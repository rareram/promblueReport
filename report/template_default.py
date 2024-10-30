from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import pandas as pd
from xlsxwriter import Workbook
import os
from pathlib import Path
import logging
import glob
import requests

class DefaultTemplate:
    """기본 Excel 템플릿 - A4 세로 한 페이지 보고서"""
    
    def __init__(self, report_instance):
        self.report = report_instance
        self.config = report_instance.config
        self.logger = logging.getLogger(__name__)

    async def create_report(self, target: str, time_range: str, output_dir: str = None, request_id: str = None) -> str:
        """A4 세로 한 페이지 보고서 생성"""
        try:
            # 시간 범위 계산
            end_time = datetime.now()
            if time_range.endswith('h'):
                start_time = end_time - timedelta(hours=int(time_range[:-1]))
            elif time_range.endswith('d'):
                start_time = end_time - timedelta(days=int(time_range[:-1]))
            else:
                start_time = end_time.replace(hour=0, minute=0, second=0, microsecond=0)

            # 서버 정보 조회
            server_info = self._get_server_info(target)
            
            # 메트릭 데이터 조회
            metrics_data = await self._get_metrics(target, start_time, end_time)

            # 출력 파일명 생성
            files_config = self.config.get('files', {})
            output_prefix = files_config.get('output_prefix', '서버진단보고서')
            
            if output_dir:
                output_path = Path(output_dir)
            else:
                output_path = self.report.output_dir

            timestamp = datetime.now().strftime('%Y%m%d%H%M')
            if request_id:
                filename = f"{output_prefix}({target})_{timestamp}-{request_id}.xlsx"
            else:
                filename = f"{output_prefix}({target})_{timestamp}.xlsx"

            output_file = output_path / filename
            workbook = Workbook(str(output_file))
            worksheet = workbook.add_worksheet()

            # 페이지 설정 및 이미지 추가
            self._init_page(worksheet)
            
            # 스타일 생성
            formats = self._create_formats(workbook)

            # 보고서 작성
            current_row = 0
            current_row = self._write_header(worksheet, formats, server_info, current_row)
            current_row = self._write_basic_info(worksheet, formats, server_info, current_row)
            current_row = await self._write_metrics(worksheet, formats, metrics_data, current_row)
            current_row = await self._write_analysis(worksheet, formats, server_info, metrics_data, current_row)

            workbook.close()
            return str(output_file)

        except Exception as e:
            self.logger.error(f"Report generation failed: {str(e)}", exc_info=True)
            raise

    def _get_server_info(self, target: str) -> dict:
        """서버 정보 조회"""
        try:
            # 구성관리조회 CSV 파일 찾기
            files_config = self.config.get('files', {})
            csv_prefix = files_config.get('extdata_prefix')
            pattern = str(self.report.data_dir / f"{csv_prefix}*.csv")
            matching_files = glob.glob(pattern)
            
            if not matching_files:
                raise FileNotFoundError(f"No CSV files found matching pattern: {pattern}")
            
            # 가장 최근 파일 선택
            latest_file = max(matching_files, key=lambda f: 
                            int(''.join(filter(str.isdigit, os.path.basename(f))) or '0')
                            )
            
            self.logger.info(f"Using CSV file: {latest_file}")
            
            # CSV 파일 읽기
            df = pd.read_csv(latest_file, encoding='euc-kr')
            
            # IP로 서버 검색
            server_info = df[(df['사설IP'] == target) | (df['공인/NAT IP'] == target)]
            
            # 서비스명으로 검색 (IP로 찾지 못한 경우)
            if server_info.empty and target.startswith('service:'):
                service_name = target.split(':', 1)[1]
                server_info = df[df['서비스'] == service_name]
            
            if server_info.empty:
                raise ValueError(f"No server information found for: {target}")
            
            return server_info.iloc[0].to_dict()
        
        except Exception as e:
            self.logger.error(f"Failed to get server info: {str(e)}")
            raise

    async def _get_metrics(self, target: str, start_time: datetime, end_time: datetime) -> Dict:
        """메트릭 데이터 조회"""
        try:
            metrics = {}
            promql = self.config.get('prometheus', {}).get('promql', {})
            
            for metric_name, query in promql.items():
                try:
                    # 쿼리에서 IP 치환
                    formatted_query = query.replace('{ip}', target)
                    formatted_query = formatted_query.replace('{{', '{').replace('}}', '}')
                    
                    # 프로메테우스 쿼리 실행
                    result = await self.report.query_prometheus(formatted_query, start_time, end_time)
                    
                    if result and isinstance(result, list) and len(result) > 0:
                        if 'values' in result[0]:
                            values = [float(v[1]) for v in result[0]['values']]
                            metrics[metric_name] = {
                                'current': values[-1] if values else 0,
                                'average': float(pd.Series(values).mean()),
                                'maximum': float(pd.Series(values).max()),
                                'minimum': float(pd.Series(values).min()),
                                'values': values
                            }
                            continue
                    
                    self.logger.warning(f"No data returned for metric: {metric_name}")
                    metrics[metric_name] = {
                        'current': 0,
                        'average': 0,
                        'maximum': 0,
                        'minimum': 0,
                        'values': []
                    }
                
                except Exception as e:
                    self.logger.error(f"Failed to get metric {metric_name}: {str(e)}")
                    metrics[metric_name] = {
                        'current': 0,
                        'average': 0,
                        'maximum': 0,
                        'minimum': 0,
                        'values': []
                    }
            
            return metrics
        
        except Exception as e:
            self.logger.error(f"Failed to get metrics: {str(e)}")
            raise

    def _init_page(self, worksheet):
        """페이지 초기화 (페이지 설정, 배경, 로고)"""
        try:
            # 1. 페이지 설정
            self._setup_page(worksheet)
            
            # 2. 배경 이미지 삽입 (설정된 경우)
            self._insert_background(worksheet)
            
            # 3. 로고 삽입 (설정된 경우)
            self._insert_logo(worksheet)

        except Exception as e:
            self.logger.error(f"Failed to initialize page: {str(e)}")
            raise

    def _setup_page(self, worksheet):
        """페이지 설정"""
        layout_config = self.config.get('layouts', {})
        page_config = layout_config.get('page', {})
        margins = page_config.get('margins', {})

        worksheet.set_paper(9)  # A4
        worksheet.set_portrait()  # 세로 방향
        worksheet.set_margins(
            left=margins.get('left', 10) / 25.4,    # mm를 inch로 변환
            right=margins.get('right', 10) / 25.4,
            top=margins.get('top', 10) / 25.4,
            bottom=margins.get('bottom', 10) / 25.4
        )

    def _insert_background(self, worksheet):
        """배경 이미지 삽입"""
        try:
            bg_config = self.config.get('layouts', {}).get('background', {})
            if not bg_config.get('enabled', False):
                return

            bg_file = self.report.data_dir / bg_config.get('image', 'backbg.png')
            if not bg_file.exists():
                self.logger.warning(f"Background image not found: {bg_file}")
                return

            position = bg_config.get('position', {})
            size = bg_config.get('size', {})
            
            options = {
                'x_offset': position.get('x', 50),
                'y_offset': position.get('y', 50),
                'width': size.get('width', 500),
                'height': size.get('height', 700),
                'opacity': bg_config.get('opacity', 0.3),
                'positioning': 3
            }

            worksheet.insert_image(0, 0, str(bg_file), options)

        except Exception as e:
            self.logger.warning(f"Failed to insert background: {str(e)}")

    def _insert_logo(self, worksheet):
        """로고 삽입"""
        try:
            logo_config = self.config.get('layouts', {}).get('logo', {})
            if not logo_config.get('enabled', True):
                return

            logo_file = self.report.data_dir / logo_config.get('image', 'logo.png')
            if not logo_file.exists():
                self.logger.warning(f"Logo image not found: {logo_file}")
                return

            # 로고 위치 계산
            position = logo_config.get('position', 'top-right')
            size = logo_config.get('size', {})
            margin = logo_config.get('margin', {})
            offset = logo_config.get('offset', {})

            # 위치에 따른 기본 좌표 설정
            if position == 'top-right':
                x = 8  # I열
                y = 0
            elif position == 'top-left':
                x = 0
                y = 0
            elif position == 'top-center':
                x = 4  # E열
                y = 0
            else:
                x = 0
                y = 0

            # 오프셋 적용
            x += offset.get('x', 0)
            y += offset.get('y', 0)

            options = {
                'width': size.get('width', 200),
                'height': size.get('height', 50),
                'x_offset': margin.get('right', 10),
                'y_offset': margin.get('top', 5),
                'positioning': 3
            }

            worksheet.insert_image(y, x, str(logo_file), options)

        except Exception as e:
            self.logger.warning(f"Failed to insert logo: {str(e)}")

    def _create_formats(self, workbook) -> Dict[str, Any]:
        """워크북 포맷 생성"""
        formats_config = self.config.get('formats', {})
        formats = {}
        
        # 기본 포맷들 생성
        for format_name, format_info in formats_config.items():
            style = {}
            
            # 폰트 설정
            if 'font' in format_info:
                font = format_info['font']
                style.update({
                    'font_name': font.get('family', 'Arial'),
                    'font_size': font.get('size', 10),
                    'bold': font.get('bold', False),
                    'color': font.get('color')
                })
            
            # 정렬 설정
            if 'alignment' in format_info:
                align = format_info['alignment']
                style.update({
                    'align': align.get('horizontal', 'left'),
                    'valign': align.get('vertical', 'top'),
                    'text_wrap': align.get('wrap_text', False)
                })
            
            # 테두리 설정
            if 'border' in format_info:
                if isinstance(format_info['border'], dict):
                    style.update({
                        'border': format_info['border'].get('width', 1),
                        'border_color': format_info['border'].get('color')
                    })
                else:
                    style['border'] = format_info['border']
            
            # 배경색 설정
            if 'background' in format_info:
                style['bg_color'] = format_info['background']
            
            # 높이 설정
            # if 'height' in format_info:
                # style['height'] = format_info['height']

            formats[format_name] = workbook.add_format(style)
        
        return formats

    def _write_header(self, worksheet, formats, server_info: Dict, row: int) -> int:
        """헤더 섹션 작성"""
        try:
            # 제목 행
            worksheet.merge_range(
                row, 0, row, 11,
                f'서버 점검 보고서 - {server_info["IT구성정보명"]}',
                formats['title']
            )
            row += 1

            # 점검 정보 행
            check_time = datetime.now().strftime('%Y-%m-%d %H:%M')
            worksheet.merge_range(
                row, 0, row, 11,
                f'점검 일시: {check_time}',
                formats['header']
            )
            
            return row + 2
            
        except Exception as e:
            self.logger.error(f"Failed to write header: {str(e)}")
            raise

    def _write_basic_info(self, worksheet, formats, server_info: Dict, row: int) -> int:
        """기본 정보 섹션 작성"""
        try:
            # 기본 정보 헤더
            worksheet.merge_range(row, 0, row, 11, '기본 시스템 정보', formats['header'])
            row += 1

            # 서버 기본 정보 그리드 (4x3 레이아웃)
            info_grid = [
                ('ID', server_info['ID'], 
                 'CMDB 등록일', server_info['등록일'], 
                 'CMDB 갱신일', server_info.get('최종 변경일시', '-')),
                
                ('서비스', server_info['서비스'], 
                 '운영상태', server_info['운영상태'], 
                 '분류', server_info['분류']),
                
                ('Hostname', server_info['Hostname'], 
                 '사설IP', server_info['사설IP'], 
                 '공인IP', server_info['공인/NAT IP']),
                
                ('OS 정보', f"{server_info['서버 OS']} {server_info['서버 OS Version']}", 
                 'CPU', f"{server_info['CPU Type']} ({server_info['CPU Core 수']})",
                 'Memory', server_info['Memory'])
            ]

            # 그리드 작성
            for info_row in info_grid:
                for i in range(0, 6, 2):
                    worksheet.write(row, i*2, info_row[i], formats['header'])
                    worksheet.merge_range(
                        row, i*2+1, row, i*2+1, 
                        info_row[i+1], 
                        formats['text']
                    )
                row += 1

            return row + 1

        except Exception as e:
            self.logger.error(f"Failed to write basic info: {str(e)}")
            raise

    async def _write_metrics(self, worksheet, formats, metrics: Dict, row: int) -> int:
        """메트릭 섹션 작성"""
        try:
            # 메트릭 섹션 헤더
            worksheet.merge_range(row, 0, row, 11, '시스템 성능 지표', formats['header'])
            row += 1

            # CPU 섹션
            cpu_data = metrics.get('cpu_usage', {'current': 0, 'average': 0, 'maximum': 0})
            gauge = self._create_gauge(cpu_data['current'])
            worksheet.merge_range(
                row, 0, row, 11,
                f"CPU 사용률: {gauge} ({cpu_data['current']:.1f}%) - "
                f"현재: {cpu_data['current']:.1f}% / 평균: {cpu_data['average']:.1f}% / "
                f"최대: {cpu_data['maximum']:.1f}%",
                self._get_metric_format(formats, cpu_data['current'])
            )
            row += 1

            # CPU Load
            for load_type in ['cpu_load1', 'cpu_load5', 'cpu_load15']:
                if load_type in metrics:
                    load = metrics[load_type]
                    worksheet.write(
                        row, 1,
                        f"{load_type}: {load['current']:.2f} / {load['average']:.2f} / {load['maximum']:.2f}",
                        formats['text']
                    )
                    row += 1

            row += 1  # 간격 추가

            # Memory 섹션
            mem_data = metrics.get('memory_usage', {'current': 0, 'average': 0, 'maximum': 0})
            gauge = self._create_gauge(mem_data['current'])
            
            # Memory Total/Available 계산 (bytes -> GB)
            mem_total = metrics.get('memory_total', {'current': 0})['current'] / (1024**3)
            mem_avail = metrics.get('memory_available', {'current': 0})['current'] / (1024**3)
            
            worksheet.merge_range(
                row, 0, row, 11,
                f"Memory 사용률: {gauge} ({mem_data['current']:.1f}%) - "
                f"현재: {mem_data['current']:.1f}% / 평균: {mem_data['average']:.1f}% / "
                f"최대: {mem_data['maximum']:.1f}%",
                self._get_metric_format(formats, mem_data['current'])
            )
            row += 1

            worksheet.write(
                row, 1,
                f"Total: {mem_total:.1f}GB / Available: {mem_avail:.1f}GB",
                formats['text']
            )
            row += 2  # 간격 추가

            # Disk 섹션
            disk_data = metrics.get('disk_usage', {'current': 0, 'average': 0, 'maximum': 0})
            gauge = self._create_gauge(disk_data['current'])
            
            # Disk I/O 계산 (bytes/sec -> MB/sec)
            disk_read = metrics.get('disk_read_bytes', {'current': 0})['current'] / (1024**2)
            disk_write = metrics.get('disk_write_bytes', {'current': 0})['current'] / (1024**2)
            
            worksheet.merge_range(
                row, 0, row, 11,
                f"Disk 사용률: {gauge} ({disk_data['current']:.1f}%) - "
                f"현재: {disk_data['current']:.1f}% / 평균: {disk_data['average']:.1f}% / "
                f"최대: {disk_data['maximum']:.1f}%",
                self._get_metric_format(formats, disk_data['current'])
            )
            row += 1

            worksheet.write(
                row, 1,
                f"Read: {disk_read:.1f}MB/s / Write: {disk_write:.1f}MB/s",
                formats['text']
            )
            row += 2  # 간격 추가

            # Network 섹션
            net_rx = metrics.get('network_receive', {'current': 0})['current'] / (1024**2)
            net_tx = metrics.get('network_transmit', {'current': 0})['current'] / (1024**2)
            
            worksheet.merge_range(
                row, 0, row, 11,
                f"Network 트래픽: Receive {net_rx:.1f}MB/s / Transmit {net_tx:.1f}MB/s",
                formats['text']
            )
            
            return row + 2

        except Exception as e:
            self.logger.error(f"Failed to write metrics: {str(e)}")
            raise

    async def _write_analysis(self, worksheet, formats, server_info: Dict, metrics: Dict, row: int) -> int:
        """분석 섹션 작성"""
        try:
            # LLM 분석 요청용 컨텍스트 생성
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
                    if isinstance(data, dict) and 'current' in data
                }
            }

            # LLM 분석 요청
            ollama_config = self.config.get('ollama', {})
            request_data = {
                "model": ollama_config.get('model', 'llama3.2'),
                "prompt": f"{self.config.get('prompt', {}).get('system_analysis')}\n\n시스템 정보:\n{context}",
                "stream": False
            }

            try:
                response = requests.post(
                    ollama_config.get('url'),
                    json=request_data,
                    timeout=float(ollama_config.get('timeout', 300))
                )
                
                if response.status_code == 200:
                    analysis = response.json()['response']
                    
                    # 분석 결과 섹션 헤더
                    worksheet.merge_range(row, 0, row, 11, '시스템 분석', formats['header'])
                    row += 1
                    
                    # 분석 결과 길이에 따라 레이아웃 조정
                    total_chars = len(analysis)
                    if total_chars < 200:  # 짧은 분석
                        num_columns = 3
                    elif total_chars < 400:  # 중간 분석
                        num_columns = 2
                    else:  # 긴 분석
                        num_columns = 1

                    chars_per_column = total_chars // num_columns
                    column_width = 12 // num_columns
                    
                    # 분석 결과 작성
                    for i in range(num_columns):
                        start_idx = i * chars_per_column
                        end_idx = start_idx + chars_per_column if i < num_columns - 1 else total_chars
                        column_text = analysis[start_idx:end_idx]
                        
                        worksheet.merge_range(
                            row, i * column_width,
                            row + 3, (i + 1) * column_width - 1,
                            column_text,
                            formats['text']
                        )
                    
                    row += 4
                
                else:
                    worksheet.merge_range(
                        row, 0, row, 11,
                        "LLM 분석을 수행할 수 없습니다.",
                        formats['text']
                    )
                    row += 1

            except Exception as e:
                self.logger.error(f"LLM analysis failed: {str(e)}")
                worksheet.merge_range(
                    row, 0, row, 11,
                    f"분석 중 오류가 발생했습니다: {str(e)}",
                    formats['text']
                )
                row += 1

            return row

        except Exception as e:
            self.logger.error(f"Failed to write analysis: {str(e)}")
            raise

    def _create_gauge(self, value: float, width: int = 10) -> str:
        """게이지 바 생성"""
        viz_config = self.config.get('visualization', {}).get('gauge', {})
        filled_char = viz_config.get('chars', {}).get('filled', '█')
        empty_char = viz_config.get('chars', {}).get('empty', '▒')
        gauge_width = viz_config.get('width', width)
        
        filled = int((value / 100) * gauge_width)
        return filled_char * filled + empty_char * (gauge_width - filled)

    def _get_metric_format(self, formats: Dict[str, Any], value: float) -> Any:
        """메트릭 값에 따른 포맷 반환"""
        thresholds = self.config.get('thresholds', {})
        if value >= thresholds.get('cpu', {}).get('critical', 90):
            return formats.get('metric_critical', formats['text'])
        elif value >= thresholds.get('cpu', {}).get('warning', 70):
            return formats.get('metric_warning', formats['text'])
        return formats.get('metric', formats['text'])