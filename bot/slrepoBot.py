import os
import glob
import re
import subprocess
import pandas as pd
import random
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
import configparser
from datetime import datetime
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import textwrap

__version__ = '0.3.7'

# 설정 파일 읽기
config = configparser.ConfigParser()
config.read('slrepoBot.conf')

# 로깅 설정
log_dir = os.path.join(os.path.dirname(__file__), config['LOGGING']['log_file_dir'])
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, config['LOGGING']['log_file'])
log_max_bytes = config['LOGGING'].getint('log_max_bytes')
log_backup_count = config['LOGGING'].getint('log_backup_count')

handler = RotatingFileHandler(
    log_file,
    maxBytes=log_max_bytes,
    backupCount=log_backup_count
)
logging.basicConfig(
    handlers=[handler],
    level=getattr(logging, config['LOGGING']['log_level']),
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Slack 앱 토큰, 봇 토큰
SLACK_APP_TOKEN = config['SLACK']['app_token']
SLACK_BOT_TOKEN = config['SLACK']['bot_token']

# AsyncApp 초기화
app = AsyncApp(token=SLACK_BOT_TOKEN)

# 큐 설정 및 초기화 (큐 설정을 할 경우 redis 설치 필요)
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
CSV_FILE = get_latest_csv_file(
    os.path.join(os.path.dirname(__file__), config['FILES']['csv_file_dir']),
    config['FILES']['csv_file_prefix'],
    config['FILES']['csv_file_extension']
)

# 점심메뉴 추천
LUNCH_CSV_FILE = os.path.join(os.path.dirname(__file__), config['FILES']['csv_file_dir'], 'babzip.csv')

def read_extdata_file(filename):
    if filename.endswith('babzip.csv'):
        return pd.read_csv(filename, encoding='utf-8')
    else:
        return pd.read_csv(filename, encoding='euc-kr')

def read_lunch_csv():
    return read_extdata_file(LUNCH_CSV_FILE)

def get_random_menu(df, cuisine=None):
    if cuisine and cuisine != '그냥추천':
        df = df[df['구분'] == cuisine]

    if df.empty:
        return None
    
    restaurant = df.sample(n=1).iloc[0]
    menus = [restaurant['메뉴1'], restaurant['메뉴2'], restaurant['메뉴3']]
    menu = random.choice([m for m in menus if pd.notna(m)])

    return {
        '식당': restaurant['식당'],
        '메뉴': menu,
        '링크': restaurant['링크']
    }

# 버튼 생성 함수
def create_buttons():
    df = read_lunch_csv()
    cuisines = df['구분'].unique().tolist()
    cuisines.append('그냥추천')

    buttons = []
    for cuisine in cuisines:
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": cuisine},
            "value": cuisine,
            "action_id": f"lunch_recommendation_{cuisine}"
        })

    return {
        "type": "actions",
        "elements": buttons
    }

def load_template(template_name):
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, 'slrepoBot.conf')
        
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        
        if 'TEMPLATES' not in config:
            logging.error("TEMPLATES section not found in config file.")
            return None
        
        template = config['TEMPLATES'][template_name]
        template = template.replace('##', '\n')
        template = textwrap.dedent(template)
        
        if not template.strip():
            logging.error("Template {template_name} is empty or contains only whitespace.")
            return None
        
        return template
    except Exception as e:
        logging.error(f"Failed to load template {template_name}: {str(e)}", exc_info=True)
        return None

# 템플릿 설정
INFO_TEMPLATE = load_template('info_template')
MNGT_TEMPLATE = load_template('mngt_template')

if INFO_TEMPLATE is None:
    logging.critical("Failed to load INFO_TEMPLATE. Application cannot proceed.")
    raise SystemExit("Critical error: Failed to load template")

async def process_report(ip, time, channel_id, user_id):
    logging.info(f"요청 <@{user_id}> 대상 서버IP {ip}")
    try:
        out_dir = os.path.join(os.path.dirname(__file__), config['FILES']['out_file_dir'])
        os.makedirs(out_dir, exist_ok=True)
        
        request_id = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        command = [
            "python3",
            os.path.join(os.path.dirname(__file__), "..", "report", "promblueReport.py"),
            "--target", ip,
            "--output", out_dir,
            "--request-id", request_id
        ]
        if time:
            command.extend(["--time", time])
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=config['QUEUE'].getint('timeout', fallback=300)
        )
        
        output_file = next((line.split(": ")[1].strip() for line in result.stdout.split('\n') if line.startswith("Report generated successfully:")), None)
        
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

