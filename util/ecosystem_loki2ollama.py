import yaml
import requests
import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import urllib.parse
from zoneinfo import ZoneInfo

def get_project_root():
    return Path(__file__).parent.parent

def load_config(yaml_path):
    try:
        project_root = get_project_root()
        full_path = project_root / yaml_path
        
        if not full_path.exists():
            print(f"❌ 설정 파일을 찾을 수 없습니다: {full_path}")
            return None
            
        with open(full_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ 설정 파일을 읽는 중 오류 발생: {str(e)}")
        return None

# Ollama 로그 분석
def analyze_with_ollama(ollama_url, logs_content):
    try:
        prompt = f"""로그를 분석하고 특이사항을 정리. 한글로 작성:

{logs_content}"""

        request_data = {
            "model": "llama3.1",
            "prompt": prompt,
            "stream": False
        }
        
        response = requests.post(ollama_url, json=request_data, timeout=300)
        
        if response.status_code == 200:
            return response.json().get('response', '분석 결과를 가져올 수 없습니다.')
        else:
            return f"❌ Ollama 분석 실패 (상태 코드: {response.status_code})"
            
    except Exception as e:
        return f"❌ Ollama 분석 중 오류 발생: {str(e)}"

# 로그 쿼리
def query_loki_logs(loki_url, query, start_time, end_time, limit=100):
    try:
        url = f"{loki_url}/loki/api/v1/query_range"
        
        start_utc = start_time.astimezone(ZoneInfo('UTC'))
        end_utc = end_time.astimezone(ZoneInfo('UTC'))
        
        params = {
            'query': query,
            'start': start_utc.isoformat(),
            'end': end_utc.isoformat(),
            'limit': limit,
            'direction': 'BACKWARD'
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'result' in data['data']:
                return data['data']['result']
            else:
                print("❌ 로그 데이터가 없습니다.")
                return None
        else:
            print(f"❌ Loki 쿼리 실패 (상태 코드: {response.status_code})")
            print(f"응답: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Loki 쿼리 중 오류 발생: {str(e)}")
        return None

def format_datetime_kst(dt):
    kst_time = dt.astimezone(ZoneInfo('Asia/Seoul'))
    return kst_time.strftime('%Y-%m-%d %H:%M:%S KST')

def convert_loki_timestamp(timestamp_str):
    try:
        timestamp_ns = int(timestamp_str)
        timestamp_s = timestamp_ns / 1e9
        return datetime.fromtimestamp(timestamp_s, ZoneInfo('Asia/Seoul'))
    except ValueError as e:
        print(f"❌ 타임스탬프 변환 오류: {str(e)}")
        return None

def build_loki_query(job_name, additional_labels=None):
    query = f'{{job="{job_name}"'
    if additional_labels:
        for key, value in additional_labels.items():
            query += f',{key}="{value}"'
    query += '}'
    return query

def main():
    parser = argparse.ArgumentParser(
        description='Loki 로그 조회 및 분석 (KST)',
        usage='%(prog)s [options] job_name\n\n'
              '예시:\n'
              '  %(prog)s varlogs\n'
              '  %(prog)s varlogs --hours 2\n'
              '  %(prog)s varlogs --limit 200\n'
              '  %(prog)s varlogs --analyze\n'
              '  %(prog)s varlogs --query \'{job="varlogs",host="myserver"}\''
    )
    
    parser.add_argument('job_name', nargs='?', help='조회할 job 이름')
    parser.add_argument('--config', default='report/promblueReport.yml',
                       help='설정 파일 경로 (프로젝트 루트 기준)')
    parser.add_argument('--query', help='전체 LogQL 쿼리 (job_name 대신 사용)')
    parser.add_argument('--hours', type=int, default=1,
                       help='조회할 시간 범위 (시간 단위)')
    parser.add_argument('--limit', type=int, default=100,
                       help='최대 로그 라인 수')
    parser.add_argument('--analyze', action='store_true',
                       help='Ollama를 사용하여 로그 분석 수행')
    
    args = parser.parse_args()
    
    if not args.job_name and not args.query:
        parser.print_help()
        return
    
    config = load_config(args.config)
    if not config:
        return
        
    loki_config = config.get('loki', {})
    loki_url = loki_config.get('url')
    
    if not loki_url:
        print("❌ Loki URL이 설정되지 않았습니다.")
        return
    
    query = args.query if args.query else build_loki_query(args.job_name)
    
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    end_time = now
    start_time = end_time - timedelta(hours=args.hours)
    
    print(f"\n🔍 Loki 로그 조회 중...")
    print(f"• 쿼리: {query}")
    print(f"• 기간: {args.hours}시간")
    print(f"• 시작: {format_datetime_kst(start_time)}")
    print(f"• 종료: {format_datetime_kst(end_time)}")
    print(f"• 제한: {args.limit}줄\n")
    
    results = query_loki_logs(loki_url, query, start_time, end_time, args.limit)
    
    if results:
        # 분석용 로그 텍스트 수집
        all_logs = []
        
        for stream in results:
            labels = stream.get('stream', {})
            print(f"\n📄 Stream Labels: {labels}")
            
            values = stream.get('values', [])
            if values:
                print("\n로그 내용:")
                for timestamp, log in values:
                    dt = convert_loki_timestamp(timestamp)
                    if dt:
                        time_str = dt.strftime('%Y-%m-%d %H:%M:%S KST')
                        log_line = f"{time_str}: {log}"
                        print(log_line)
                        all_logs.append(log_line)
            else:
                print("로그 데이터가 없습니다.")
        
        # Ollama 분석 수행
        if args.analyze and all_logs:
            print("\n🤖 Ollama 로그 분석 중...\n")
            
            ollama_url = config.get('ollama', {}).get('url')
            if not ollama_url:
                print("❌ Ollama URL이 설정되지 않았습니다.")
                return
                
            logs_content = "\n".join(all_logs)
            analysis = analyze_with_ollama(ollama_url, logs_content)
            
            print("📊 분석 결과:")
            print("=" * 50)
            print(analysis)
            print("=" * 50)
    else:
        print("❌ 조회된 로그가 없습니다.")

if __name__ == "__main__":
    main()
