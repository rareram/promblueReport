import yaml
import requests
import argparse
from datetime import datetime, timedelta

def load_config(yaml_path):
    """Load configuration from YAML file"""
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"설정 파일을 읽는 중 오류 발생: {str(e)}")
        return None

def test_prometheus(url):
    """Test Prometheus connection with a simple query"""
    try:
        # 현재 시간 기준으로 5분 전후의 시간범위 설정
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=5)
        
        params = {
            'query': 'up',  # 가장 기본적인 쿼리
            'start': str(int(start_time.timestamp())),
            'end': str(int(end_time.timestamp())),
            'step': '1m'
        }
        
        response = requests.get(f"{url}/api/v1/query_range", params=params, timeout=5)
        
        if response.status_code == 200:
            print(f"✅ Prometheus 연결 성공 ({url})")
            data = response.json()
            if data['status'] == 'success':
                return True
            else:
                print(f"❌ 프로메테우스 응답 오류: {data.get('error', '알 수 없는 오류')}")
                return False
        else:
            print(f"❌ Prometheus 연결 실패 (상태 코드: {response.status_code})")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Prometheus 서버에 연결할 수 없습니다: {url}")
        return False
    except Exception as e:
        print(f"❌ Prometheus 테스트 중 오류 발생: {str(e)}")
        return False

def test_ollama(url):
    """Test Ollama connection with a simple prompt"""
    try:
        request_data = {
            "model": "llama3.2",  # 기본 모델
            "prompt": "test",
            "stream": False
        }
        
        response = requests.post(url, json=request_data, timeout=5)
        
        if response.status_code == 200:
            print(f"✅ Ollama 연결 성공 ({url})")
            return True
        else:
            print(f"❌ Ollama 연결 실패 (상태 코드: {response.status_code})")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Ollama 서버에 연결할 수 없습니다: {url}")
        return False
    except Exception as e:
        print(f"❌ Ollama 테스트 중 오류 발생: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Test Prometheus and Ollama connections')
    parser.add_argument('--config', default='promblueReport.yml', help='Path to config YAML file')
    args = parser.parse_args()
    
    print(f"\n🔍 설정 파일 '{args.config}' 로드 중...")
    config = load_config(args.config)
    if not config:
        return
    
    print("\n📊 서비스 연결 테스트 시작...")
    
    # Prometheus 테스트
    prom_url = config.get('prometheus', {}).get('url')
    if prom_url:
        test_prometheus(prom_url)
    else:
        print("❌ Prometheus URL이 설정되지 않았습니다")
    
    print()  # 빈 줄 추가
    
    # Ollama 테스트
    ollama_url = config.get('ollama', {}).get('url')
    if ollama_url:
        test_ollama(ollama_url)
    else:
        print("❌ Ollama URL이 설정되지 않았습니다")

if __name__ == "__main__":
    main()