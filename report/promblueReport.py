import os
import yaml
import asyncio
import aiohttp
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
import logging
from logging.handlers import RotatingFileHandler
import pandas as pd
import numpy as np
import redis
from rq import Queue
from pathlib import Path

__version__ = '0.5.2 (2024.10.29)'

# yaml 처리 클래스
class YAMLConfig:
    def __init__(self, yaml_path: str):
        self.project_root = Path(__file__).parent.parent
        if not os.path.isabs(yaml_path):
            yaml_path = str(Path(__file__).parent / yaml_path)
            
        if not os.path.exists(yaml_path):
            raise FileNotFoundError(f"Config file not found: {yaml_path}")

        with open(yaml_path, 'r', encoding='utf-8') as f:
            try:
                self.config_data = yaml.safe_load(f)
                if self.config_data is None:
                    self.config_data = {}  # 빈 파일이면 빈 딕셔너리로 초기화
                self._resolve_references(self.config_data)
            except yaml.YAMLError as e:
                raise ValueError(f"Failed to parse YAML: {str(e)}")

    # YAML 내의 변수 참조 해결 (${변수} 형식)
    def _resolve_references(self, data):
        if isinstance(data, dict):
            for key, value in list(data.items()):
                if isinstance(value, str) and value.startswith('${'):
                    ref_path = value[2:-1].split('.')
                    data[key] = self._get_value_by_path(ref_path)
                else:
                    self._resolve_references(value)
        elif isinstance(data, list):
            for item in data:
                self._resolve_references(item)

    # 설정값 경로로 값 조회
    def _get_value_by_path(self, path: List[str]) -> Any:
        value = self.config_data
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
            if value is None:
                return None
        return value

    # 단일 키 값 조회
    def get(self, key: str, default: Any = None) -> Any:
        if not isinstance(self.config_data, dict):
            return default
        return self.config_data.get(key, default)
    
    # 중첩 키값 조회
    def get_nested(self, *keys: str, default: Any = None) -> Any:
        value = self.config_data
        for key in keys:
            if not isinstance(value, dict):
                return default
            value = value.get(key)
            if value is None:
                return default
        return value

    # 전체 조회 (항상 딕셔너리 반환)
    def get_config(self, section: str) -> Dict:
        if not isinstance(self.config_data, dict):
            return {}
        config = self.config_data.get(section)
        return config if isinstance(config, dict) else {}

