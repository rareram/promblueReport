import os
import glob
import re
import subprocess
import pandas as pd
import random
import aiohttp
import asyncio
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
import configparser
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import textwrap
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image
import io
import tempfile

__version__ = '0.5.13'

# 설정 파일 읽기 및 로그 포멧 설정
def setup_config_and_logging():
    config = configparser.ConfigParser()
    config.read('slrepoBot.conf')

    log_dir = os.path.join(os.path.dirname(__file__), config['LOGGING']['log_file_dir'])
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, config['LOGGING']['log_file'])
    log_max_bytes = config['LOGGING'].getint('log_max_bytes')
    log_backup_count = config['LOGGING'].getint('log_backup_count')

    # 스레드 옵션
    config['THREAD_OPTIONS'] = {
        'check_web_thread': config.getboolean('THREAD_OPTIONS', 'check_web_thread', fallback=False),
        'server_report_thread': config.getboolean('THREAD_OPTIONS', 'server_report_thread')
    }

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

    return config

config = setup_config_and_logging()

# 슬랙 앱 초기화
SLACK_APP_TOKEN = config['SLACK']['app_token']
SLACK_BOT_TOKEN = config['SLACK']['bot_token']
app = AsyncApp(token=SLACK_BOT_TOKEN)

# 데이터 파일 핸들링
def get_latest_csv_file(directory, prefix, extension):
    pattern = os.path.join(directory, f"{prefix}*{extension}")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"No files found matching the pattern: {pattern}")
    return max(files, key=os.path.getctime)

CSV_FILE = get_latest_csv_file(
    os.path.join(os.path.dirname(__file__), config['FILES']['csv_file_dir']),
    config['FILES']['csv_file_prefix'],
    config['FILES']['csv_file_extension']
)

LUNCH_CSV_FILE = os.path.join(os.path.dirname(__file__), config['FILES']['csv_file_dir'], 'babzip.csv')

def read_extdata_file(filename):
    encoding = 'utf-8' if filename.endswith('babzip.csv') else 'euc-kr'
    return pd.read_csv(filename, encoding=encoding)

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

# 유저그룹 별 권한 제어
async def get_user_info(client, user_id):
    try:
        result = await client.users_info(user=user_id)
        return result["user"]
    except Exception as e:
        logging.error(f"Error fetching user info: {str(e)}")
        return None

def check_permission(user_id, user_email, command):
    if not user_email:
        logging.warning(f"User email not available for user {user_id}")
        user_email = ""
    
    admin_domains = config['ACCESS_CONTROL'].get('admin_domains', '').split(', ')
    admin_slack_ids = config['ACCESS_CONTROL'].get('admin_slack_ids', '').split(', ')
    user_domains = config['ACCESS_CONTROL'].get('user_domains', '').split(', ')
    user_slack_ids = config['ACCESS_CONTROL'].get('user_slack_ids', '').split(', ')
    guest_domains = config['ACCESS_CONTROL'].get('guest_domains', '*').split(', ')
    
    allowed_groups = config['COMMAND_PERMISSIONS'].get(command, '').split(', ')
    
    user_domain = user_email.split('@')[1] if '@' in user_email else ''
    
    if 'admin' in allowed_groups and (user_domain in admin_domains or user_id in admin_slack_ids):
        return 'admin'
    elif 'user' in allowed_groups and (user_domain in user_domains or user_id in user_slack_ids):
        return 'user'
    elif 'guest' in allowed_groups and (guest_domains == ['*'] or user_domain in guest_domains):
        return 'guest'
    else:
        return None

def filter_data(df, user_group):
    if user_group == 'admin':
        logging.info("Admin user, no filtering applied")
        return df
    
    filtered_columns = config['DATA_FILTERING']['filtered_columns'].split(', ')
    logging.info(f"Filtering columns for {user_group}: {filtered_columns}")
    
    for column in filtered_columns:
        if column in df.columns:
            df[column] = '***filtered***'
            logging.info(f"Column {column} filtered")
        else:
            logging.warning(f"Column {column} not found in dataframe")
    
    return df

# 템플릿 로드
def load_template(template_name):
    try:
        template = config['TEMPLATES'][template_name]
        template = template.replace('##', '\n')
        return textwrap.dedent(template)
    except Exception as e:
        logging.error(f"Failed to load template {template_name}: {str(e)}")
        return None

