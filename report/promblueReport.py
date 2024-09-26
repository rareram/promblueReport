import os
import pandas as pd
from xlsxwriter import Workbook
from prometheus_api_client import PrometheusConnect
import configparser
import argparse
import requests
from datetime import datetime, timedelta

__version__ = '0.3.5'

def get_version():
    return __version__

def print_version():
    print(f"promblueReport version {get_version()}")

def get_latest_extdata_file(prefix):
    files = [f for f in os.listdir('.') if f.startswith(prefix) and f.endswith('.csv')]
    if not files:
        raise FileNotFoundError(f"No files found with prefix '{prefix}'")
    return max(files, key=os.path.getmtime)

def read_extdata_file(filename):
    # CSV 파일 읽기, 제목 2줄 건너뛰기
    df = pd.read_csv(filename, encoding='utf-8', skiprows=2)
    # 실제 데이터는 네 번째 줄부터 시작하므로 첫 번째 행을 건너뛰기
    df = df.iloc[1:].reset_index(drop=True)
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
    if time_str is None or time_str == '':
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif time_str.endswith('h'):
        hours = int(time_str[:-1])
        return now - timedelta(hours=hours), now
    elif time_str.endswith('d'):
        days = int(time_str[:-1])
        return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0), now
    elif time_str == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
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
        "model": "llama3.1",
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
        # target_name = target.replace('.', '_')
        target_name = target
    return f"{prefix}({target_name})-{date_time}.xlsx"

def generate_report(config_df, config, prompts, ollama_timeout, start_time, end_time, output_file, target, prompt_index):
    workbook = Workbook(output_file)
    formats = create_workbook_formats(workbook, config)

    if prompt_index < 0 or prompt_index >= len(prompts):
        print(f"Warning: Invalid prompt index {prompt_index}. Using the first prompt.")
        prompt_index = 0

    selected_prompt = prompts[prompt_index]

    if target.startswith('service:'):
        service_name = target.split(':', 1)[1]
        servers = config_df[config_df['서비스'] == service_name]
    else:
        servers = config_df[(config_df['사설IP'] == target) | (config_df['공인/NAT IP'] == target)]

    if servers.empty:
        raise ValueError(f"No servers found for the given target: {target}")

    queries = get_queries(config)

    for _, server in servers.iterrows():
        ip_address = server['사설IP'] if pd.notnull(server['사설IP']) else server['공인/NAT IP']
        # sheet_name = f"Server_{ip_address.replace('.', '_')}"
        sheet_name = f"{ip_address}"
        if len(sheet_name) > 31:
            sheet_name = sheet_name[:31]
        worksheet = workbook.add_worksheet(sheet_name)

        worksheet.write('A1', f'서버 점검 보고서 - {server["IT구성정보명"]}', formats['format_title1'])
        worksheet.merge_range('A1:F1', f'서버 점검 보고서 - {server["IT구성정보명"]}', formats['format_title1'])

        headers = ['서버명', 'IP 주소', 'OS', 'CPU 사용률', '메모리 사용률', '디스크 사용률']
        for col, header in enumerate(headers):
            worksheet.write(2, col, header, formats['format_header1'])
        
        worksheet.write(3, 0, server['IT구성정보명'], formats['format_string1'])
        worksheet.write(3, 1, ip_address, formats['format_string1'])
        worksheet.write(3, 2, f"{server['서버 OS']} {server['서버 OS Version']}", formats['format_string1'])

        server_metrics = f"Server: {server['IT구성정보명']} ({ip_address})\n"
        for col, query in enumerate(queries, start=3):
            formatted_query = format_query(query, ip_address)
            result = query_prometheus(config['prometheus']['url'], formatted_query, start_time, end_time)
            if result and result[0]['values']:
                value = result[0]['values'][-1][1]
                worksheet.write(3, col, float(value), formats['format_stat1'])
                server_metrics += f"{headers[col]}: {value}\n"
            else:
                worksheet.write(3, col, 'N/A', formats['format_string2'])
                server_metrics += f"{headers[col]}: N/A\n"

        ollama_feedback = get_ollama_feedback(
            config['ollama']['url'],
            selected_prompt,
            server_metrics,
            ollama_timeout
        )

        worksheet.merge_range('A5:F5', '종합 의견', formats['format_title2'])
        worksheet.merge_range('A6:F10', ollama_feedback, formats['format_string1'])

    workbook.close()

def main():
    parser = argparse.ArgumentParser(description='Generate server inspection report')
    parser.add_argument('--time', type=str, default=None, help='Time parameter (e.g., 24h, 7d, today, yesterday, or YYYY-MM-DD. Default: today from 00:00 to now')
    parser.add_argument('--target', type=str, required=True, help='IP address or service name (prefix with "service:")')
    parser.add_argument('--config', type=str, default='promblueReport.conf', help='Path to the configuration file')
    parser.add_argument('--prompt', type=int, default=0, help='Index of the prompt to use (default: 0, first prompt)')
    parser.add_argument('--version', action='version', version=f'%(prog)s {get_version()}')
    parser.add_argument('--list-prompts', action='store_true', help='List available prompts and exit')
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
        generate_report(extdata_df, config, prompts, ollama_timeout, start_time, end_time, output_file, args.target, args.prompt)
        print(f"Report generated successfully: {output_file}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()