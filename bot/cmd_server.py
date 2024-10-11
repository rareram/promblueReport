import os
import re
import subprocess
import pandas as pd
import asyncio
from slack_bolt.async_app import AsyncApp
import logging
import glob
from datetime import datetime

class ServerManager:
    def __init__(self, app: AsyncApp, config, queue, check_permission, get_user_info, filter_data):
        self.app = app
        self.config = config
        self.queue = queue
        self.check_permission = check_permission
        self.get_user_info = get_user_info
        self.filter_data = filter_data
        self.logger = logging.getLogger(__name__)
        self.CSV_FILE = self.get_latest_csv_file(
            os.path.join(os.path.dirname(__file__), config['FILES']['csv_file_dir']),
            config['FILES']['csv_file_prefix'],
            config['FILES']['csv_file_extension']
        )

        # 슬래시 명령어 핸들러 등록
        app.command("/server_report")(self.handle_report_command)
        app.command("/server_info")(self.handle_server_info_command)
        app.command("/server_mngt")(self.handle_server_mngt_command)

    def get_latest_csv_file(self, directory, prefix, extension):
        pattern = os.path.join(directory, f"{prefix}*{extension}")
        files = glob.glob(pattern)
        if not files:
            raise FileNotFoundError(f"No files found matching the pattern: {pattern}")
        return max(files, key=os.path.getctime)

    def read_extdata_file(self, filename):
        return pd.read_csv(filename, encoding='euc-kr')

    # 보고서 생성 로직
    async def process_report(self, ip, time, channel_id, user_id, thread_ts=None):
        self.logger.info(f"요청 <@{user_id}> 대상 서버IP {ip}")
        try:
            out_dir = os.path.join(os.path.dirname(__file__), self.config['FILES']['out_file_dir'])
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
                timeout=self.config['QUEUE'].getint('timeout', fallback=300)
            )
        
            output_file = next((line.split(": ")[1].strip() for line in result.stdout.split('\n') if line.startswith("Report generated successfully:")), None)
        
            if output_file and os.path.exists(output_file):
                time_display = "오늘 0시부터 현재까지" if time == 'today' else time
                # await app.client.files_upload(
                await self.app.client.files_upload_v2(
                    channels=channel_id,
                    file=output_file,
                    initial_comment=f"<@{user_id}> {ip}에 대한 {time_display} 기간의 보고서입니다.",
                    thread_ts=thread_ts
                )
                await self.app.client.chat_postMessage(
                    channel=channel_id,
                    text=f"<@{user_id}> 보고서가 성공적으로 업로드되었습니다.",
                    thread_ts=thread_ts
                )
                self.logger.info(f"완료 <@{user_id}> 대상 서버IP {ip}")
            else:
                await self.app.client.chat_postMessage(
                    channel=channel_id,
                    text=f"<@{user_id}> 보고서 파일을 생성하지 못했습니다.",
                    thread_ts=thread_ts
                )
                self.logger.error(f"실패 <@{user_id}> 대상 서버IP {ip} - 파일 생성 실패")
        except subprocess.TimeoutExpired:
            await self.app.client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> 보고서 생성 시간이 초과되었습니다.")
            self.logger.error(f"실패 <@{user_id}> 대상 서버IP {ip} - 시간 초과")
        except Exception as e:
            await self.app.client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> 보고서 생성 중 오류가 발생했습니다: {str(e)}")
            self.logger.error(f"실패 <@{user_id}> 대상 서버IP {ip} - 오류: {str(e)}")

    # @app.command("/server_report")
    async def handle_report_command(self, ack, say, command):
        await ack()
        user_group = self.check_permission(command['user_id'], command.get('user_email'), 'server_report')
        if not user_group:
            await say("명령어 실행 권한이 없습니다.")
            return
    
        match = re.match(r'(\S+)(?:\s+(\S+))?', command['text'])
        if not match:
            await say("잘못된 형식입니다. 사용법: /report <IP> [기간옵션; 1d, 7d]")
            self.logger.warning(f"잘못된 형식 요청 <@{command['user_id']}> 텍스트: {command['text']}")
            return
    
        ip, time = match.groups()
        time = time or 'today'

        self.logger.info(f"요청 접수 <@{command['user_id']}> 대상 서버IP {ip} 기간 {time}")

        use_thread = self.config['THREAD_OPTIONS'].getboolean('server_report_thread', fallback=False)
        initial_message = await say(f"<@{command['user_id']}> 보고서 생성 요청을 받았습니다. 처리 중입니다...")

        thread_ts = initial_message['ts'] if use_thread else None
        asyncio.create_task(self.process_report(ip, time, command['channel_id'], command['user_id'], thread_ts))

        self.logger.info(f"Command executed: {command['command']} - User: {command['user_id']} ({command.get('user_email')}) - Group: {user_group} - Params: {command['text']}")

    # 명령어 처리 로직 - csv 에서 정보 조회
    async def handle_server_command(self, ack, say, command, template, client):
        await ack()
        user_id = command['user_id']
        user_email = command.get('user_email')

        if not user_email:
            user_info = await self.get_user_info(self.app.client, user_id)
            user_email = user_info.get('profile', {}).get('email') if user_info else None

        user_group = self.check_permission(user_id, user_email, command['command'][1:])
        if not user_group:
            await say("명령어 실행 권한이 없습니다.")
            return
    
        match = re.match(r'(\S+)', command['text'])
        if not match:
            await say(f"잘못된 형식입니다. 사용법: {command['command']} <IP>")
            return
    
        ip = match.group(1)

        try:
            df = self.read_extdata_file(self.CSV_FILE)
            self.logger.info(f"Original dataframe columns: {df.columns.tolist()}")
        
            df = self.filter_data(df, user_group)
            self.logger.info(f"Filtered dataframe columns: {df.columns.tolist()}")
        
            server_info = df[(df['사설IP'] == ip) | (df['공인/NAT IP'] == ip)]
        
            if server_info.empty:
                await say(f"{ip}에 해당하는 서버 정보를 찾을 수 없습니다.")
                return
        
            formatted_info = template.replace('##', '\n')
            for column, value in server_info.iloc[0].items():
                placeholder = f"{{{column}}}"
                if placeholder in formatted_info:
                    value = '-' if pd.isna(value) or value == '' else str(value)
                    formatted_info = formatted_info.replace(placeholder, value)
        
            await say(formatted_info)
        except Exception as e:
            self.logger.error(f"Error occurred while handling {command['command']} command: {str(e)}", exc_info=True)
            await say(f"서버 정보 조회 중 오류가 발생했습니다: {str(e)}")
    
        self.logger.info(f"Command executed: {command['command']} - User: {user_id} ({user_email}) - Group: {user_group} - Params: {command['text']}")

    # @app.command("/server_info")
    async def handle_server_info_command(self, ack, say, command, client):
        await self.handle_server_command(ack, say, command, self.config['TEMPLATES']['info_template'], client)

    # @app.command("/server_mngt")
    async def handle_server_mngt_command(self, ack, say, command, client):
        await self.handle_server_command(ack, say, command, self.config['TEMPLATES']['mngt_template'], client)

def init(app: AsyncApp, config, queue, check_permission, get_user_info, filter_data):
    ServerManager(app, config, queue, check_permission, get_user_info, filter_data)