INFO_TEMPLATE = load_template('info_template')
MNGT_TEMPLATE = load_template('mngt_template')

if INFO_TEMPLATE is None:
    logging.critical("Failed to load INFO_TEMPLATE. Application cannot proceed.")
    raise SystemExit("Critical error: Failed to load template")

# 슬래시 명령어
# async def process_report(ip, time, channel_id, user_id):
async def process_report(ip, time, channel_id, user_id, thread_ts=None):
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
            # await app.client.files_upload(
            await app.client.files_upload_v2(
                channels=channel_id,
                file=output_file,
                initial_comment=f"<@{user_id}> {ip}에 대한 {time_display} 기간의 보고서입니다.",
                thread_ts=thread_ts
            )
            await app.client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> 보고서가 성공적으로 업로드되었습니다.",
                thread_ts=thread_ts
            )
            logging.info(f"완료 <@{user_id}> 대상 서버IP {ip}")
        else:
            await app.client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> 보고서 파일을 생성하지 못했습니다.",
                thread_ts=thread_ts
            )
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
    user_group = check_permission(command['user_id'], command.get('user_email'), 'server_report')
    if not user_group:
        await say("명령어 실행 권한이 없습니다.")
        return
    
    match = re.match(r'(\S+)(?:\s+(\S+))?', command['text'])
    if not match:
        await say("잘못된 형식입니다. 사용법: /report <IP> [기간옵션; 1d, 7d]")
        logging.warning(f"잘못된 형식 요청 <@{command['user_id']}> 텍스트: {command['text']}")
        return
    
    ip, time = match.groups()
    time = time or 'today'

    logging.info(f"요청 접수 <@{command['user_id']}> 대상 서버IP {ip} 기간 {time}")

    use_thread = config['THREAD_OPTIONS'].getboolean('server_report_thread', fallback=False)
    initial_message = await say(f"<@{command['user_id']}> 보고서 생성 요청을 받았습니다. 처리 중입니다...")

    thread_ts = initial_message['ts'] if use_thread else None
    asyncio.create_task(process_report(ip, time, command['channel_id'], command['user_id'], thread_ts))

    logging.info(f"Command executed: {command['command']} - User: {command['user_id']} ({command.get('user_email')}) - Group: {user_group} - Params: {command['text']}")

async def handle_server_command(ack, say, command, template, client):
    await ack()
    user_id = command['user_id']
    user_email = command.get('user_email')

    if not user_email:
        user_info = await get_user_info(client, user_id)
        user_email = user_info.get('profile', {}).get('email') if user_info else None

    user_group = check_permission(user_id, user_email, command['command'][1:])
    if not user_group:
        await say("명령어 실행 권한이 없습니다.")
        return
    
    match = re.match(r'(\S+)', command['text'])
    if not match:
        await say(f"잘못된 형식입니다. 사용법: {command['command']} <IP>")
        return
    
    ip = match.group(1)

    try:
        df = read_extdata_file(CSV_FILE)
        logging.info(f"Original dataframe columns: {df.columns.tolist()}")
        
        df = filter_data(df, user_group)
        logging.info(f"Filtered dataframe columns: {df.columns.tolist()}")
        
        server_info = df[(df['사설IP'] == ip) | (df['공인/NAT IP'] == ip)]
        
        if server_info.empty:
            await say(f"{ip}에 해당하는 서버 정보를 찾을 수 없습니다.")
            return
        
        formatted_info = template
        for column, value in server_info.iloc[0].items():
            placeholder = f"{{{column}}}"
            if placeholder in formatted_info:
                value = '-' if pd.isna(value) or value == '' else str(value)
                formatted_info = formatted_info.replace(placeholder, value)
        
        await say(formatted_info)
    except Exception as e:
        logging.error(f"Error occurred while handling {command['command']} command: {str(e)}", exc_info=True)
        await say(f"서버 정보 조회 중 오류가 발생했습니다: {str(e)}")
    
    logging.info(f"Command executed: {command['command']} - User: {user_id} ({user_email}) - Group: {user_group} - Params: {command['text']}")

@app.command("/server_info")
async def handle_server_info_command(ack, say, command, client):
    await handle_server_command(ack, say, command, INFO_TEMPLATE, client)

@app.command("/server_mngt")
async def handle_server_mngt_command(ack, say, command, client):
    await handle_server_command(ack, say, command, MNGT_TEMPLATE, client)

