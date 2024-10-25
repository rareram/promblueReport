from abc import ABC
from datetime import datetime, timedelta
from typing import Dict, List, Any
import pandas as pd
from xlsxwriter import Workbook
import numpy as np
import os
import glob
import requests
import logging

class DefaultTemplate:
    def __init__(self, report_instance):
        self.report = report_instance
        self.config = report_instance.config
        self.logger = report_instance.logger

    # 보고서 생성 - default
    async def create_report(self, target: str, time_range: str) -> str:
        try:
            # 시간 범위 계산
            end_time = datetime.now()
            if time_range.endswith('h'):
                start_time = end_time - timedelta(hours=int(time_range[:-1]))
            elif time_range.endswith('d'):
                start_time = end_time - timedelta(days=int(time_range[:-1]))
            else:  # today
                start_time = end_time.replace(hour=0, minute=0, second=0, microsecond=0)

            # 출력 파일명 생성
            output_file = self._generate_output_filename(target)
            workbook = Workbook(output_file)
            
            # 워크시트 생성 및 기본 설정
            worksheet = workbook.add_worksheet()
            self._setup_worksheet(worksheet)
            formats = self._create_formats(workbook)

            # 서버 정보 조회
            server_info = self._get_server_info(target)
            
            # 각 섹션 작성
            current_row = 0
            current_row = self._write_header_section(worksheet, formats, server_info, current_row)
            current_row = self._write_system_info_section(worksheet, formats, server_info, current_row)
            current_row = await self._write_metrics_section(worksheet, formats, target, start_time, end_time, current_row)
            current_row = self._write_analysis_section(worksheet, formats, server_info, current_row)

            workbook.close()
            return output_file

        except Exception as e:
            self.logger.error(f"Report generation failed: {str(e)}", exc_info=True)
            raise

    # 워크시트 기본 설정
    def _setup_worksheet(self, worksheet):
        worksheet.set_paper(9)        # A4
        worksheet.set_landscape()
        worksheet.set_margins(left=0.25, right=0.25, top=0.25, bottom=0.25)
        
        column_widths = [15, 20, 25, 15, 15, 15, 15, 15]
        for i, width in enumerate(column_widths):
            worksheet.set_column(i, i, width)

    # 워크시트 서식 생성
    def _create_formats(self, workbook):
        formats = {}
        
        # 제목 서식
        formats['title'] = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': 'F5F5F5',
            'text_wrap': True
        })

        # 헤더 서식
        formats['header'] = workbook.add_format({
            'bold': True,
            'font_size': 9,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': 'E0E0E0',
            'border': 1
        })

        # 일반 텍스트 서식
        formats['text'] = workbook.add_format({
            'font_size': 8,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True
        })

        # 메트릭 서식
        formats['metric'] = workbook.add_format({
            'font_size': 8,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '0.00'
        })

        # 경고 서식
        formats['warning'] = workbook.add_format({
            'font_size': 8,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': 'FFEB3B',
            'border': 1
        })

        # 위험 서식
        formats['critical'] = workbook.add_format({
            'font_size': 8,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': 'FF5252',
            'border': 1
        })

        return formats

    def _write_header_section(self, worksheet, formats, server_info, row):
        """헤더 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, 
                            f'서버 점검 보고서 - {server_info["IT구성정보명"]}', 
                            formats['title'])
        return row + 2

    def _write_system_info_section(self, worksheet, formats, server_info, row):
        """시스템 정보 섹션 작성"""
        # 좌측 기본 정보
        headers = ['항목', '내용']
        worksheet.write_row(row, 0, headers, formats['header'])
        
        basic_info = [
            ['ID', server_info['ID']],
            ['서비스', f"{server_info['서비스']} ({server_info['운영상태']})"],
            ['용도', server_info['IT구성정보명']],
            ['IP 주소', f"사설IP: {server_info['사설IP']}\n공인IP: {server_info['공인/NAT IP']}"],
            ['OS', f"{server_info['서버 OS']} {server_info['서버 OS Version']}"],
            ['CPU', f"{server_info['CPU Type']} ({server_info['CPU Core 수']})"],
            ['메모리', server_info['Memory']],
            ['디스크', server_info['디스크 용량']]
        ]
        
        for i, (item, value) in enumerate(basic_info):
            worksheet.write(row + 1 + i, 0, item, formats['text'])
            worksheet.write(row + 1 + i, 1, value, formats['text'])
        
        return row + len(basic_info) + 2

    # 메트릭 섹션
    async def _write_metrics_section(self, worksheet, formats, target, start_time, end_time, row):
        # 메트릭 헤더
        headers = ['지표', '현재', '평균', '최대', '시각화']
        worksheet.write_row(row, 0, headers, formats['header'])
        
        # 메트릭 데이터 수집 및 작성
        metrics = await self._get_metrics(target, start_time, end_time)
        metrics_rows = []
        
        for metric_name, data in metrics.items():
            visual = self.report.create_visualizer(data['current'])
            row_data = [
                metric_name,
                data['current'],
                data['average'],
                data['maximum'],
                visual
            ]
            metrics_rows.append(row_data)
        
        for i, row_data in enumerate(metrics_rows):
            format_to_use = self._get_metric_format(formats, row_data[1])
            worksheet.write(row + 1 + i, 0, row_data[0], formats['text'])
            worksheet.write(row + 1 + i, 1, row_data[1], format_to_use)
            worksheet.write(row + 1 + i, 2, row_data[2], formats['metric'])
            worksheet.write(row + 1 + i, 3, row_data[3], formats['metric'])
            worksheet.write(row + 1 + i, 4, row_data[4], formats['text'])
        
        return row + len(metrics_rows) + 2

    # 메트릭 값에 따른 서식 반환
    def _get_metric_format(self, formats, value):
        if value >= float(self.config['visualization']['threshold_critical']):
            return formats['critical']
        elif value >= float(self.config['visualization']['threshold_warning']):
            return formats['warning']
        return formats['metric']

    # 분석 결과 섹션 작성
    async def _write_analysis_section(self, worksheet, formats, server_info, row):
        worksheet.merge_range(row, 0, row, 7, '시스템 분석', formats['header'])
        
        analysis = self._get_llm_analysis(server_info)
        
        worksheet.merge_range(row + 1, 0, row + 5, 7, analysis, formats['text'])
        return row + 7

    def _generate_output_filename(self, target):
        """출력 파일명 생성"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M')
        prefix = self.config['files']['output_prefix']
        return f"{prefix}_{target}_{timestamp}.xlsx"

    # 서버 정보 조회
    def _get_server_info(self, target: str)  -> Dict:
        try:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'data',
            )

            prefix = self.config['files']['extdata_prefix']
            pattern = os.path.join(data_dir, f"{prefix}*.csv")
            matching_files = glob.glob(pattern)

            if not matching_files:
                raise FileNotFoundError(f"'{prefix}'로 시작하는 CSV 파일을 찾을 수 없습니다.")
        
            # 가장 최근 파일 선택 (파일명의 숫자가 가장 큰 파일)
            latest_file = max(matching_files, key=lambda f: 
                int(''.join(filter(str.isdigit, os.path.basename(f))) or '0')
            )
        
            self.logger.info(f"Using CSV file: {latest_file}")

            df = pd.read_csv(latest_file, encoding='euc-kr')
        
            # target이 IP인 경우
            server_info = df[(df['사설IP'] == target) | (df['공인/NAT IP'] == target)]
        
            # target이 서비스명인 경우
            if server_info.empty:
                if target.startswith('service:'):
                    service_name = target.split(':', 1)[1]
                    server_info = df[df['서비스'] == service_name]
        
            if server_info.empty:
                raise ValueError(f"서버 정보를 찾을 수 없습니다: {target}")
        
            # 첫 번째 행을 딕셔너리로 변환하여 반환
            return server_info.iloc[0].to_dict()
    
        except Exception as e:
            self.logger.error(f"서버 정보 조회 실패: {str(e)}")
            raise

    # 메트릭 데이터 조회
    async def _get_metrics(self, target: str, start_time: datetime, end_time: datetime) -> Dict:
        try:
            metrics = {}
            queries = self.config['prometheus_queries']
        
            # 각 메트릭별 데이터 조회
            for metric_name, query in queries.items():
                # 쿼리에서 IP 치환
                formatted_query = query.replace('{ip}', target)
                formatted_query = formatted_query.replace('{{', '{').replace('}}', '}')
            
                # 프로메테우스에 쿼리 실행
                prom_data = self.report.query_prometheus(
                    formatted_query,
                    start_time,
                    end_time,
                    target
                )
                if prom_data and 'values' in prom_data[0]:
                    values = [float(v[1]) for v in prom_data[0]['values']]
                    metrics[metric_name] = {
                        'current': values[-1] if values else 0,
                        'average': np.mean(values) if values else 0,
                        'maximum': np.max(values) if values else 0,
                        'minimum': np.min(values) if values else 0,
                        'values': values
                    }
                else:
                    metrics[metric_name] = {
                        'current': 0,
                        'average': 0,
                        'maximum': 0,
                        'minimum': 0,
                        'values': []
                    }
            return metrics
    
        except Exception as e:
            self.logger.error(f"메트릭 데이터 조회 실패: {str(e)}")
            raise

    # LLM 호출 및 결과 수집
    def _get_llm_analysis(self, server_info):
        try:
            # 메트릭 데이터 준비
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=24)     # 최근 24시간 데이터
            metrics = self._get_metrics(server_info['사설IP'], start_time, end_time)
        
            # 분석용 컨텍스트 생성
            context = {
                "서버정보": {
                    "호스트명": server_info['Hostname'],
                    "IP": server_info['사설IP'],
                    "서비스": server_info['서비스'],
                    "용도": server_info['IT구성정보명'],
                    "운영상태": server_info['운영상태']
                },
                "시스템사양": {
                    "OS": f"{server_info['서버 OS']} {server_info['서버 OS Version']}",
                    "CPU": f"{server_info['CPU Type']} ({server_info['CPU Core 수']})",
                    "메모리": server_info['Memory'],
                    "디스크": server_info['디스크 용량']
                },
                "성능지표": {
                    name: {
                        "현재값": f"{data['current']:.1f}%",
                        "평균": f"{data['average']:.1f}%",
                        "최대": f"{data['maximum']:.1f}%"
                    }
                    for name, data in metrics.items()
                }
            }

            # LLM 요청 데이터 준비
            prompt = self.config['prompts']['system_analysis']
            request_data = {
                "model": self.config['ollama']['model'],
                "prompt": f"{prompt}\n\n시스템 정보:\n{context}",
                "stream": False
            }

            # LLM 서비스 호출
            try:
                import requests
                response = requests.post(
                    self.config['ollama']['url'],
                    json=request_data,
                    timeout=float(self.config['ollama']['timeout'])
                )
            
                if response.status_code == 200:
                    analysis = response.json()['response']
                
                    # 분석 결과가 너무 길면 잘라내기
                    max_length = 1000
                    if len(analysis) > max_length:
                        analysis = analysis[:max_length] + "..."
                
                    return analysis
                else:
                    self.logger.error(f"LLM 서비스 응답 실패: {response.status_code}")
                    return "LLM 분석을 수행할 수 없습니다."

            except requests.exceptions.RequestException as e:
                self.logger.error(f"LLM 서비스 호출 실패: {str(e)}")
                return "LLM 서비스에 연결할 수 없습니다."
            except Exception as e:
                self.logger.error(f"LLM 분석 중 오류 발생: {str(e)}")
                return "LLM 분석 처리 중 오류가 발생했습니다."

        except Exception as e:
            self.logger.error(f"LLM 분석 준비 중 오류 발생: {str(e)}")
            return "시스템 분석을 수행할 수 없습니다."