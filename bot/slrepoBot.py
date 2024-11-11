import os
import configparser
import logging
from logging.handlers import RotatingFileHandler
import asyncio
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
import redis
from rq import Queue
import socket
import requests
import websockets
from urllib.parse import urlparse
import ssl

# 슬래시 명령어 모듈
import cmd_check_web   # /check_web_b2b, /check_web_b2c, /check_web_b2e, /check_web_blue
import cmd_server      # /server_info, /server_mngt, /server_report
import cmd_fun         # 
# import cmd_check_api   # TODO /check_api ...
# import cmd_check_db    # TODO /check_db ...
# import cmd_aws         # TODO PaaS & SaaS on AWS ...
# import cmd_azure       # TODO PaaS & SaaS on Azure ...

__version__ = '0.6.37 (2024.11.11)'

class NetworkChecker:
    def __init__(self, logger):
        self.logger = logger
        self.slack_endpoints = [
            'api.slack.com',
            'wss-primary.slack.com',
            'wss-backup.slack.com',
            'slack.com'
        ]
    
    # Slack 엔드포인트 연결 체크
    async def check_connections(self):
        results = {}
        for endpoint in self.lack_endpoints:
            results[endpoint] = await self._check_endpoint(endpoint)
        return results
    
    # 개별 엔드포인트 연결 체크
    async def _check_endpoint(self, endpoint):
        try:
            # DNS 확인
            try:
                ip = socket.gethostbyname(endpoint)
                self.logger.info(f"DNS Resolution - {endpoint} -> {ip}")
            except socket.gaierror as e:
                self.logger.error(f"DNS Resolution failed for {endpoint}: {str(e)}")
                return False
            
            # HTTPS 연결 테스트
            if not endpoint.startswith('wss'):
                try:
                    response = requests.get(f'https://{endpoint}', timeout=5)
                    self.logger.info(f"HTTPS Connection to {endpoint} successful: {response.status_code}")
                except requests.exceptions.RequestException as e:
                    self.logger.error(f"HTTPS Connection failed to {endpoint}: {str(e)}")
                    return False

            # WebSocket 연결 테스트 (wss 로 시작)
            if endpoint.startswith('wss'):
                try:
                    uri = f"wss://{endpoint}"
                    async with websockets.connect(uri, ssl=True) as websocket:
                        self.logger.info(f"WebSocket Connection to {endpoint} successful")
                except Exception as e:
                    self.logger.error(f"WebSocket Connection failed to {endpoint}: {str(e)}")
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Connection check failed for {endpoint}: {str(e)}")
            return False

class SlackConnectionMonitor:
    def __init__(self, app: AsyncApp):
        self.app = app
        self.logger = app.client.logger
        self.network_checker = NetworkChecker(self.logger)
        
        self.setup_connection_monitoring()

    # 연결 상태 모니터링 설정
    def setup_connection_monitoring(self):
        self.app.client.web_client.session.hooks['response'] = [self.log_request_response]
        
    # HTTP 요청/응답 로깅
    def log_request_response(self, response, *args, **kwargs):
        try:
            request = response.request
            self.logger.debug(f"""
                Request:
                - URL: {request.url}
                - Method: {request.method}
                - Headers: {request.headers}
                
                Response:
                - Status: {response.status_code}
                - Headers: {response.headers}
                - Time: {response.elapsed.total_seconds():.2f}s
            """)
            
            # 응답 시간이 너무 긴 경우 경고
            if response.elapsed.total_seconds() > 5:
                self.logger.warning(f"Slow response from {request.url}: {response.elapsed.total_seconds():.2f}s")
                
            # 연결 실패나 타임아웃 감지
            if response.status_code >= 500:
                self.logger.error(f"Server error from Slack API: {response.status_code}")
            elif response.status_code == 429:
                self.logger.warning("Rate limit hit on Slack API")
                
        except Exception as e:
            self.logger.error(f"Error in request/response logging: {str(e)}")

