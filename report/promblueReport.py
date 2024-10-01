import os
import glob
import pandas as pd
import numpy as np
from xlsxwriter import Workbook
from prometheus_api_client import PrometheusConnect
import configparser
import argparse
import requests
from datetime import datetime, timedelta

__version__ = '0.3.12'

def get_version():
    return __version__

def print_version():
    print(f"promblueReport version {get_version()}")

def get_latest_extdata_file(prefix):
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # data 디렉토리 경로
    data_dir = os.path.join(root_dir, 'data')
    # data 디렉토리에서 prefix로 시작하는 모든 CSV 파일 찾기
    pattern = os.path.join(data_dir, f"{prefix}*.csv")
    matching_files = glob.glob(pattern)
    
    if not matching_files:
        raise FileNotFoundError(f"No files found with prefix '{prefix}' in {data_dir}")
    
    # 가장 최근에 수정된 파일을 반환
    return max(matching_files, key=os.path.getmtime)

def read_extdata_file(filename):
    # df = pd.read_csv(filename, encoding='utf-8')
    df = pd.read_csv(filename, encoding='euc-kr')
    # df = df.iloc[1:].reset_index(drop=True)
    print("Columns in the CSV file:", df.columns.tolist())
    return df

def load_config(filename):
    config = configparser.ConfigParser(allow_no_value=True)
    config.read(filename)

    required_settings = {
        'files': ['extdata_prefix', 'output_prefix'],
        'prometheus': ['url', 'queries'],
        'ollama': ['url', 'timeout']
    }

    for section, keys in required_settings.items():
        if section not in config:
            raise ValueError(f"Missing section '{section}' in config file")
        for key in keys:
            if key not in config[section]:
                raise ValueError(f"Missing key '{key}' in section '{section}' of config file")
    # ollama timeout 값을 정수로 변환
    try:
        ollama_timeout = int(config['ollama']['timeout'])
    except ValueError:
        raise ValueError("Ollama timeout must be an integer value in seconds")

    # 프롬프트 검증 및 처리
    if 'prompts' not in config:
        raise ValueError("Missing 'prompts' section in config file")
    
    prompts = list(config['prompts'].values())
    if not prompts:
        raise ValueError("No prompts defined in config file")
    
    return config, prompts, ollama_timeout

def create_workbook_formats(workbook, style_config):
    formats = {}
    for section in style_config.sections():
        if section.startswith('format_'):
            format_dict = dict(style_config[section])
            for key, value in format_dict.items():
                if key in ['bold', 'italic', 'text_wrap']:
                    format_dict[key] = value.lower() == 'true'
                elif key in ['font_size', 'border', 'bottom', 'left', 'right']:
                    format_dict[key] = int(value)
            formats[section] = workbook.add_format(format_dict)
    return formats

def parse_time(time_str):
    now = datetime.now()
    if time_str is None or time_str == '' or time_str == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif time_str.endswith('h'):
        hours = int(time_str[:-1])
        return now - timedelta(hours=hours), now
    elif time_str.endswith('d'):
        days = int(time_str[:-1])
        return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0), now
    elif time_str == 'yesterday':
        yesterday = now - timedelta(days=1)
        return yesterday.replace(hour=0, minute=0, second=0, microsecond=0), yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        try:
            start_date = datetime.strptime(time_str, "%Y-%m-%d")
            return start_date, start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid time format: {time_str}")

def get_queries(config):
    queries_str = config['prometheus']['queries']
    return [q.strip() for q in queries_str.split('\n') if q.strip()]

def format_query(query, ip_address):
    # 이중 중괄호를 단일 중괄호로 변경 (파이썬 중괄호 처리)
    query = query.replace('{{', '{').replace('}}', '}')
    return query.replace('{ip}', ip_address)

def query_prometheus(prom_url, query, start_time, end_time):
    prom = PrometheusConnect(url=prom_url, disable_ssl=True)
    try:
        result = prom.custom_query_range(query, start_time=start_time, end_time=end_time, step="1h")
        return result
    except Exception as e:
        print(f"Error querying Prometheus: {e}")
        print(f"Query: {query}")
        print(f"Start time: {start_time}")
        print(f"End time: {end_time}")
        return None

def get_ollama_feedback(ollama_url, prompt, metrics_dump, timeout):
    headers = {'Content-Type': 'application/json'}
    data = {
        "model": "llama3.2",
        "prompt": f"{prompt}\n\nMetrics dump:\n{metrics_dump}",
        "stream": False
    }

    try:
        timeout = int(timeout)
        response = requests.post(ollama_url, headers=headers, json=data, timeout=timeout)
        if response.status_code == 200:
            return response.json()['response']
        else:
            return f"Failed to get feedback from Ollama. Status code: {response.status_code}"
    except requests.exceptions.Timeout:
        return "Error: Ollama request timed out after {timeout} seconds. The server might be busy or the task might be too complex."
    except requests.exceptions.RequestException as e:
        return f"Error connecting to Ollama: {str(e)}"

def generate_output_filename(prefix, target):
    now = datetime.now()
    date_time = now.strftime("%Y%m%d%H%M")
    if target.startswith('service:'):
        target_name = target.split(':', 1)[1]
    else:
        target_name = target
    
    # 프로젝트 루트 디렉토리 경로
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # output 디렉토리 경로
    output_dir = os.path.join(root_dir, 'output')
    # output 디렉토리가 없으면 생성
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"{prefix}({target_name})-{date_time}.xlsx"
    return os.path.join(output_dir, filename)