class PromBlueReport:
    def __init__(self, config_path: str = 'promblueReport.yml'):
        self.project_root = Path(__file__).parent.parent
        self.config = YAMLConfig(config_path)
        self._setup_paths()
        self.logger = self._setup_logging()
        self.queue = self._setup_queue()
    
    # 경로 설정
    def _setup_paths(self):
        files_config = self.config.get_config('files')  # 항상 딕셔너리 반환
    
        self.data_dir = self.project_root / files_config.get('data_dir', 'data').lstrip('./')
        self.output_dir = self.project_root / files_config.get('output_dir', 'output').lstrip('./')
    
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
        self.logger_debug(f"Project root: {self.project_root}")
        self.logger_debug(f"Data directory: {self.data_dir}")
        self.logger_debug(f"Output directory: {self.output_dir}")

    # 로깅 설정
    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger(__name__)
    
        try:
            log_config = self.config.get_config('logging')
        
            # 로그 레벨 설정
            level_str = log_config.get('log_level', 'INFO').upper()
            log_level = getattr(logging, level_str, logging.INFO)
            logger.setLevel(log_level)

            # 로그 파일 설정
            log_file = log_config.get('log_file')
            if log_file:
                if not os.path.isabs(log_file):
                    log_file = str(self.project_root / log_file.lstrip('./'))

                log_dir = os.path.dirname(log_file)
                os.makedirs(log_dir, exist_ok=True)

                handler = RotatingFileHandler(
                    log_file,
                    maxBytes=log_config.get('log_max_bytes', 1048576),
                    backupCount=log_config.get('log_backup_count', 5)
                )
            
                formatter = logging.Formatter(
                    '%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                handler.setFormatter(formatter)
                logger.addHandler(handler)

            # 콘솔 핸들러 추가
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
            logger.addHandler(console_handler)

            return logger

        except Exception as e:
            # 기본 로깅으로 폴백
            basic_handler = logging.StreamHandler()
            basic_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
            logger.addHandler(basic_handler)
            logger.setLevel(logging.INFO)
            logger.warning(f"Using basic logging configuration: {str(e)}")
            return logger

    def logger_debug(self, message: str):
        if hasattr(self, 'logger'):
            self.logger.debug(message)

    # Redis 큐 설정
    def _setup_queue(self) -> Optional[Queue]:
        queue_config = self.config.get_config('queue')
        if not queue_config.get('use_queue', False):
            return None

        try:
            redis_config = queue_config.get('redis', {})
            redis_conn = redis.Redis(
                host=redis_config.get('host', 'localhost'),
                port=redis_config.get('port', 6379),
                db=redis_config.get('db', 0)
            )
            return Queue(connection=redis_conn)
        except Exception as e:
            self.logger.error(f"Redis queue setup failed: {str(e)}")
            return None

    # Prometheus 쿼리 실행
    async def query_prometheus(self, query: str, start_time: datetime, end_time: datetime) -> List[Dict]:
        prom_config = self.config.get('prometheus', {})
        
        try:
            params = {
                'query': query,
                'start': str(int(start_time.timestamp())),
                'end': str(int(end_time.timestamp())),
                'step': prom_config.get('step_interval', '1h')
            }

            self.logger.debug(f"Querying Prometheus - Query: {query}")
            self.logger.debug(f"Parameters: {params}")
            
            timeout = aiohttp.ClientTimeout(total=float(prom_config.get('query_timeout', 30)))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{prom_config['url']}/api/v1/query_range"
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self.logger.error(f"Query failed: {error_text}")
                        return []
                    
                    data = await response.json()
                    if data['status'] != 'success':
                        self.logger.error(f"Query error: {data.get('error', 'Unknown error')}")
                        return []
                    
                    return data['data']['result']

        except Exception as e:
            self.logger.error(f"Prometheus query failed: {str(e)}")
            return []

    # 보고서 생성
    async def generate_report(
        self,
        target: str,
        time_range: str = 'today',
        template: str = 'default',
        output_dir: str = None,
        request_id: str = None,
        is_slack: bool = False
    ) -> Union[str, Dict[str, str]]:
        try:
            # Default to simple template for Slack
            if is_slack and template == 'default':
                template = 'simple'
            
            template_class = self._get_template_class(template)
            template_instance = template_class(self)
            
            self.logger.info(f"Generating {template} report for {target}")
            result = await template_instance.create_report(
                target=target,
                time_range=time_range,
                output_dir=output_dir,
                request_id=request_id
            )
            
            self.logger.info(f"Report generation completed")
            return result
            
        except Exception as e:
            self.logger.error(f"Report generation failed: {str(e)}", exc_info=True)
            raise

    # 템플릿 선택
    def _get_template_class(self, template: str):
        """Get appropriate template class"""
        if template == 'default':
            from template_default import DefaultTemplate
            return DefaultTemplate
        elif template == 'simple':
            from template_simple import SimpleTemplate
            return SimpleTemplate
        elif template == 'complete':
            from template_complete import CompleteTemplate
            return CompleteTemplate
        else:
            raise ValueError(f"Unknown template: {template}")

    @staticmethod
    def get_version() -> str:
        return __version__

def main():
    parser = argparse.ArgumentParser(description='Generate server inspection report')
    parser.add_argument('--target', required=True, help='IP address or hostname')
    parser.add_argument('--time', default='today', help='Time range (e.g., 24h, 7d, today)')
    parser.add_argument('--template', default='default', help='Report template (default, simple, complete)')
    parser.add_argument('--output', help='Output directory')
    parser.add_argument('--config', default='promblueReport.yml', help='Config file path')
    parser.add_argument('--request-id', help='Request ID for the report')
    
    args = parser.parse_args()

    async def async_main():
        try:
            report_generator = PromBlueReport(args.config)
            result = await report_generator.generate_report(
                target=args.target,
                time_range=args.time,
                template=args.template,
                output_dir=args.output,
                request_id=args.request_id
            )

            if isinstance(result, dict):  # Markdown result
                print(result['report'])
                if 'analysis' in result:
                    print("\nAnalysis:")
                    print(result['analysis'])
            else:  # Excel file path
                print(f"Report generated successfully: {result}")
            
            return result

        except Exception as e:
            print(f"Error generating report: {str(e)}")
            raise

    return asyncio.run(async_main())

if __name__ == "__main__":
    main()