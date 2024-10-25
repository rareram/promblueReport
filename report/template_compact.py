from abc import ABC
from datetime import datetime, timedelta
from typing import Dict, List, Any
import pandas as pd
from xlsxwriter import Workbook
import numpy as np
import os
import requests
import logging

class CompactTemplate:
    def __init__(self, report_instance):
        self.report = report_instance
        self.config = report_instance.config
        self.logger = report_instance.logger

    def create_report(self, target: str, time_range: str) -> str:
        """압축 템플릿의 보고서 생성 - 핵심 정보만 포함"""
        try:
            # 기본적인 워크북/워크시트 설정은 DefaultTemplate과 유사
            end_time = datetime.now()
            if time_range.endswith('h'):
                start_time = end_time - timedelta(hours=int(time_range[:-1]))
            elif time_range.endswith('d'):
                start_time = end_time - timedelta(days=int(time_range[:-1]))
            else:
                start_time = end_time.replace(hour=0, minute=0, second=0, microsecond=0)

            output_file = self._generate_output_filename(target)
            workbook = Workbook(output_file)
            worksheet = workbook.add_worksheet()
            
            # 압축 템플릿만의 특징:
            # 1. 더 작은 폰트 사이즈 (7pt)
            # 2. 더 좁은 열 너비
            # 3. 핵심 정보만 표시
            # 4. 그래프 대신 단순 숫자로 표시
            # 5. 분석 결과는 핵심 요약만
            
            formats = self._create_compact_formats(workbook)
            self._setup_compact_worksheet(worksheet)
            
            current_row = 0
            current_row = self._write_minimal_header(worksheet, formats, server_info, current_row)
            current_row = self._write_compact_metrics(worksheet, formats, target, start_time, end_time, current_row)
            current_row = self._write_brief_analysis(worksheet, formats, server_info, current_row)

            workbook.close()
            return output_file

        except Exception as e:
            self.logger.error(f"Compact report generation failed: {str(e)}", exc_info=True)
            raise

    def _create_compact_formats(self, workbook):
        """압축 버전용 서식 생성"""
        formats = {}
        # 더 작은 폰트 크기와 최소한의 서식만 정의
        formats['title'] = workbook.add_format({
            'bold': True,
            'font_size': 12,
            'align': 'center'
        })
        formats['header'] = workbook.add_format({
            'bold': True,
            'font_size': 7,
            'align': 'center',
            'border': 1
        })
        formats['text'] = workbook.add_format({
            'font_size': 7,
            'align': 'left',
            'border': 1
        })
        return formats

    def _setup_compact_worksheet(self, worksheet):
        """압축 버전 워크시트 설정"""
        worksheet.set_paper(9)
        worksheet.set_landscape(True)
        worksheet.set_margins(left=0.2, right=0.2, top=0.2, bottom=0.2)
        
        # 더 좁은 열 너비 설정
        column_widths = [12, 15, 20, 12, 12]
        for i, width in enumerate(column_widths):
            worksheet.set_column(i, i, width)

    # 이하 메소드들은 DefaultTemplate의 메소드들을 더 간단하게 구현