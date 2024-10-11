import re
import aiohttp
import asyncio
from slack_bolt.async_app import AsyncApp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image
import io
import logging

class WebChecker:
    def __init__(self, app: AsyncApp, config):
        self.app = app
        self.config = config
        self.logger = logging.getLogger(__name__)

        app.command("/check_web_b2b")(self.handle_check_web_command)
        app.command("/check_web_b2c")(self.handle_check_web_command)
        app.command("/check_web_b2e")(self.handle_check_web_command)
        app.command("/check_web_blue")(self.handle_check_web_command)
        app.action(re.compile("check_web_.*"))(self.handle_all_check_web_action)

    # 웹 서비스 상태 확인 로직
    async def check_website(self, url):
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
            self.logger.error(f"Error checking website {url}: {str(e)}")
            return None, None

    # 웹 서비스 목록별 버튼 생성 로직
    def create_web_service_buttons(self, service_type, capture_mode=False):
        services = self.config[f'WEB_SERVICES_{service_type}']
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

    # 웹사이트 캡처 로직
    async def capture_website(self, url):
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

    # 캡처 진행 progress 표시
    async def show_capture_progress(self, client, channel, thread_ts=None):
        progress_message = await client.chat_postMessage(
            channel=channel,
            text="_웹사이트를 캡쳐하는 중입니다.._ :hourglass_flowing_sand:",
            thread_ts=thread_ts
        )

        for _ in range(2):            # 2번 업데이트
            await asyncio.sleep(0.5)  # 0.5초 대기
            await client.chat_update(
                channel=channel,
                ts=progress_message['ts'],
                text=f"_웹사이트를 캡처하는 중입니다.._ :hourglass_flowing_sand: {'.' * (_ + 1)}"
            )
    
        return progress_message

    async def handle_check_web_command(self, ack, say, command, logger):
        await ack()
        service_type = command['command'].split('_')[-1].upper()

        capture_mode = 'capture' in command['text'].lower()

        buttons = self.create_web_service_buttons(service_type, capture_mode)
        self.logger.info(f"Created buttons for {service_type}: {buttons}")

        message = f"{service_type} 상태를 확인할 웹서비스를 선택하세요."
        if capture_mode:
            message += " (캡처 모드 :camera_with_flash:)"
    
        use_thread = self.config['THREAD_OPTIONS']['check_web_thread']

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
    # @app.action(re.compile("check_web_.*"))
    async def handle_all_check_web_action(self, ack, body, say):
        await ack()
        action = body['actions'][0]
        action_id = action['action_id']
        url, capture_mode = action['value'].split('|')
        capture_mode = capture_mode.lower() == 'true'
        service_name = action['text']['text']

        self.logger.info(f"Action triggered: {action_id}")
        self.logger.info(f"Checking website: {service_name} ({url})")
    
        status, response_time = await self.check_website(url)
    
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
            use_thread = self.config['THREAD_OPTIONS'].getboolean('check_web_thread', fallback=False)
            thread_ts = status_message['ts'] if use_thread else None
            asyncio.create_task(self.capture_website_task(self.app.client, body['channel']['id'], service_name, url, thread_ts))

    # 웹 서비스 캡처 작업
    async def capture_website_task(self, client, channel_id, service_name, url, thread_ts):
        try:
            progress_message = await self.show_capture_progress(client, channel_id, thread_ts)
        
            screenshot_data = await self.capture_website(url)

            await client.files_upload_v2(
                channel=channel_id,
                file=screenshot_data,
                filename=f"{service_name}_screenshot.png",
                title=f"{service_name} 캡처 이미지",
                initial_comment=f"{service_name} ({url})의 캡처 이미지입니다.",
                thread_ts=thread_ts
            )

            # 캡처 완료 메시지로 업데이트
            await client.chat_update(
                channel=channel_id,
                ts=progress_message['ts'],
                text=f"_웹사이트 캡처가 완료되었습니다._ :white_check_mark:"
            )

        except Exception as e:
            self.logger.error(f"Failed to capture website: {str(e)}")
            await client.chat_postMessage(
                channel=channel_id,
                text=f"웹사이트 캡처 중 오류가 발생했습니다: {str(e)}",
                thread_ts=thread_ts
            )

def init(app: AsyncApp, config):
    WebChecker(app, config)