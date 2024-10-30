import os
import re
import subprocess
import pandas as pd
import asyncio
from typing import Dict, List, Any, Optional, Union
from slack_bolt.async_app import AsyncApp
import logging
import glob
from datetime import datetime

class ServerManager:
    def __init__(self, app: AsyncApp, config, queue, check_permission, get_user_info, filter_data, ip_pattern, hostname_pattern):
        self.app = app
        self.config = config
        self.queue = queue
        self.check_permission = check_permission
        self.get_user_info = get_user_info
        self.filter_data = filter_data
        self.ip_pattern = re.compile(ip_pattern)
        self.hostname_pattern = re.compile(hostname_pattern)
        self.logger = logging.getLogger(__name__)

        # report 모듈을 함수로 받지 않고 인터프리터로 실행시키기 위한 루트 지정
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self.CSV_FILE = self.get_latest_csv_file(
            os.path.join(self.project_root, self.config['FILES']['csv_file_dir'].replace('./', '')),
            config['FILES']['csv_file_prefix'],
            config['FILES']['csv_file_extension']
        )
        self.CSV_FILE_NAME = os.path.basename(self.CSV_FILE)

        # 슬래시 명령어 핸들러 등록
        app.command("/server_report")(self.handle_report_command)
        app.command("/server_info")(self.handle_server_info_command)
        app.command("/server_mngt")(self.handle_server_mngt_command)
        app.command("/server_button")(self.handle_server_button_command)
        # app.action("server_info_button")(self.handle_server_info_button)
        app.action(re.compile(r"^server_info_button_\d+$"))(self.handle_server_info_button)

        # Progress display 설정 로드
        self.progress_config = {
            'bar_char': config['PROGRESS_DISPLAY'].get('progress_bar_char', '█'),
            'empty_char': config['PROGRESS_DISPLAY'].get('progress_empty_char', '▒'),
            'bar_length': config['PROGRESS_DISPLAY'].getint('progress_bar_length', 10),
            'update_interval': config['PROGRESS_DISPLAY'].getint('update_interval', 5),
            'emojis': config['PROGRESS_DISPLAY'].get('progress_emojis', '').split(','),
            'steps': config['PROGRESS_DISPLAY'].get('progress_steps', '').split(','),
            'start_message': config['PROGRESS_DISPLAY'].get('start_message', '보고서 생성을 시작합니다...'),
            'complete_message': config['PROGRESS_DISPLAY'].get('complete_message', '보고서 생성이 완료되었습니다.'),
            'error_message': config['PROGRESS_DISPLAY'].get('error_message', '보고서 생성 중 오류가 발생했습니다.'),
            'timeout_message': config['PROGRESS_DISPLAY'].get('timeout_message', '보고서 생성 시간이 초과되었습니다.')
        }
    
        self.logger.info("ServerManager initialized with action handlers")
        self.logger.debug(r"Registered action handler for pattern: ^server_info_button_\d+$")

    def get_latest_csv_file(self, directory, prefix, extension):
        pattern = os.path.join(directory, f"{prefix}*{extension}")
        files = glob.glob(pattern)
        if not files:
            raise FileNotFoundError(f"No files found matching the pattern: {pattern}")
        return max(files, key=os.path.getctime)

    def read_extdata_file(self, filename):
        return pd.read_csv(filename, encoding='euc-kr')

    # 보고서 생성 진행상태 메시지
    async def update_progress_message(self, client, channel_id, message_ts, current_step, total_steps, step_name):
        try:
            filled = int(self.progress_config['bar_length'] * current_step / total_steps)
            bar = (self.progress_config['bar_char'] * filled + 
                   self.progress_config['empty_char'] * (self.progress_config['bar_length'] - filled))
            percentage = int(100 * current_step / total_steps)
        
            emojis = self.progress_config['emojis']
            emoji = self.progress_config['emojis'][current_step % len(self.progress_config['emojis'])]
        
            await client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f"보고서 생성 중입니다... {emoji}\n"
                     f"진행 단계: {step_name}\n"
                     f"진행률: {bar} {percentage}%",
                # thread_ts=message_ts
            )
        except Exception as e:
            self.logger.error(f"Progress update failed: {str(e)}")
            pass

    # 프로세스 출력 처리
    async def _handle_process_output(self, stdout: str, stderr: str, channel_id: str, message_ts: str) -> Dict:
        try:
            # 마크다운 결과와 분석 결과 분리
            parts = stdout.split('\n\nAnalysis:', 1)
            report = parts[0].strip()
            analysis = parts[1].strip() if len(parts) > 1 else None

            return {
                'success': True,
                'report': report,
                'analysis': analysis
            }
        except Exception as e:
            self.logger.error(f"Failed to process output: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _handle_slack_messages(
        self, 
        result: Dict, 
        channel_id: str, 
        initial_message_ts: str,
        user_id: str,
        thread_ts: str = None
    ):
        try:
            if result['success']:
                # 시스템 지표 메시지 업데이트
                await self.app.client.chat_update(
                    channel=channel_id,
                    ts=initial_message_ts,
                    text=result['report']
                )

                # 분석 결과가 있으면 스레드로 추가
                if result.get('analysis'):
                    await self.app.client.chat_postMessage(
                        channel=channel_id,
                        thread_ts=initial_message_ts,
                        text=f"*시스템 분석:*\n{result['analysis']}"
                    )
            else:
                error_msg = result.get('error', 'Unknown error')
                await self.app.client.chat_update(
                    channel=channel_id,
                    ts=initial_message_ts,
                    text=f"보고서 생성 실패. {self.progress_config['error_message']}"
                )
                await self.app.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=initial_message_ts,
                    text=f"<@{user_id}> {self.progress_config['error_message']}: {error_msg}"
                )
        except Exception as e:
            self.logger.error(f"Failed to send Slack messages: {str(e)}")

    # 보고서 생성 로직
    async def process_report(self, ip, command, channel_id, user_id, thread_ts=None, time='today'):
        self.logger.info(f"요청 <@{user_id}> 대상 서버IP {ip}")
        initial_message = await self.app.client.chat_postMessage(
            channel=channel_id,
            text=f"{self.progress_config['start_message']}\n"
                 f"진행 단계: {self.progress_config['steps'][0]}\n"
                 f"진행률: {self.progress_config['bar_char']} 0%"
        )

        progress_task = None
        process = None

        try:
            self.logger.info(f"Executing command: {' '.join(command)}")
        
            progress_task = asyncio.create_task(
                self.progress_updates(
                    self.app.client, 
                    channel_id, 
                    initial_message['ts'], 
                    self.progress_config['steps'],
                    len(self.progress_config['steps'])
            ))
    
            process = await asyncio.subprocess.create_subprocess_exec( 
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
                env={**os.environ, 'PYTHONPATH': self.project_root}
            )

            # 결과 대기
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config['QUEUE'].getint('timeout', fallback=300)
            )

            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, command)

            # 결과 처리
            result = await self._handle_process_output(
                stdout.decode(),
                stderr.decode(),
                channel_id,
                initial_message['ts']
            )

            # Slack 메시지 처리
            await self._handle_slack_messages(
                result,
                channel_id,
                initial_message['ts'],
                user_id,
                thread_ts
            )

        except asyncio.TimeoutError:
            await self._handle_timeout_error(channel_id, initial_message['ts'], user_id)
    
        except Exception as e:
            await self._handle_process_error(channel_id, initial_message['ts'], user_id, str(e))
    
        finally:
            if progress_task and not progress_task.done():
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
        
            output_file = next((line.split(": ")[1].strip() for line in stdout.split('\n') if line.startswith("Report generated successfully:")), None)
        
            if output_file and os.path.exists(output_file):
                time_display = "오늘 0시부터 현재까지" if time == 'today' else time
                # 최종 결과와 파일을 스레드로 표시
                await self.app.client.files_upload_v2(
                    channel=channel_id,
                    file=output_file,
                    initial_comment=f"<@{user_id}> {ip}에 대한 {time_display} 기간의 보고서입니다.",
                    thread_ts=initial_message['ts']  # 초기 메시지에 스레드로 연결
                )
                await self.app.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=initial_message['ts'],  # 초기 메시지에 스레드로 연결
                    text=f"<@{user_id}> 보고서가 성공적으로 생성되었습니다. ✨"
                )
                # 메인 메시지 업데이트
                await self.app.client.chat_update(
                    channel=channel_id,
                    ts=initial_message['ts'],
                    text=self.progress_config['complete_message']
                )
            else:
                # 실패 메시지를 스레드로 표시
                await self.app.client.chat_postMessage(
                    channel=channel_id,
                    thread_ts=initial_message['ts'],  # 초기 메시지에 스레드로 연결
                    text=f"<@{user_id}> 보고서 파일을 생성하지 못했습니다."
                )
                # 메인 메시지 업데이트
                await self.app.client.chat_update(
                    channel=channel_id,
                    ts=initial_message['ts'],
                    text=f"보고서 생성 실패. {self.progress_config['error_message']}"
                )
        # except subprocess.TimeoutExpired:
        #     # 타임아웃 메시지를 스레드로 표시
        #     await self.app.client.chat_postMessage(
        #         channel=channel_id, 
        #         thread_ts=initial_message['ts'],  # 초기 메시지에 스레드로 연결
        #         text=f"<@{user_id}> {self.progress_config['timeout_message']}"
        #     )
        #     # 메인 메시지 업데이트
        #     await self.app.client.chat_update(
        #         channel=channel_id,
        #         ts=initial_message['ts'],
        #         text=f"보고서 생성 실패. {self.progress_config['timeout_message']}"
        #     )
        # except Exception as e:
        #     if progress_task and not progress_task.done():
        #         progress_task.cancel()
        #         try:
        #             await progress_task
        #         except asyncio.CancelledError:
        #             pass

            error_msg = str(e)
            self.logger.error(f"Error in process_report: {error_msg}")
            await self.app.client.chat_postMessage(
                channel=channel_id,
                thread_ts=initial_message['ts'],
                text=f"<@{user_id}> {self.progress_config['error_message']}: {error_msg}"
            )
            await self.app.client.chat_update(
                channel=channel_id,
                ts=initial_message['ts'],
                text=f"보고서 생성 실패. {self.progress_config['error_message']}"
            )
    
    # 주기적으로 진행 상태 업데이트
    async def progress_updates(self, client, channel_id, message_ts, steps, total_steps):
        try:
            delay_per_step = int(self.progress_config['update_interval'])
            for i, step in enumerate(steps, 1):
                await self.update_progress_message(
                    client, channel_id, message_ts, i, len(steps), step
                )
                await asyncio.sleep(delay_per_step)

                if i == len(steps) - 1:
                    await asyncio.sleep(delay_per_step * 2)
        except asyncio.CancelledError:
            # 보고서 생성이 완료되면 마지막 상태 업데이트
            await client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=self.progress_config['complete_message']
            )
            raise

    # @app.command("/server_report")
    async def handle_report_command(self, ack, say, command):
        await ack()
        user_group = self.check_permission(command['user_id'], command.get('user_email'), 'server_report')
        if not user_group:
            await say("명령어 실행 권한이 없습니다.")
            return
    
        args = command['text'].split()
        if not args:
            await say("잘못된 형식입니다. 사용법: /server_report <IP> [excel|24h|7d]")
            return
    
        ip = args[0]
        option = args[1] if len(args) > 1 else 'simple'  # 슬랙봇에서의 기본값: simple (마크다운)
    
        self.logger.info(f"요청 접수 <@{command['user_id']}> 대상 서버IP {ip} 옵션 {option}")

        use_thread = False
        template = 'simple'
        time_range = 'today'

        if option == 'excel':
            template = 'default'  # Excel 보고서
            use_thread = True     # 스레드 사용
        elif option in ['24h', '7d']:
            time_range = option
    
        initial_message = await say(f"<@{command['user_id']}> 보고서 생성 요청을 받았습니다. 처리 중입니다...")
        thread_ts = initial_message['ts'] if use_thread else None

        # 실행 명령 구성
        python_interpreter = os.path.join(self.project_root, self.config['FILES']['venv_path'].replace('./', ''), 'bin', 'python')
        report_script = os.path.join(self.project_root, 'report', 'promblueReport.py')
        report_config = os.path.join(self.project_root, 'report', 'promblueReport.yml')  # .yml 사용
        out_dir = os.path.join(self.project_root, self.config['FILES']['out_file_dir'].replace('./', ''))

        os.makedirs(out_dir, exist_ok=True)
        request_id = f"{command['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        cmd_args = [
            python_interpreter,
            report_script,
            '--target', ip,
            '--output', out_dir,
            '--request-id', request_id,
            '--config', report_config,
            '--template', template,
            '--time', time_range
        ]

        asyncio.create_task(self.process_report(
            ip=ip, 
            command=cmd_args,
            channel_id=command['channel_id'],
            user_id=command['user_id'],
            thread_ts=thread_ts,
            time=time_range
        ))
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

    async def handle_server_button_command(self, ack, say, command, client):
        await ack()
        user_group = self.check_permission(command['user_id'], command.get('user_email'), 'server_button')
        if not user_group:
            await say("명령어 실행 권한이 없습니다.")
            return

        channel_id = command['channel_id']
        message_limit = int(self.config.get('BUTTON_GENERATION', 'message_limit', fallback=10))
        extract_ips_limit = int(self.config.get('BUTTON_GENERATION', 'extract_ips_limit', fallback=5))

        try:
            result = await client.conversations_history(channel=channel_id, limit=message_limit)
            messages = result['messages']

            extracted_info = set()
            for message in messages:
                # text = message.get('text', '')
                text = self.extract_text_from_message(message) 
                ip_matches = self.ip_pattern.findall(text)
                host_matches = self.hostname_pattern.findall(text)

                extracted_info.update(ip_matches)
                extracted_info.update(host_matches)

            if not extracted_info:
                await say(f"상위 {message_limit}개의 메시지에서 추출 가능한 IP 또는 Hostname이 없습니다.")
                return

            df = self.read_extdata_file(self.CSV_FILE)
            buttons, unmapped_hostnames, unmapped_ips = self.create_buttons_and_find_unmapped(extracted_info, df)

            if not buttons:
                await say("추출된 정보에서 유효한 IP를 찾을 수 없습니다.")
                return

            text_content = f"상위 {message_limit}개의 메시지에서 추출한 IP:"
            blocks = [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f":robot_face: :speech_balloon: 상위 *{message_limit}* 개의 메세지에서 *추출한 IP:* (limit: *{extract_ips_limit}* buttons) :mag_right:"}
                },
                {
                    "type": "actions",
                    "elements": buttons[:extract_ips_limit]
                }
            ]

            if unmapped_hostnames or unmapped_ips:
                unmapped_text = f"※ _참조파일: `{self.CSV_FILE_NAME}`_\n"
                if unmapped_hostnames:
                    unmapped_text += "*매핑되지 않은 Hostname:*\n" + "\n".join(f"• {hostname}" for hostname in unmapped_hostnames)
                if unmapped_ips:
                    if unmapped_text:
                        unmapped_text += "\n\n"
                    unmapped_text += f"*구성관리조회 CSV에 없는 IP:*\n" + "\n".join(f"• {ip}" for ip in unmapped_ips)
                
                blocks.append({
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": unmapped_text}
                    ]
                })

                text_content += f"\n\n{unmapped_text}"

            await say(text=text_content, blocks=blocks)

        except Exception as e:
            self.logger.error(f"Error in handle_server_button_command: {str(e)}", exc_info=True)
            await say(f"명령어 처리 중 오류가 발생했습니다: {str(e)}")

    def extract_text_from_message(self, message):
        text = message.get('text', '')
        if 'blocks' in message:
            for block in message['blocks']:
                if block['type'] == 'section' and 'text' in block:
                    text += ' ' + block['text'].get('text', '')
        return text

    def create_buttons_and_find_unmapped(self, extracted_info, df):
        buttons = []
        unmapped_hostnames = set()
        unmapped_ips = set()
        for index, info in enumerate(extracted_info):
            ip = self.get_ip_from_info(info, df)
            if ip:
                action_id = f"server_info_button_{index}"
                buttons.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": ip},
                    "value": ip,
                    "action_id": action_id
                })
                self.logger.debug(f"Created button with action_id: {action_id}")
            elif self.ip_pattern.match(info):
                unmapped_ips.add(info)
            else:
                unmapped_hostnames.add(info)
        return buttons, unmapped_hostnames, unmapped_ips

    def get_ip_from_info(self, info, df):
        if self.ip_pattern.match(info):
            if info in df['사설IP'].values or info in df['공인/NAT IP'].values:
                return info
            return None
        else:
            matching_row = df[df['Hostname'] == info]
            if not matching_row.empty:
                return matching_row['사설IP'].iloc[0] or matching_row['공인/NAT IP'].iloc[0]
        return None

    async def handle_server_info_button(self, ack, body, say):
        await ack()
        action_id = body['actions'][0]['action_id']
        # self.logger.info(f"Handling server info button action: {body['actions'][0]['action_id']}")
        self.logger.info(f"Handling server info button action: {action_id}")
        ip = body['actions'][0]['value']
        user_id = body['user']['id']
        user_email = body['user'].get('email')

        user_group = self.check_permission(user_id, user_email, 'server_info')
        if not user_group:
            await say("서버 정보 조회 권한이 없습니다.")
            return

        try:
            df = self.read_extdata_file(self.CSV_FILE)
            df = self.filter_data(df, user_group)
            
            server_info = df[(df['사설IP'] == ip) | (df['공인/NAT IP'] == ip)]
            
            if server_info.empty:
                await say(f"{ip}에 해당하는 서버 정보를 찾을 수 없습니다.")
                return
            
            template = self.config['TEMPLATES']['voca_template'].replace('##', '\n')
            formatted_info = self.format_server_info(server_info.iloc[0], template)
            
            await say(formatted_info)
        except Exception as e:
            self.logger.error(f"Error in handle_server_info_button: {str(e)}")
            await say(f"서버 정보 조회 중 오류가 발생했습니다: {str(e)}")

    def format_server_info(self, server_info, template):
        formatted_info = template
        for column, value in server_info.items():
            placeholder = f"{{{column}}}"
            if placeholder in formatted_info:
                value = '-' if pd.isna(value) or value == '' else str(value)
                formatted_info = formatted_info.replace(placeholder, value)
        return formatted_info

def init(app: AsyncApp, config, queue, check_permission, get_user_info, filter_data, ip_pattern, hostname_pattern):
    return ServerManager(app, config, queue, check_permission, get_user_info, filter_data, ip_pattern, hostname_pattern)