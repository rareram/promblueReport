import os
import glob
import re
import subprocess
import pandas as pd
# from slack_bolt import App
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.errors import SlackApiError
import configparser
from datetime import datetime
import asyncio
import logging

__version__ = '0.2.7'

# 설정 파일 읽기
config = configparser.ConfigParser()
config.read('slrepoBot.conf')

# 문서 생성 로깅 설정
log_dir = os.path.join(os.path.dirname(__file__), config['LOGGING']['log_file_dir'])
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, config['LOGGING']['log_file'])
logging.basicConfig(
    filename=log_file,
    level=getattr(logging, config['LOGGING']['log_level']),
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Slack 앱 토큰, 봇 토큰
SLACK_APP_TOKEN = config['SLACK']['app_token']
SLACK_BOT_TOKEN = config['SLACK']['bot_token']

# AsyncApp 초기화
app = AsyncApp(token=SLACK_BOT_TOKEN)

# 큐 설정 및 초기화 (큐 설정을 할 경우 redis 설치 필요)
# USE_QUEUE = config['QUEUE'].getboolean('use_queue', fallback=False)
# TIMEOUT = config['QUEUE'].getint('timeout', fallback=300)
if config['QUEUE'].getboolean('use_queue', fallback=False):
    import redis
    from rq import Queue
    from rq.job import Job

    redis_conn = redis.Redis(
        host=config['QUEUE']['redis_host'],
        port=config['QUEUE'].getint('redis_port'),
        db=config['QUEUE'].getint('redis_db')
    )
    queue = Queue(connection=redis_conn)
else:
    queue = None

def get_latest_csv_file(directory, prefix, extension):
    pattern = os.path.join(directory, f"{prefix}*{extension}")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"No files found matching the pattern: {pattern}")
    return max(files, key=os.path.getctime)

# CSV 파일 경로 설정
# CSV_FILE = config['FILES']['csv_file']
CSV_FILE = get_latest_csv_file(
    os.path.join(os.path.dirname(__file__), config['FILES']['csv_file_dir']),
    config['FILES']['csv_file_prefix'],
    config['FILES']['csv_file_extension']
)

# 템플릿 및 컬럼 설정
INFO_TEMPLATE = config['TEMPLATES']['info_template']
INFO_COLUMNS = config['COLUMNS']['info_columns'].split(',')

async def process_report(ip, time, channel_id, user_id):
    logging.info(f"요청 <@{user_id}> 대상 서버IP {ip}")
    try:
        out_dir = os.path.join(os.path.dirname(__file__), config['FILES']['out_file_dir'])
        os.makedirs(out_dir, exist_ok=True)
        
        # 고유한 요청 ID 생성
        request_id = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        result = subprocess.run(
            ["python3", "../report/promblueReport.py", "--time", time, "--target", ip, "--output", out_dir, "--request-id", request_id],
            capture_output=True,
            text=True,
            check=True,
            timeout=config['QUEUE'].getint('timeout', fallback=300)
        )
        
        # 생성된 보고서 파일 찾기
        output_file = None
        for line in result.stdout.split('\n'):
            if line.startswith("Report generated successfully:"):
                output_file = line.split(": ")[1].strip()
                break
        
        if output_file and os.path.exists(output_file):
            time_display = "오늘 0시부터 현재까지" if time == 'today' else time
            await app.client.files_upload(
                channels=channel_id,
                file=output_file,
                initial_comment=f"<@{user_id}> {ip}에 대한 {time_display} 기간의 보고서입니다."
            )
            await app.client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> 보고서가 성공적으로 업로드되었습니다.")
            logging.info(f"완료 <@{user_id}> 대상 서버IP {ip}")
        else:
            await app.client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> 보고서 파일을 생성하지 못했습니다.")
            logging.error(f"실패 <@{user_id}> 대상 서버IP {ip} - 파일 생성 실패")
    except subprocess.TimeoutExpired:
        await app.client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> 보고서 생성 시간이 초과되었습니다.")
        logging.error(f"실패 <@{user_id}> 대상 서버IP {ip} - 시간 초과")
    except Exception as e:
        await app.client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> 보고서 생성 중 오류가 발생했습니다: {str(e)}")
        logging.error(f"실패 <@{user_id}> 대상 서버IP {ip} - 오류: {str(e)}")

@app.command("/report")
async def handle_report_command(ack, say, command):
    await ack()
    text = command['text']
    match = re.match(r'(\S+)(?:\s+(\S+))?', text)

    if not match:
        await say("잘못된 형식입니다. 사용법: /report <IP> [기간옵션; 1d, 7d]")
        logging.warning(f"잘못된 형식 요청 <@{command['user_id']}> 텍스트: {text}")
        return
    
    ip = match.group(1)
    time = match.group(2) if match.group(2) else 'today'

    logging.info(f"요청 접수 <@{command['user_id']}> 대상 서버IP {ip} 기간 {time}")

    await say(f"<@{command['user_id']}> 보고서 생성 요청을 받았습니다. 처리 중입니다...")
    asyncio.create_task(process_report(ip, time, command['channel_id'], command['user_id']))

@app.command("/info")
async def handle_info_command(ack, say, command):
    await ack()
    text = command['text']
    match = re.match(r'(\S+)', text)

    if not match:
        await say("잘못된 형식입니다. 사용법: /info <IP>")
        return
    
    ip = match.group(1)

    try:
        df = pd.read_csv(CSV_FILE, encoding='utf-8')
        server_info = df[(df['사설IP'] == ip) | (df['공인/NAT IP'] == ip)]

        if server_info.empty:
            await say(f"{ip}에 해당하는 서버 정보를 찾을 수 없습니다.")
            return
        
        info = INFO_TEMPLATE
        for column in INFO_COLUMNS:
            info = info.replace(f"{{{column}}}", str(server_info[column].values[0]))

        await say(info)
    
    except Exception as e:
        await say(f"서버 정보 조회 중 오류가 발생했습니다: {str(e)}")

@app.command("/bot_ver")
async def handle_version_command(ack, say, command):
    await ack()
    if command['text']:
        await say(f"참고: '/bot_ver' 명령어는 추가 파라미터를 필요로 하지 않습니다. 입력하신 '{command['text']}'는 무시됩니다.")
    await say(f"현재 슬리포봇(slrepoBot) 버전: {__version__}")

async def main():
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    await handler.start_async()

if __name__ == "__main__":
    asyncio.run(main())