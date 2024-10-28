import os
import configparser
import asyncio
import aiohttp
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Any
import logging
from dataclasses import dataclass
import pandas as pd
import numpy as np

__version__ = '0.4.1 (2024.10.28)'

class PromBlueReport:
    def __init__(self, config_path: str = 'promblueReport.conf'):
        self.config = self._load_config(config_path)
        self.logger = self._setup_logging()
        self._setup_common_variables()

    def _load_config(self, config_path: str) -> configparser.ConfigParser:
        config = configparser.ConfigParser()
        config.read(config_path)
        return config

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        return logger

    def _setup_common_variables(self):
        # 공통으로 사용할 변수들 초기화
        self.prometheus_url = self.config['prometheus']['url']
        self.report_template = self.config['report_layout']['template']
        self.visualization_style = self.config['visualization']['style']
        
    # 프로메테우스 쿼리 실행
    async def query_prometheus(self, query: str, start_time: datetime, end_time: datetime, ip: str) -> Dict:
        try:
            params = {
                'query': query,
                'start': str(int(start_time.timestamp())),
                'end': str(int(end_time.timestamp())),
                'step': self.config['prometheus']['step_interval']
            }

            self.logger.debug(f"Querying Prometheus - URL: {self.prometheus_url}")
            self.logger.debug(f"Query: {query}")
            self.logger.debug(f"Parameters: {params}")
        
            timeout_value = float(self.config['prometheus'].get('query_timeout', '30'))
            timeout = aiohttp.ClientTimeout(total=timeout_value)
        
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.prometheus_url}/api/v1/query_range"
            
                try:
                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            self.logger.error(f"프로메테우스 쿼리 실패 - Status: {response.status}, Error: {error_text}")
                            self.logger.error(f"Error response: {error_text}")
                            return []

                        data = await response.json()
                    
                        if data['status'] != 'success':
                            self.logger.error(f"프로메테우스 응답 오류 - Error: {data.get('error', 'Unknown error')}")
                            return []

                        self.logger.debug(f"Query successful, received {len(data['data']['result'])} results")
                        return data['data']['result']

                except aiohttp.ClientError as e:
                    self.logger.error(f"프로메테우스 연결 실패: {str(e)}")
                    return []
                except Exception as e:
                    self.logger.error(f"프로메테우스 쿼리 중 예외 발생: {str(e)}")
                    return []

        except Exception as e:
            self.logger.error(f"프로메테우스 쿼리 처리 중 예외 발생: {str(e)}")
            return []

    # 메트릭 시각화 공통 로직
    def create_visualizer(self, metric_value: float, style: str = None) -> str:
        style = style or self.visualization_style
        width = 10  # 기본 너비

        # 미니 그래프 (Unicode 블록)
        if style == 'mini-graph':
            chars = self.config['visualization']['graph_chars'].split()
            normalized = min(max(metric_value / 100, 0), 1)
            index = int(normalized * (len(chars) - 1))
            return chars[index] * width
        
        # 바 그래프 (파이프 문자)
        elif style == 'pipe':
            pipe_char = self.config['visualization'].get('pipe_char', '|')
            filled = int((metric_value / 100) * width)
            return pipe_char * filled + ' ' * (width - filled)
        
        # 조건부 서식 색상 블록
        elif style == 'color-block':
            if metric_value >= float(self.config['visualization']['threshold_critical']):
                return '■' * 3    # 위험
            elif metric_value >= float(self.config['visualization']['threshold_warning']):
                return '■' * 2    # 경고
            return '■'            # 정상
        
        else:
            # 기본값: 숫자만 반환
            return f"{metric_value:.1f}%"

    # 출력 파일 생성
    def _generate_output_filename(self, target: str, output_dir: str = None, request_id: str = None) -> str:
        timestamp = datetime.now().strftime('%Y%m%d%H%M')
        prefix = self.config['files']['output_prefix']
        
        # output_dir이 지정되지 않은 경우 기본 디렉토리 사용
        if not output_dir:
            output_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                self.config['files']['output_dir'].lstrip('../')
            )
        
        os.makedirs(output_dir, exist_ok=True)

        # request_id가 있으면 파일명에 포함 (slackbot에서 생성)
        if request_id:
            filename = f"{prefix}_{target}_{timestamp}_{request_id}.xlsx"
        else:
            filename = f"{prefix}_{target}_{timestamp}.xlsx"
            
        return os.path.join(output_dir, filename)

    # 템플릿 선택 및 보고서 생성 공통
    async def generate_report(self, target: str, time_range: str = 'today', template: str = None, output_dir: str = None, request_id: str = None) -> str:
        template = template or self.report_template
        
        if template == 'default':
            from template_default import DefaultTemplate
            template_class = DefaultTemplate(self)
        elif template == 'compact':
            from template_compact import CompactTemplate
            template_class = CompactTemplate(self)
        elif template == 'detailed':
            from template_detailed import DetailedTemplate
            template_class = DetailedTemplate(self)
        else:
            raise ValueError(f"Unknown template: {template}")

        return await template_class.create_report(target, time_range, output_dir, request_id)

    @staticmethod
    def get_version():
        return __version__

def main():
    parser = argparse.ArgumentParser(description='Generate server inspection report')
    parser.add_argument('--target', required=True, help='IP address or service name (prefix with "service:")')
    parser.add_argument('--time', default='today', help='Time parameter (e.g., 24h, 7d, today)')
    parser.add_argument('--template', default='default', help='Report template (default, compact, detailed)')
    parser.add_argument('--config', default='promblueReport.conf', help='Path to config file')
    parser.add_argument('--output', help='Output directory for the report')
    parser.add_argument('--request-id', help='Request ID for the report')
    
    args = parser.parse_args()

    async def async_main():
        try:
            report_generator = PromBlueReport(args.config)
            output_file = await report_generator.generate_report(
                args.target,
                args.time,
                args.template,
                args.output,
                args.request_id
            )
            print(f"Report generated successfully: {output_file}")
            return output_file
        except Exception as e:
            print(f"Error generating report: {str(e)}")
            raise

    return asyncio.run(async_main())

if __name__ == "__main__":
    main()