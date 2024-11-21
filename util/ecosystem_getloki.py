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

# UTC 타임 포멧
def format_datetime_kst(dt):
    kst_time = dt.astimezone(ZoneInfo('Asia/Seoul'))
    return kst_time.strftime('%Y-%m-%d %H:%M:%S KST')

# Loki 타임스탬프로 변환 (ns)
def convert_loki_timestamp(timestamp_str):
    try:
        # 나노초를 초로 변환 (문자열을 먼저 정수로 변환)
        timestamp_ns = int(timestamp_str)
        timestamp_s = timestamp_ns / 1e9
        
        return datetime.fromtimestamp(timestamp_s, ZoneInfo('Asia/Seoul'))
    except ValueError as e:
        print(f"❌ 타임스탬프 변환 오류: {str(e)}")
        return None

# 파라미터 적용
def build_loki_query(job_name, additional_labels=None):
    query = f'{{job="{job_name}"'
    if additional_labels:
        for key, value in additional_labels.items():
            query += f',{key}="{value}"'
    query += '}'
    return query

def main():
    parser = argparse.ArgumentParser(
        description='Loki 로그 조회 (KST)',
        usage='%(prog)s [options] job_name\n\n'
              '예시:\n'
              '  %(prog)s varlogs\n'
              '  %(prog)s varlogs --hours 2\n'
              '  %(prog)s varlogs --limit 200\n'
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
    
    # 쿼리 생성
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
                        print(f"{time_str}: {log}")
            else:
                print("로그 데이터가 없습니다.")
    else:
        print("❌ 조회된 로그가 없습니다.")

if __name__ == "__main__":
    main()