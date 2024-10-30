from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
import pandas as pd
import os
from pathlib import Path
import logging
import glob
import requests

# 심플 템플릿 (슬랙용 마크다운)
class SimpleTemplate:
    def __init__(self, report_instance):
        self.report = report_instance
        self.config = report_instance.config
        self.logger = logging.getLogger(__name__)

    async def create_report(self, target: str, time_range: str, output_dir: str = None, request_id: str = None) -> Dict[str, str]:
        try:
            # Calculate time range
            end_time = datetime.now()
            if time_range.endswith('h'):
                start_time = end_time - timedelta(hours=int(time_range[:-1]))
            elif time_range.endswith('d'):
                start_time = end_time - timedelta(days=int(time_range[:-1]))
            else:
                start_time = end_time.replace(hour=0, minute=0, second=0, microsecond=0)

            # Get server info
            server_info = self._get_server_info(target)
            
            # Get metrics
            metrics = await self._get_metrics(target, start_time, end_time)
            
            # Generate report sections
            header = self._generate_header(server_info)
            basic_info = self._generate_basic_info(server_info)
            metrics_info = self._generate_metrics_info(metrics)
            # analysis = await self._generate_analysis(server_info, metrics)

            # 기본 메트릭 즉시 반환
            report = f"{header}\n\n{basic_info}\n\n{metrics_info}"
            # 느려터진 LLM은 스레드 처리 후 반환
            analysis = await self._generate_analysis(server_info, metrics)

            return {
                "report": report,
                "analysis": analysis,
                "needs_thread": True
            }

        except Exception as e:
            self.logger.error(f"Failed to generate simple report: {str(e)}", exc_info=True)
            raise

    # 서버 정보 CMDB (CSV) 참조
    def _get_server_info(self, target: str) -> Dict:
        try:
            # CSV 최신 파일 선택
            files_config = self.config.get('files', {})
            csv_prefix = files_config.get('extdata_prefix')
            pattern = str(self.report.data_dir / f"{csv_prefix}*.csv")
            matching_files = glob.glob(pattern)
            
            if not matching_files:
                raise FileNotFoundError(f"CSV 파일 패턴을 찾을 수 없습니다: {pattern}")
            
            latest_file = max(matching_files, key=lambda f: 
                int(''.join(filter(str.isdigit, os.path.basename(f))) or '0')
            )
            
            # Read CSV file
            df = pd.read_csv(latest_file, encoding='euc-kr')
            
            # Search by IP
            server_info = df[(df['사설IP'] == target) | (df['공인/NAT IP'] == target)]
            
            # Search by service name if IP not found
            if server_info.empty and target.startswith('service:'):
                service_name = target.split(':', 1)[1]
                server_info = df[df['서비스'] == service_name]
            
            if server_info.empty:
                raise ValueError(f"다음 서버 정보를 찾을 수 없습니다: {target}")
            
            return server_info.iloc[0].to_dict()
        
        except Exception as e:
            self.logger.error(f"Failed to get server info: {str(e)}")
            raise

    # Prometheus 메트릭
    async def _get_metrics(self, target: str, start_time: datetime, end_time: datetime) -> Dict[str, Any]:
        try:
            metrics = {}
            promql = self.config.get('prometheus', {}).get('promql', {})
            
            for metric_name, query in promql.items():
                try:
                    # Replace IP in query
                    formatted_query = query.replace('{ip}', target)
                    formatted_query = formatted_query.replace('{{', '{').replace('}}', '}')
                    
                    # Execute Prometheus query
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
                    metrics[metric_name] = self._empty_metric()
                
                except Exception as e:
                    self.logger.error(f"Failed to get metric {metric_name}: {str(e)}")
                    metrics[metric_name] = self._empty_metric()
            
            return metrics
        
        except Exception as e:
            self.logger.error(f"Failed to get metrics: {str(e)}")
            raise

    # 빈 메트릭 값 처리
    def _empty_metric(self) -> Dict[str, Any]:
        return {
            'current': 0,
            'average': 0,
            'maximum': 0,
            'minimum': 0,
            'values': []
        }

    def _generate_header(self, server_info: Dict) -> str:
        """Generate report header section"""
        check_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        return (
            f"*서버 점검 보고서*\n"
            f"점검 시간: {check_time}\n"
            f"대상: {server_info['IT구성정보명']} ({server_info['서비스']})"
        )

    # 서버 정보 섹션
    def _generate_basic_info(self, server_info: Dict) -> str:
        return (
            "*기본 정보*\n"
            f"• *ID:* {server_info['ID']}\n"
            f"• *Hostname:* {server_info['Hostname']}\n"
            f"• *IP:* {server_info['사설IP']} / {server_info['공인/NAT IP']}\n"
            f"• *OS:* {server_info['서버 OS']} {server_info['서버 OS Version']}\n"
            f"• *CPU:* {server_info['CPU Type']} ({server_info['CPU Core 수']})\n"
            f"• *Memory:* {server_info['Memory']}\n"
            f"• *Disk:* {server_info['디스크 용량']}"
        )

    # 메트릭 정보 섹션
    def _generate_metrics_info(self, metrics: Dict) -> str:
        """Generate metrics information section with visualizations"""
        try:
            sections = ["*시스템 성능 지표*"]
            viz_config = self.config.get('visualization', {})
            
            # CPU Metrics
            cpu_data = metrics.get('cpu_usage', self._empty_metric())
            cpu_gauge = self._create_gauge(cpu_data['current'], viz_config.get('slack_gauge', {}))
            cpu_trend = self._create_trend(cpu_data['values'], viz_config.get('slack_trend', {}))
            sections.append(
                f"• *CPU 사용률:* {cpu_gauge} ({cpu_data['current']:.1f}%)\n"
                f"  ↳ 평균: {cpu_data['average']:.1f}% / 최대: {cpu_data['maximum']:.1f}%\n"
                f"  ↳ 추세: {cpu_trend}"
            )

            # Memory Metrics
            mem_data = metrics.get('memory_usage', self._empty_metric())
            mem_gauge = self._create_gauge(mem_data['current'], viz_config.get('slack_gauge', {}))
            mem_trend = self._create_trend(mem_data['values'], viz_config.get('slack_trend', {}))
            mem_total = metrics.get('memory_total', {}).get('current', 0) / (1024**3)  # Convert to GB
            mem_avail = metrics.get('memory_available', {}).get('current', 0) / (1024**3)
            sections.append(
                f"• *Memory 사용률:* {mem_gauge} ({mem_data['current']:.1f}%)\n"
                f"  ↳ 평균: {mem_data['average']:.1f}% / 최대: {mem_data['maximum']:.1f}%\n"
                f"  ↳ Total: {mem_total:.1f}GB / Available: {mem_avail:.1f}GB\n"
                f"  ↳ 추세: {mem_trend}"
            )

            # Disk Metrics
            disk_data = metrics.get('disk_usage', self._empty_metric())
            disk_gauge = self._create_gauge(disk_data['current'], viz_config.get('slack_gauge', {}))
            disk_trend = self._create_trend(disk_data['values'], viz_config.get('slack_trend', {}))
            disk_read = metrics.get('disk_read_bytes', {}).get('current', 0) / (1024**2)  # MB/s
            disk_write = metrics.get('disk_write_bytes', {}).get('current', 0) / (1024**2)
            sections.append(
                f"• *Disk 사용률:* {disk_gauge} ({disk_data['current']:.1f}%)\n"
                f"  ↳ 평균: {disk_data['average']:.1f}% / 최대: {disk_data['maximum']:.1f}%\n"
                f"  ↳ I/O: Read {disk_read:.1f}MB/s / Write {disk_write:.1f}MB/s\n"
                f"  ↳ 추세: {disk_trend}"
            )

            # Network Metrics
            net_rx = metrics.get('network_receive', {}).get('current', 0) / (1024**2)  # MB/s
            net_tx = metrics.get('network_transmit', {}).get('current', 0) / (1024**2)
            sections.append(
                f"• *Network 트래픽:*\n"
                f"  ↳ Receive: {net_rx:.1f}MB/s\n"
                f"  ↳ Transmit: {net_tx:.1f}MB/s"
            )

            return "\n\n".join(sections)

        except Exception as e:
            self.logger.error(f"Failed to generate metrics info: {str(e)}")
            return "*시스템 성능 지표 생성 중 오류 발생*"

    # 분석 포멧 - LLM 피드백
    async def _generate_analysis(self, server_info: Dict, metrics: Dict) -> str:
        try:
            # Create context for LLM
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

            # Request LLM analysis
            ollama_config = self.config.get_config('ollama')
            prompt_config = self.config.get_config('prompt')

            request_data = {
                "model": ollama_config.get('model'),
                "prompt": f"{prompt_config.get('simple_analysis')}\n\n시스템 정보:\n{context}",
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
                    return analysis
                else:
                    return "시스템 분석을 수행할 수 없습니다."

            except requests.exceptions.RequestException as e:
                self.logger.error(f"LLM request failed: {str(e)}")
                return "LLM 서비스에 연결할 수 없습니다."

        except Exception as e:
            self.logger.error(f"Failed to generate analysis: {str(e)}")
            return "시스템 분석 중 오류가 발생했습니다."

    def _create_gauge(self, value: float, config: Dict) -> str:
        """Create visual gauge bar for Slack"""
        width = config.get('width', 10)
        chars = config.get('chars', {})
        filled_char = chars.get('filled', '■')
        empty_char = chars.get('empty', '□')
        prefix = config.get('prefix', '')
        suffix = config.get('suffix', '')
        
        filled = int((value / 100) * width)
        return f"{prefix}{filled_char * filled}{empty_char * (width - filled)}{suffix}"

    def _create_trend(self, values: List[float], config: Dict) -> str:
        """Create trend visualization for Slack"""
        if not values:
            return ""
            
        width = config.get('width', 8)
        chars = config.get('chars', '▁▂▃▄▅▆▇█')
        indicators = config.get('indicators', {})
        
        # Calculate trend direction
        if len(values) >= 2:
            start_avg = sum(values[:3]) / min(3, len(values))
            end_avg = sum(values[-3:]) / min(3, len(values))
            diff = end_avg - start_avg
            
            if abs(diff) < 5:  # threshold for "flat" trend
                indicator = indicators.get('flat', '➡︎')
            elif diff > 0:
                indicator = indicators.get('up', '⬆︎')
            else:
                indicator = indicators.get('down', '⬇︎')
        else:
            indicator = indicators.get('flat', '➡︎')
        
        # Create sparkline visualization
        if len(values) < width:
            values_subset = values
        else:
            values_subset = []
            chunk_size = len(values) / width
            for i in range(width):
                start_idx = int(i * chunk_size)
                end_idx = int((i + 1) * chunk_size)
                chunk_avg = sum(values[start_idx:end_idx]) / (end_idx - start_idx)
                values_subset.append(chunk_avg)
        
        # Normalize values to char range
        min_val = min(values_subset)
        max_val = max(values_subset)
        if max_val == min_val:
            normalized = [0] * len(values_subset)
        else:
            normalized = [
                ((v - min_val) / (max_val - min_val)) * (len(chars) - 1)
                for v in values_subset
            ]
        
        # Create visualization
        trend = ''.join(chars[int(v)] for v in normalized)
        return f"{trend} {indicator}"

    def _format_size(self, size_bytes: float) -> str:
        """Format byte sizes for human reading"""
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        unit_index = 0
        while size_bytes >= 1024 and unit_index < len(units) - 1:
            size_bytes /= 1024
            unit_index += 1
        return f"{size_bytes:.1f}{units[unit_index]}"