# 웹 서비스 상태 확인 함수
async def check_website(url):
    try:
        async with aiohttp.ClientSession() as session:
            start_time = asyncio.get_event_loop().time()
            async with session.get(url, allow_redirects=True, timeout=5) as response:
                end_time = asyncio.get_event_loop().time()
                response_time = end_time - start_time
                status = response.status
                return status, response_time
    except asyncio.TimeoutError:
        return None, None
    except Exception as e:
        logging.error(f"Error checking website {url}: {str(e)}")
        return None, None

# 웹 서비스 목록 생성 함수
def create_web_service_buttons(service_type, capture_mode=False):
    services = config[f'WEB_SERVICES_{service_type}']
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": service_info.split(',')[0].strip()},
                "value": f"{service_info.split(',')[1].strip()}|{capture_mode}",
                "action_id": f"check_web_{service_type}_{service_key}"
            } for service_key, service_info in services.items()
        ]
    }

# 웹 서비스 캡처
async def capture_website(url):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(url)
        driver.set_window_size(1920, 1080)
        screenshot = driver.get_screenshot_as_png()
        image = Image.open(io.BytesIO(screenshot))

        # with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            # image.save(temp_file.name)
            # return temp_file.name
        with io.BytesIO() as output:
            image.save(output, format='PNG')
            output.seek(0)
            return output.getvalue()

    finally:
        driver.quit()

async def show_capture_progress(client, channel, thread_ts):
    progress_message = await client.chat_postMessage(
        channel=channel,
        text="_웹사이트를 캡쳐하는 중입니다.._ :hourglass_flowing_sand:",
        thread_ts=thread_ts
    )

    for _ in range(3):         # 3번 업데이트
        await asyncio.sleep(1) # 1초 대기
        await client.chat_update(
            channel=channel,
            ts=progress_message['ts'],
            text=f"_웹사이트를 캡처하는 중입니다.._ :hourglass_flowing_sand: {'.' * (_ + 1)}"
        )
    
    return progress_message

# 웹 서비스 상태 확인 명령어 핸들러
@app.command("/check_web_b2b")
@app.command("/check_web_b2c")
@app.command("/check_web_b2e")
@app.command("/check_web_blue")
async def handle_check_web_command(ack, say, command, logger):
    await ack()
    service_type = command['command'].split('_')[-1].upper()

    capture_mode = 'capture' in command['text'].lower()

    buttons = create_web_service_buttons(service_type, capture_mode)
    logger.info(f"Created buttons for {service_type}: {buttons}")

    message = f"{service_type} 상태를 확인할 웹서비스를 선택하세요."
    if capture_mode:
        message += " (캡처 모드 :camera_with_flash:)"
    
    use_thread = config['THREAD_OPTIONS']['check_web_thread']

    initial_message = await say(
        text=message,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message}
            },
            buttons
        ]
    )

    return initial_message['ts'] if use_thread else None

# 웹 서비스 상태 확인 버튼 핸들러
@app.action(re.compile("check_web_.*"))
async def handle_all_check_web_action(ack, body, say, logger):
    await ack()
    action = body['actions'][0]
    action_id = action['action_id']
    url, capture_mode = action['value'].split('|')
    capture_mode = capture_mode.lower() == 'true'
    service_name = action['text']['text']

    logger.info(f"Action triggered: {action_id}")
    logger.info(f"Checking website: {service_name} ({url})")
    
    status, response_time = await check_website(url)
    
    if status == 200:
        status_emoji = ":large_green_circle:"
        if response_time < 1:
            speed_emoji = ":zap:"
        elif response_time < 3:
            speed_emoji = ":turtle:"
        else:
            speed_emoji = ":sloth:"
        message = f"▪ *상태:* {status_emoji} (*{service_name}* {url} 접속 *정상*)\n▪ *속도:* {speed_emoji} (응답 시간: *{response_time:.2f}* 초)"
    elif status is not None:
        emoji = ":large_yellow_circle:"
        message = f"{emoji} *{service_name}* 서비스 웹({url})가 비정상입니다. 상태 코드: {status}"
    else:
        emoji = ":red_circle:"
        message = f"{emoji} *{service_name}* 서비스 웹({url})에 접근할 수 없습니다."
    
    status_message = await say(message)
    # thread_ts = status_message['ts'] 

    if capture_mode:
        use_thread = config['THREAD_OPTIONS'].getboolean('check_web_thread', fallback=False)
        thread_ts = status_message['ts'] if use_thread else None
        asyncio.create_task(capture_website_task(app.client, body['channel']['id'], service_name, url, thread_ts))

