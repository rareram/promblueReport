import yaml
import requests
import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path

def get_project_root():
    """Get project root directory"""
    return Path(__file__).parent.parent

def load_config(yaml_path):
    """Load configuration from YAML file with absolute path"""
    try:
        project_root = get_project_root()
        full_path = project_root / yaml_path
        
        if not full_path.exists():
            print(f"❌ 설정 파일을 찾을 수 없습니다: {full_path}")
            return None
            
        with open(full_path, 'r', encoding='utf-8') as f:
            print(f"📂 설정 파일 로드: {full_path}")
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ 설정 파일을 읽는 중 오류 발생: {str(e)}")
        return None

def test_prometheus(url):
    """Test Prometheus connection with a simple query"""
    try:
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=5)
        
        params = {
            'query': 'up',
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

def test_grafana(url):
    """Test Grafana connection with health check API"""
    try:
        health_url = f"{url}/api/health"
        response = requests.get(health_url, timeout=5)
        
        if response.status_code == 200:
            print(f"✅ Grafana 연결 성공 ({url})")
            data = response.json()
            if data.get('database') == 'ok':
                print("   📊 Grafana 데이터베이스 상태: 정상")
            return True
        else:
            print(f"❌ Grafana 연결 실패 (상태 코드: {response.status_code})")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"❌ Grafana 서버에 연결할 수 없습니다: {url}")
        return False
    except Exception as e:
        print(f"❌ Grafana 테스트 중 오류 발생: {str(e)}")
        return False

def test_ollama(url):
    """Test Ollama connection with a simple prompt"""
    try:
        request_data = {
            "model": "llama3.2",
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
    parser = argparse.ArgumentParser(description='Test Prometheus, Grafana, and Ollama connections')
    parser.add_argument('--config', default='report/promblueReport.yml', 
                       help='Path to config YAML file (relative to project root)')
    args = parser.parse_args()
    
    print("\n🔍 서비스 연결 테스트 시작...")
    config = load_config(args.config)
    if not config:
        return
    
    print("\n📡 각 서비스 연결 확인 중...")
    
    services = [
        ('prometheus', test_prometheus),
        ('grafana', test_grafana),
        ('ollama', test_ollama)
    ]
    
    for service_name, test_func in services:
        service_config = config.get(service_name, {})
        service_url = service_config.get('url')
        
        if service_url:
            test_func(service_url)
        else:
            print(f"❌ {service_name.title()} URL이 설정되지 않았습니다")
        print()  # 빈 줄 추가

if __name__ == "__main__":
    main()