def generate_report(config_df, config, prompts, ollama_timeout, start_time, end_time, output_file, target, prompt_index, skip_ollama=False):
    if target.startswith('service:'):
        service_name = target.split(':', 1)[1]
        servers = config_df[config_df['서비스'] == service_name]
    else:
        servers = config_df[(config_df['사설IP'] == target) | (config_df['공인/NAT IP'] == target)]

    if servers.empty:
        raise ValueError(f"No servers found for the given target: {target}")

    queries = get_queries(config)
    
    unavailable_servers = []
    workbook = Workbook(output_file)
    formats = create_workbook_formats(workbook, config)

    for _, server in servers.iterrows():
        ip_address = server['사설IP'] if pd.notnull(server['사설IP']) else server['공인/NAT IP']
        
        worksheet = workbook.add_worksheet(str(ip_address)[:31])
        worksheet.write('A1', f'서버 점검 보고서 - {server["IT구성정보명"]}', formats['format_title1'])
        worksheet.merge_range('A1:F1', f'서버 점검 보고서 - {server["IT구성정보명"]}', formats['format_title1'])

        headers = ['서버명', 'IP 주소', 'OS', 'CPU 사용률', '메모리 사용률', '디스크 사용률']
        for col, header in enumerate(headers):
            worksheet.write(2, col, header, formats['format_header1'])
        
        worksheet.write(3, 0, server['IT구성정보명'], formats['format_string1'])
        worksheet.write(3, 1, ip_address, formats['format_string1'])
        worksheet.write(3, 2, f"{server['서버 OS']} {server['서버 OS Version']}", formats['format_string1'])

        server_metrics = f"Server: {server['IT구성정보명']} ({ip_address})\n"
        metrics_available = False
        
        for col, query in enumerate(queries, start=3):
            formatted_query = format_query(query, ip_address)
            result = query_prometheus(config['prometheus']['url'], formatted_query, start_time, end_time)
            if result and isinstance(result, list) and len(result) > 0 and 'values' in result[0]:
                metrics_available = True
                values = [float(v[1]) for v in result[0]['values'] if v[1] != 'NaN']
                if values:
                    avg_value = np.mean(values)
                    worksheet.write(3, col, avg_value, formats['format_stat1'])
                    server_metrics += f"{headers[col]}: {avg_value:.2f}\n"
                else:
                    worksheet.write(3, col, 'N/A', formats['format_string2'])
                    server_metrics += f"{headers[col]}: N/A\n"
            else:
                worksheet.write(3, col, 'N/A', formats['format_string2'])
                server_metrics += f"{headers[col]}: N/A\n"

        if not metrics_available:
            unavailable_servers.append(f"{server['IT구성정보명']} ({ip_address})")
            worksheet.merge_range('A5:F5', '서버 상태', formats['format_title2'])
            worksheet.merge_range('A6:F10', 'Prometheus node_exporter로부터 데이터를 받을 수 없습니다. 서버 상태를 확인해주세요.', formats['format_string1'])
        elif not skip_ollama:
            ollama_feedback = get_ollama_feedback(
                config['ollama']['url'],
                prompts[prompt_index],
                server_metrics,
                ollama_timeout
            )
            worksheet.merge_range('A5:F5', '종합 의견', formats['format_title2'])
            worksheet.merge_range('A6:F10', ollama_feedback, formats['format_string1'])
        else:
            worksheet.merge_range('A5:F5', '종합 의견', formats['format_title2'])
            worksheet.merge_range('A6:F10', 'Ollama 피드백 생략', formats['format_string1'])

    workbook.close()

    if unavailable_servers:
        return f"다음 서버의 Prometheus node_exporter를 확인해주세요:\n" + "\n".join(unavailable_servers)
    return None

def main():
    parser = argparse.ArgumentParser(description='Generate server inspection report')
    parser.add_argument('--time', type=str, default='today', help='Time parameter (e.g., 24h, 7d, today, yesterday, or YYYY-MM-DD. Default: today')
    parser.add_argument('--target', type=str, required=True, help='IP address or service name (prefix with "service:")')
    parser.add_argument('--output', type=str, default='../output', help='Output directory')
    parser.add_argument('--config', type=str, default='promblueReport.conf', help='Path to the configuration file')
    parser.add_argument('--prompt', type=int, default=0, help='Index of the prompt to use (default: 0, first prompt)')
    parser.add_argument('--skip-ollama', action='store_true', help='Skip Ollama feedback generation')
    parser.add_argument('--version', action='version', version=f'%(prog)s {get_version()}')
    parser.add_argument('--list-prompts', action='store_true', help='List available prompts and exit')
    parser.add_argument('--request-id', type=str, help='Unique identifier for the request')
    args = parser.parse_args()

    print_version()  # 스크립트 실행 시 버전 정보 출력

    try:
        config, prompts, ollama_timeout = load_config(args.config)
        print(f"Configuration loaded from {args.config}")

        if args.list_prompts:
            print("Available prompts:")
            for i, prompt in enumerate(prompts):
                print(f"{i}: {prompt[:50]}...")
            return

        extdata_file = get_latest_extdata_file(config['files']['extdata_prefix'])
        print(f"Using external data file: {extdata_file}")
        extdata_df = read_extdata_file(extdata_file)

        start_time, end_time = parse_time(args.time)
        print(f"Report period: from {start_time} to {end_time}")

        output_file = generate_output_filename(config['files']['output_prefix'], args.target)

        if args.prompt < 0 or args.prompt >= len(prompts):
            print(f"Warning: Invalid prompt index {args.prompt}. Using the first prompt.")
            args.prompt = 0

        print(f"Using prompt index: {args.prompt}")
        message = generate_report(extdata_df, config, prompts, ollama_timeout, start_time, end_time, output_file, args.target, args.prompt, args.skip_ollama)
        if message:
            print(message)
        print(f"Report generated successfully: {output_file}")

    except ValueError as e:
        print(f"Error: {str(e)}")
        raise
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    main()