async def capture_website_task(client, channel_id, service_name, url, thread_ts):
    try:
        progress_message = await show_capture_progress(client, channel_id, thread_ts)
        
        screenshot_data = await capture_website(url)

        await client.files_upload_v2(
            channel=channel_id,
            file=screenshot_data,
            filename=f"{service_name}_screenshot.png",
            title=f"{service_name} 캡처 이미지",
            initial_comment=f"{service_name} ({url})의 캡처 이미지입니다.",
            thread_ts=thread_ts
        )

        # 캡처 완료 메시지로 업데이트
        await app.client.chat_update(
            channel=channel_id,
            ts=progress_message['ts'],
            text=f"_웹사이트 캡처가 완료되었습니다._ :white_check_mark:"
        )

    except Exception as e:
        logging.error(f"Failed to capture website: {str(e)}")
        await client.chat_postMessage(
            channel=channel_id,
            text=f"웹사이트 캡처 중 오류가 발생했습니다: {str(e)}",
            thread_ts=thread_ts
        )

# 점심 추천 기능
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

def create_buttons():
    df = read_lunch_csv()
    cuisines = df['구분'].unique().tolist()

    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": cuisine},
                "value": cuisine,
                "action_id": f"lunch_recommendation_{cuisine}"
            } for cuisine in cuisines
        ] + [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "랜덤 돌려유?"},
                "value": "random",
                "action_id": "lunch_recommendation_random"
            }
        ]
    }

@app.command("/조보아씨이리와봐유")
async def handle_lunch_command(ack, say):
    await ack()
    buttons = create_buttons()
    await say(
        text="장르 좀 골라봐유",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "어떤 장르로 추천해볼까유?"}
            },
            buttons
        ]
    )

async def show_progress(say):
    progress_message = await say("메뉴 번개같이 골라줄테니께 긴장타봐유.. :thinking_face:")
    progress_emojis = [":fork_and_knife:", ":rice:", ":hamburger:", ":pizza:", ":sushi:", ":curry:", ":cut_of_meat:", ":stew:"]

    for _ in range(5):
        progress = "".join(random.choices(progress_emojis, k=random.randint(3, 6)))
        await app.client.chat_update(
            channel=progress_message['channel'],
            ts=progress_message['ts'],
            text=f"메뉴 번개같이 골라줄테니께 긴장타봐유.. {progress}"
        )
        await asyncio.sleep(random.uniform(0.2, 0.6))
    
    return progress_message

async def handle_cuisine_selection(body, say, cuisine):
    progress_message = await show_progress(say)

    df = read_lunch_csv()
    recommendation = get_random_menu(df, cuisine)

    if recommendation:
        await app.client.chat_update(
            channel=progress_message['channel'],
            ts=progress_message['ts'],
            text="추천헐께유",
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
    
        await say(
            text="추천은 맘에 드는겨?",
            blocks=[
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": "*추천은 맘에 드는겨?*"
                        },
                        {
                            "type": "mrkdwn",
                            "text": " "    # 빈칸으로 레이아웃 조정
                        }
                    ]
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "한번 더혀?"},
                            "action_id": "lunch_recommendation_random"
                        }
                    ]
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

@app.action("lunch_recommendation_random")
async def handle_random_food(ack, body, say):
    await ack()
    await handle_cuisine_selection(body, say, None)

@app.command("/bot_ver")
async def handle_version_command(ack, say, command):
    await ack()
    if command['text']:
        await say(f"참고: '/bot_ver' 명령어는 추가 파라미터를 필요로 하지 않습니다. 입력하신 '{command['text']}'는 무시됩니다.")
    await say(f"현재 슬리포봇(slrepoBot) 버전: {__version__}")

async def main():
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    try:
        await handler.start_async()
        logging.info("slrepoBot v{__version__} is running!")
        while True:
            await asyncio.sleep(3600)
    finally:
        await handler.close()
        if app.client.session:
            await app.client.session.close()

if __name__ == "__main__":
    print(f"Starting slrepoBot v{__version__}")
    asyncio.run(main())