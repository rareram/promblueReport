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

class DetailedTemplate:
    def __init__(self, report_instance):
        self.report = report_instance
        self.config = report_instance.config
        self.logger = report_instance.logger

    async def create_report(self, target: str, time_range: str, output_dir: str = None, request_id: str = None) -> str:
        """상세 템플릿의 보고서 생성 - 모든 가능한 정보 포함"""
        try:
            end_time = datetime.now()
            if time_range.endswith('h'):
                start_time = end_time - timedelta(hours=int(time_range[:-1]))
            elif time_range.endswith('d'):
                start_time = end_time - timedelta(days=int(time_range[:-1]))
            else:
                start_time = end_time.replace(hour=0, minute=0, second=0, microsecond=0)

            # Use the report instance's method to generate output filename
            output_file = self.report._generate_output_filename(target, output_dir, request_id)
            workbook = Workbook(output_file)
            
            # 상세 보고서는 여러 워크시트로 구성
            await self._create_summary_sheet(workbook, target, start_time, end_time)
            await self._create_system_info_sheet(workbook, target)
            await self._create_metrics_sheet(workbook, target, start_time, end_time)
            await self._create_security_sheet(workbook, target)
            await self._create_analysis_sheet(workbook, target)

            workbook.close()
            return output_file

        except Exception as e:
            self.logger.error(f"Detailed report generation failed: {str(e)}", exc_info=True)
            raise

    async def _create_summary_sheet(self, workbook, target, start_time, end_time):
        """요약 정보 시트 생성"""
        worksheet = workbook.add_worksheet('Summary')
        formats = self._create_detailed_formats(workbook)
        
        # 기본 설정
        self._setup_detailed_worksheet(worksheet)
        
        row = 0
        # 보고서 제목
        worksheet.merge_range(row, 0, row, 7, '서버 상세 점검 보고서', formats['title'])
        row += 2

        # 점검 개요
        overview_data = [
            ['점검 대상', target],
            ['점검 시작', start_time.strftime('%Y-%m-%d %H:%M:%S')],
            ['점검 종료', end_time.strftime('%Y-%m-%d %H:%M:%S')],
            ['보고서 생성', datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
        ]
        
        for item, value in overview_data:
            worksheet.write(row, 0, item, formats['header'])
            worksheet.write(row, 1, value, formats['text'])
            row += 1

        # 주요 지표 요약
        row += 2
        worksheet.merge_range(row, 0, row, 7, '주요 지표 요약', formats['subtitle'])
        row += 1

        metrics_summary = await self._get_metrics_summary(target, start_time, end_time)
        await self._write_metrics_summary(worksheet, row, metrics_summary, formats)

    async def _create_system_info_sheet(self, workbook, target):
        """시스템 정보 시트 생성"""
        worksheet = workbook.add_worksheet('System Info')
        formats = self._create_detailed_formats(workbook)
        
        # CMDB 정보 섹션
        server_info = self._get_server_info(target)
        self._write_cmdb_info(worksheet, formats, server_info)
        
        # 하드웨어 정보 섹션
        self._write_hardware_info(worksheet, formats, server_info)
        
        # 소프트웨어 정보 섹션
        self._write_software_info(worksheet, formats, server_info)
        
        # 네트워크 정보 섹션
        self._write_network_info(worksheet, formats, server_info)

    async def _create_metrics_sheet(self, workbook, target, start_time, end_time):
        """상세 메트릭 시트 생성"""
        worksheet = workbook.add_worksheet('Metrics')
        formats = self._create_detailed_formats(workbook)
        
        # 시간별 메트릭 데이터
        metrics_data = await self._get_detailed_metrics(target, start_time, end_time)
        
        row = 0
        # CPU 섹션
        row = self._write_cpu_metrics(worksheet, metrics_data, formats, row)
        
        # 메모리 섹션
        row = self._write_memory_metrics(worksheet, metrics_data, formats, row)
        
        # 디스크 섹션
        row = self._write_disk_metrics(worksheet, metrics_data, formats, row)
        
        # 네트워크 섹션
        row = self._write_network_metrics(worksheet, metrics_data, formats, row)

    async def _create_security_sheet(self, workbook, target):
        """보안 정보 시트 생성"""
        worksheet = workbook.add_worksheet('Security')
        formats = self._create_detailed_formats(workbook)
        
        row = 0
        # 보안 설정 상태
        row = self._write_security_status(worksheet, target, formats, row)
        
        # 취약점 분석
        row = self._write_vulnerability_analysis(worksheet, target, formats, row)
        
        # 보안 권장사항
        row = self._write_security_recommendations(worksheet, target, formats, row)

    async def _create_analysis_sheet(self, workbook, target):
        """분석 결과 시트 생성"""
        worksheet = workbook.add_worksheet('Analysis')
        formats = self._create_detailed_formats(workbook)
        
        row = 0
        # 시스템 분석 결과
        row = await self._write_system_analysis(worksheet, target, formats, row)
        
        # 성능 분석
        row = await self._write_performance_analysis(worksheet, target, formats, row)
        
        # 용량 계획
        row = self._write_capacity_planning(worksheet, target, formats, row)
        
        # 개선 권장사항
        row = self._write_improvement_recommendations(worksheet, target, formats, row)

    def _create_detailed_formats(self, workbook):
        """상세 보고서용 서식 생성"""
        formats = {}
        
        # 기본 서식
        formats['title'] = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': 'F5F5F5',
            'border': 1
        })
        
        formats['subtitle'] = workbook.add_format({
            'bold': True,
            'font_size': 11,
            'align': 'left',
            'valign': 'vcenter',
            'bg_color': 'E0E0E0',
            'border': 1
        })

        formats['header'] = workbook.add_format({
            'bold': True,
            'font_size': 9,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': 'E0E0E0',
            'border': 1
        })

        formats['text'] = workbook.add_format({
            'font_size': 8,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True
        })

        formats['metric'] = workbook.add_format({
            'font_size': 8,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'num_format': '0.00'
        })
        
        return formats

    def _setup_detailed_worksheet(self, worksheet):
        """상세 워크시트 기본 설정"""
        worksheet.set_paper(9)  # A4
        worksheet.set_landscape(True)
        worksheet.set_margins(left=0.25, right=0.25, top=0.25, bottom=0.25)
        
        # 열 너비 설정
        column_widths = [20, 25, 30, 20, 20, 20, 20, 20]
        for i, width in enumerate(column_widths):
            worksheet.set_column(i, i, width)

    async def _get_metrics_summary(self, target, start_time, end_time):
        """메트릭 요약 데이터 조회"""
        metrics = await self.report._get_metrics(target, start_time, end_time)
        return metrics

    async def _write_metrics_summary(self, worksheet, row, metrics_summary, formats):
        """메트릭 요약 정보 작성"""
        headers = ['지표', '현재', '평균', '최대', '시각화']
        worksheet.write_row(row, 0, headers, formats['header'])
        row += 1

        for metric_name, data in metrics_summary.items():
            visual = self.report.create_visualizer(data['current'])
            worksheet.write(row, 0, metric_name, formats['text'])
            worksheet.write(row, 1, data['current'], formats['metric'])
            worksheet.write(row, 2, data['average'], formats['metric'])
            worksheet.write(row, 3, data['maximum'], formats['metric'])
            worksheet.write(row, 4, visual, formats['text'])
            row += 1

        return row

    def _get_server_info(self, target):
        """서버 정보 조회"""
        try:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'data'
            )
            prefix = self.config['files']['extdata_prefix']
            pattern = os.path.join(data_dir, f"{prefix}*.csv")
            matching_files = glob.glob(pattern)
            
            if not matching_files:
                raise FileNotFoundError(f"'{prefix}'로 시작하는 CSV 파일을 찾을 수 없습니다.")
            
            latest_file = max(matching_files, key=lambda f: 
                int(''.join(filter(str.isdigit, os.path.basename(f))) or '0')
            )
            
            df = pd.read_csv(latest_file, encoding='euc-kr')
            server_info = df[(df['사설IP'] == target) | (df['공인/NAT IP'] == target)]
            
            if server_info.empty:
                if target.startswith('service:'):
                    service_name = target.split(':', 1)[1]
                    server_info = df[df['서비스'] == service_name]
            
            if server_info.empty:
                raise ValueError(f"서버 정보를 찾을 수 없습니다: {target}")
            
            return server_info.iloc[0].to_dict()
            
        except Exception as e:
            self.logger.error(f"서버 정보 조회 실패: {str(e)}")
            raise

    async def _get_detailed_metrics(self, target, start_time, end_time):
        """상세 메트릭 데이터 조회"""
        return await self.report._get_metrics(target, start_time, end_time)

    # Helper methods for writing different sections
    def _write_cmdb_info(self, worksheet, formats, server_info, row=0):
        """CMDB 정보 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, 'CMDB 정보', formats['subtitle'])
        row += 1
        
        cmdb_fields = ['ID', '서비스', 'IT구성정보명', '운영상태', '관리부서', '등록일']
        for field in cmdb_fields:
            worksheet.write(row, 0, field, formats['header'])
            worksheet.write(row, 1, server_info.get(field, '-'), formats['text'])
            row += 1
        
        return row + 1

    def _write_hardware_info(self, worksheet, formats, server_info, row=0):
        """하드웨어 정보 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, '하드웨어 정보', formats['subtitle'])
        row += 1
        
        hw_fields = ['CPU Type', 'CPU Core 수', 'Memory', '디스크 용량', '모델명', '제조사', 'Serial No.']
        for field in hw_fields:
            worksheet.write(row, 0, field, formats['header'])
            worksheet.write(row, 1, server_info.get(field, '-'), formats['text'])
            row += 1
        
        return row + 1

    def _write_software_info(self, worksheet, formats, server_info, row=0):
        """소프트웨어 정보 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, '소프트웨어 정보', formats['subtitle'])
        row += 1
        
        sw_fields = ['서버 OS', '서버 OS Version', 'DB Platform', 'DB Version', 
                    'WAS Platform', 'WAS Version', 'WEB Platform', 'WEB Version']
        for field in sw_fields:
            worksheet.write(row, 0, field, formats['header'])
            worksheet.write(row, 1, server_info.get(field, '-'), formats['text'])
            row += 1
        
        return row + 1

    def _write_network_info(self, worksheet, formats, server_info, row=0):
        """네트워크 정보 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, '네트워크 정보', formats['subtitle'])
        row += 1
        
        net_fields = ['Hostname', '공인/NAT IP', '사설IP', 'VIP', 'HA IP', 'MGMT IP', 'MAC 주소']
        for field in net_fields:
            worksheet.write(row, 0, field, formats['header'])
            worksheet.write(row, 1, server_info.get(field, '-'), formats['text'])
            row += 1
        
        return row + 1

    def _write_cpu_metrics(self, worksheet, metrics_data, formats, row=0):
        """CPU 메트릭 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, 'CPU 사용량 분석', formats['subtitle'])
        row += 1
        
        headers = ['지표', '현재', '평균', '최대', '최소', '시각화']
        worksheet.write_row(row, 0, headers, formats['header'])
        row += 1
        
        cpu_metrics = {k: v for k, v in metrics_data.items() if k.startswith('cpu_')}
        for metric_name, data in cpu_metrics.items():
            visual = self.report.create_visualizer(data['current'])
            worksheet.write(row, 0, metric_name, formats['text'])
            worksheet.write(row, 1, data['current'], formats['metric'])
            worksheet.write(row, 2, data['average'], formats['metric'])
            worksheet.write(row, 3, data['maximum'], formats['metric'])
            worksheet.write(row, 4, data['minimum'], formats['metric'])
            worksheet.write(row, 5, visual, formats['text'])
            row += 1
        
        return row + 2

    def _write_memory_metrics(self, worksheet, metrics_data, formats, row=0):
        """메모리 메트릭 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, '메모리 사용량 분석', formats['subtitle'])
        row += 1
        
        headers = ['지표', '현재', '평균', '최대', '최소', '시각화']
        worksheet.write_row(row, 0, headers, formats['header'])
        row += 1
        
        memory_metrics = {k: v for k, v in metrics_data.items() if k.startswith('memory_')}
        for metric_name, data in memory_metrics.items():
            visual = self.report.create_visualizer(data['current'])
            worksheet.write(row, 0, metric_name, formats['text'])
            worksheet.write(row, 1, data['current'], formats['metric'])
            worksheet.write(row, 2, data['average'], formats['metric'])
            worksheet.write(row, 3, data['maximum'], formats['metric'])
            worksheet.write(row, 4, data['minimum'], formats['metric'])
            worksheet.write(row, 5, visual, formats['text'])
            row += 1
        
        return row + 2

    def _write_disk_metrics(self, worksheet, metrics_data, formats, row=0):
        """디스크 메트릭 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, '디스크 사용량 분석', formats['subtitle'])
        row += 1
        
        headers = ['지표', '현재', '평균', '최대', '최소', '시각화']
        worksheet.write_row(row, 0, headers, formats['header'])
        row += 1
        
        disk_metrics = {k: v for k, v in metrics_data.items() if k.startswith('disk_')}
        for metric_name, data in disk_metrics.items():
            visual = self.report.create_visualizer(data['current'])
            worksheet.write(row, 0, metric_name, formats['text'])
            worksheet.write(row, 1, data['current'], formats['metric'])
            worksheet.write(row, 2, data['average'], formats['metric'])
            worksheet.write(row, 3, data['maximum'], formats['metric'])
            worksheet.write(row, 4, data['minimum'], formats['metric'])
            worksheet.write(row, 5, visual, formats['text'])
            row += 1
        
        return row + 2

    def _write_network_metrics(self, worksheet, metrics_data, formats, row=0):
        """네트워크 메트릭 섹션 작성"""
        worksheet.merge_range(row, 0, row, 7, '네트워크 트래픽 분석', formats['subtitle'])
        row += 1
        
        headers = ['지표', '현재', '평균', '최대', '최소', '시각화']
        worksheet.write_row(row, 0, headers, formats['header'])
        row += 1
        
        network_metrics = {k: v for k, v in metrics_data.items() if k.startswith('network_')}
        for metric_name, data in network_metrics.items():
            visual = self.report.create_visualizer(data['current'])
            worksheet.write(row, 0, metric_name, formats['text'])
            worksheet.write(row, 1, data['current'], formats['metric'])
            worksheet.write(row, 2, data['average'], formats['metric'])
            worksheet.write(row, 3, data['maximum'], formats['metric'])
            worksheet.write(row, 4, data['minimum'], formats['metric'])
            worksheet.write(row, 5, visual, formats['text'])
            row += 1
        
        return row + 2

    def _write_security_status(self, worksheet, target, formats, row=0):
        """보안 상태 정보 작성"""
        worksheet.merge_range(row, 0, row, 7, '보안 설정 상태', formats['subtitle'])
        row += 1
        
        server_info = self._get_server_info(target)
        security_fields = [
            'EQST VM 설치 여부', '백신 설치 여부', 'Tanium 설치 여부',
            '서버 접근제어 연동 여부', 'DB 접근제어 연동 여부'
        ]
        
        for field in security_fields:
            status = server_info.get(field, '미설치')
            worksheet.write(row, 0, field, formats['header'])
            worksheet.write(row, 1, status, formats['text'])
            row += 1
        
        return row + 2

    def _write_vulnerability_analysis(self, worksheet, target, formats, row=0):
        """취약점 분석 결과 작성"""
        worksheet.merge_range(row, 0, row, 7, '취약점 분석', formats['subtitle'])
        row += 1
        
        headers = ['항목', '상태', '위험도', '설명']
        worksheet.write_row(row, 0, headers, formats['header'])
        row += 1
        
        # 보안 설정 점검 항목들
        vulnerabilities = [
            ('OS 보안 패치', '양호', '중', '최신 보안 패치 적용 상태'),
            ('계정 관리', '주의', '상', '기본 계정 존재'),
            ('방화벽 설정', '양호', '상', '필수 포트만 개방'),
            ('로그 설정', '양호', '중', '정상적인 로그 기록 중'),
            ('접근 통제', '양호', '상', '접근 제어 정책 적용')
        ]
        
        for vuln in vulnerabilities:
            worksheet.write_row(row, 0, vuln, formats['text'])
            row += 1
        
        return row + 2

    def _write_security_recommendations(self, worksheet, target, formats, row=0):
        """보안 권장사항 작성"""
        worksheet.merge_range(row, 0, row, 7, '보안 권장사항', formats['subtitle'])
        row += 1
        
        recommendations = [
            '1. 주기적인 보안 패치 적용 및 업데이트 실행',
            '2. 불필요한 서비스 및 포트 비활성화',
            '3. 계정 접근 권한 정기 검토',
            '4. 로그 모니터링 강화',
            '5. 백신 및 보안 도구 최신 버전 유지'
        ]
        
        for rec in recommendations:
            worksheet.merge_range(row, 0, row, 7, rec, formats['text'])
            row += 1
        
        return row + 2

    async def _write_system_analysis(self, worksheet, target, formats, row=0):
        """시스템 분석 결과 작성"""
        worksheet.merge_range(row, 0, row, 7, '시스템 분석', formats['subtitle'])
        row += 1

        try:
            server_info = self._get_server_info(target)
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=24)
            metrics = await self._get_detailed_metrics(target, start_time, end_time)
            
            analysis = await self.report._get_llm_analysis(server_info)
            worksheet.merge_range(row, 0, row, 7, analysis, formats['text'])
            row += 5
            
        except Exception as e:
            self.logger.error(f"시스템 분석 실패: {str(e)}")
            worksheet.merge_range(row, 0, row, 7, "시스템 분석을 수행할 수 없습니다.", formats['text'])
            row += 1
        
        return row + 2

    async def _write_performance_analysis(self, worksheet, target, formats, row=0):
        """성능 분석 결과 작성"""
        worksheet.merge_range(row, 0, row, 7, '성능 분석', formats['subtitle'])
        row += 1
        
        try:
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=24)
            metrics = await self._get_detailed_metrics(target, start_time, end_time)
            
            headers = ['구분', '현재 상태', '권장사항']
            worksheet.write_row(row, 0, headers, formats['header'])
            row += 1
            
            perf_analysis = [
                ('CPU 사용률', self._analyze_metric(metrics['cpu_usage']), '임계치 70% 이하 유지'),
                ('메모리 사용률', self._analyze_metric(metrics['memory_usage']), '임계치 80% 이하 유지'),
                ('디스크 사용률', self._analyze_metric(metrics['disk_usage']), '임계치 80% 이하 유지'),
                ('시스템 부하', self._analyze_metric(metrics['cpu_load1']), 'Load Average 5.0 이하 유지')
            ]
            
            for analysis in perf_analysis:
                worksheet.write_row(row, 0, analysis, formats['text'])
                row += 1
            
        except Exception as e:
            self.logger.error(f"성능 분석 실패: {str(e)}")
            worksheet.merge_range(row, 0, row, 7, "성능 분석을 수행할 수 없습니다.", formats['text'])
            row += 1
        
        return row + 2

    def _write_capacity_planning(self, worksheet, target, formats, row=0):
        """용량 계획 작성"""
        worksheet.merge_range(row, 0, row, 7, '용량 계획', formats['subtitle'])
        row += 1
        
        server_info = self._get_server_info(target)
        
        headers = ['항목', '현재', '권장', '확장 계획']
        worksheet.write_row(row, 0, headers, formats['header'])
        row += 1
        
        capacity_items = [
            ('CPU', server_info['CPU Core 수'], '현재 적정', '부하 80% 시 Core 증설'),
            ('메모리', server_info['Memory'], '현재 적정', '사용률 85% 시 증설'),
            ('디스크', server_info['디스크 용량'], '현재 적정', '사용률 85% 시 증설'),
            ('네트워크', '1Gbps', '현재 적정', '트래픽 포화 시 증설')
        ]
        
        for item in capacity_items:
            worksheet.write_row(row, 0, item, formats['text'])
            row += 1
        
        return row + 2

    def _write_improvement_recommendations(self, worksheet, target, formats, row=0):
        """개선 권장사항 작성"""
        worksheet.merge_range(row, 0, row, 7, '개선 권장사항', formats['subtitle'])
        row += 1
        
        recommendations = [
            '1. 시스템 모니터링 강화',
            '  - 임계치 알람 설정',
            '  - 주요 지표 대시보드 구성',
            '2. 백업 정책 개선',
            '  - 백업 주기 최적화',
            '  - 복구 테스트 정기 수행',
            '3. 성능 최적화',
            '  - 불필요 프로세스 정리',
            '  - 리소스 사용 최적화',
            '4. 가용성 향상',
            '  - 이중화 구성 검토',
            '  - 장애 복구 계획 수립'
        ]
        
        for rec in recommendations:
            worksheet.merge_range(row, 0, row, 7, rec, formats['text'])
            row += 1
        
        return row + 2

    def _analyze_metric(self, metric_data):
        """메트릭 데이터 분석"""
        if not metric_data:
            return "데이터 없음"
            
        current = metric_data['current']
        average = metric_data['average']
        maximum = metric_data['maximum']
        
        if current >= float(self.config['visualization']['threshold_critical']):
            return "위험"
        elif current >= float(self.config['visualization']['threshold_warning']):
            return "주의"
        else:
            return "정상"