class slrepoBot:
    def __init__(self):
        self.config = self.setup_config_and_logging()
        self.app = AsyncApp(token=self.config['SLACK']['bot_token'])
        self.queue = self.setup_queue()
        self.connection_monitor = None
        self.init_modules()
        self.register_commands()

    # 설정 파일 읽기 및 로그 설정
    def setup_config_and_logging(self):
        config = configparser.ConfigParser()
        config.read('slrepoBot.conf')

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

        return config

    # (리포트 생성용) 큐 설정 및 초기화
    def setup_queue(self):
        if self.config['QUEUE'].getboolean('use_queue', fallback=False):
            redis_conn = redis.Redis(
                host=self.config['QUEUE']['redis_host'],
                port=self.config['QUEUE'].getint('redis_port'),
                db=self.config['QUEUE'].getint('redis_db')
            )
            return Queue(connection=redis_conn)
        return None

    # 슬랙 유저 정보 얻기
    async def get_user_info(self, client, user_id):
        try:
            result = await client.users_info(user=user_id)
            return result["user"]
        except Exception as e:
            logging.error(f"Error fetching user info: {str(e)}")
            return None

    # 권한 제어 로직
    def check_permission(self, user_id, user_email, command):
        if not user_email:
            logging.warning(f"User email not available for user {user_id}")
            user_email = ""
        
        admin_domains = self.config['ACCESS_CONTROL'].get('admin_domains', '').split(', ')
        admin_slack_ids = self.config['ACCESS_CONTROL'].get('admin_slack_ids', '').split(', ')
        user_domains = self.config['ACCESS_CONTROL'].get('user_domains', '').split(', ')
        user_slack_ids = self.config['ACCESS_CONTROL'].get('user_slack_ids', '').split(', ')
        guest_domains = self.config['ACCESS_CONTROL'].get('guest_domains', '*').split(', ')
        
        allowed_groups = self.config['COMMAND_PERMISSIONS'].get(command, '').split(', ')
        
        user_domain = user_email.split('@')[1] if '@' in user_email else ''
        
        logging.debug(f"Checking permission for user_id: {user_id}, user_email: {user_email}, command: {command}")
        logging.debug(f"Admin domains: {admin_domains}, Admin Slack IDs: {admin_slack_ids}")
        logging.debug(f"User domain: {user_domain}, Allowed groups: {allowed_groups}")

        if 'admin' in allowed_groups and (user_domain in admin_domains or user_id in admin_slack_ids):
            logging.info(f"Admin permission granted to user {user_id} for command {command}")
            return 'admin'
        elif 'user' in allowed_groups and (user_domain in user_domains or user_id in user_slack_ids):
            logging.info(f"User permission granted to user {user_id} for command {command}")
            return 'user'
        elif 'guest' in allowed_groups and (guest_domains == ['*'] or user_domain in guest_domains):
            logging.info(f"Guest permission granted to user {user_id} for command {command}")
            return 'guest'
        else:
            logging.warning(f"Permission denied to user {user_id} for command {command}")
            return None

    # csv 칼럼(개인정보) 데이터 필터링
    def filter_data(self, df, user_group):
        if user_group == 'admin':
            logging.info("Admin user, no filtering applied")
            return df
        
        filtered_columns = self.config['DATA_FILTERING']['filtered_columns'].split(', ')
        logging.info(f"Filtering columns for {user_group}: {filtered_columns}")
        
        for column in filtered_columns:
            if column in df.columns:
                df[column] = '***filtered***'
                logging.info(f"Column {column} filtered")
            else:
                logging.warning(f"Column {column} not found in dataframe")
        
        return df
    
    # 각 모듈의 초기화 함수 호출
    def init_modules(self):
        cmd_check_web.init(self.app, self.config)

        try:
            self.ip_pattern = self.config['BUTTON_GENERATION']['ip_pattern']
            self.hostname_pattern = self.config['BUTTON_GENERATION']['hostname_pattern']
        except KeyError:
            logging.error("'BUTTON_GENERATION' section or 'ip_pattern''hostname_pattern' key not found in config")
            self.ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'              # Default IP pattern
            self.hostname_pattern = r'\b[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b'  # Default Hostname pattern
        cmd_fun.init(self.app, self.config)
        self.server_manager = cmd_server.init(self.app, self.config, self.queue, self.check_permission, self.get_user_info, self.filter_data, self.ip_pattern, self.hostname_pattern)
        logging.info("All modules initialized")

    def register_commands(self):
        self.app.command("/bot_ver")(self.handle_version_command)

    # @app.command("/bot_ver")
    async def handle_version_command(self, ack, say, command):
        await ack()
        if command['text']:
            await say(f"참고: '/bot_ver' 명령어는 추가 파라미터를 필요로 하지 않습니다. 입력하신 '{command['text']}'는 무시됩니다.")
        await say(f"현재 채찍PT봇 버전: v{__version__}")

    async def run(self):
        handler = AsyncSocketModeHandler(self.app, self.config['SLACK']['app_token'])
        try:
            # 연결 모니터링 초기화 및 초기 연결 체크
            self.connection_monitor = SlackConnectionMonitor(self.app)
            connection_status = await self.connection_monitor.network_checker.check_connections()
            
            # 연결 상태 로깅
            for endpoint, status in connection_status.items():
                if status:
                    logging.info(f"Successfully connected to {endpoint}")
                else:
                    logging.error(f"Failed to connect to {endpoint}")

            await handler.start_async()
            logging.info(f"채찍PT봇 v{__version__} 구동중!")
            while True:
                await asyncio.sleep(3600)
        finally:
            await handler.close()
            if self.app.client.session:
                await self.app.client.session.close()

# 메인 애플리케이션 로직
async def main():
    bot = slrepoBot()
    await bot.run()

if __name__ == "__main__":
    print(f"Starting 채찍PT봇 v{__version__}")
    asyncio.run(main())