@app.command("/server_report")
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

async def handle_server_command(ack, say, command, template):
    await ack()
    text = command['text']
    match = re.match(r'(\S+)', text)

    if not match:
        await say(f"잘못된 형식입니다. 사용법: {command['command']} <IP>")
        return
    
    ip = match.group(1)

    try:
        df = read_extdata_file(CSV_FILE)
        server_info = df[(df['사설IP'] == ip) | (df['공인/NAT IP'] == ip)]
        
        if server_info.empty:
            await say(f"{ip}에 해당하는 서버 정보를 찾을 수 없습니다.")
            return
        
        formatted_info = template
        for column in server_info.columns:
            placeholder = f"{{{column}}}"
            if placeholder in formatted_info:
                value = server_info[column].values[0]
                # 칼럼값이 없을때 치환문자
                value = '-' if pd.isna(value) or value == '' else str(value)
                formatted_info = formatted_info.replace(placeholder, value)
        
        await say(formatted_info)
    
    except Exception as e:
        logging.error(f"Error occurred while handling {command['command']} command: {str(e)}", exc_info=True)
        await say(f"서버 정보 조회 중 오류가 발생했습니다: {str(e)}")

@app.command("/server_info")
async def handle_server_info_command(ack, say, command):
    await handle_server_command(ack, say, command, INFO_TEMPLATE)

@app.command("/server_mngt")
async def handle_server_mngt_command(ack, say, command):
    await handle_server_command(ack, say, command, MNGT_TEMPLATE)

@app.command("/조보아씨이리와봐유")
async def handle_lunch_command(ack, say):
    await ack()
    buttons = create_buttons()
    await say(
        text="메뉴 좀 골라봐유",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "오늘은 뭐가 땡겨유?"}
            },
            buttons
        ]
    )

async def show_progress(body, say):
    progress_message = await say("메뉴를 번개같이 골라주니께 긴장타봐유.. :thinking_face:")

    # 진행 표시줄 이모지 & 업데이트
    progress_emojis = [":fork_and_knife:", ":rice:", ":hamburger:", ":pizza:", ":sushi:", ":curry:", ":cut_of_meat:", ":stew:"]

    for _ in range(5):
        progress = "".join(random.choices(progress_emojis, k=random.randint(2, 6)))
        await app.client.chat_update(
            channel=progress_message['channel'],
            ts=progress_message['ts'],
            text=f"메뉴를 번개같이 골라주니께 긴장타봐유.. {progress}"
        )
        await asyncio.sleep(random.uniform(0.2, 0.7))
    
    return progress_message

async def handle_cuisine_selection(body, say, cuisine):
    progress_message = await show_progress(body, say)

    df = read_lunch_csv()
    recommendation = get_random_menu(df, cuisine)

    if recommendation:
        text = f"추천헐께유"
        await app.client.chat_update(
            channel=progress_message['channel'],
            ts=progress_message['ts'],
            text=text,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"오늘은 *{recommendation['식당']}* 가서 *{recommendation['메뉴']}* 한번 씹어봐유"}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "어딘지 모르면 눌러봐유"},
                            "url": recommendation['링크']
                        }
                    ]
                }
            ]
        )
    
        await app.client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text="추천은 맘에 드는겨?",
            blocks=[
                {
                    "type": "sections",
                    "text": {"type": "mrkdwn", "text": "추천은 맘에 드는겨?"}
                }
            ]
        )
    else:
        await app.client.chat_update(
            channel=progress_message['channel'],
            ts=progress_message['ts'],
            text=f"{cuisine} 메뉴가 읍는디?"
        )

@app.action("lunch_recommendation_한식")
async def handle_korean_food(ack, body, say):
    await ack()
    await handle_cuisine_selection(body, say, '한식')

@app.action("lunch_recommendation_중식")
async def handle_chinese_food(ack, body, say):
    await ack()
    await handle_cuisine_selection(body, say, '중식')

@app.action("lunch_recommendation_일식")
async def handle_japanese_food(ack, body, say):
    await ack()
    await handle_cuisine_selection(body, say, '일식')

@app.action("lunch_recommendation_그냥추천")
async def handle_random_food(ack, body, say):
    await ack()
    await handle_cuisine_selection(body, say, '그냥추천')

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