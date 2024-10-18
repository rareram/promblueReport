import requests
import json

# API 엔드포인트 설정 (실제 URL로 변경해야 합니다)
PROMETHEUS_URL = "http://localhost:9090"
ALERTMANAGER_URL = "http://localhost:9093"
GRAFANA_URL = "http://localhost:3000"

# Grafana API 키 (실제 API 키로 변경해야 합니다)
GRAFANA_API_KEY = "your_grafana_api_key_here"

def test_prometheus_api():
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/status/config")
        if response.status_code == 200:
            print("Prometheus API 연결 성공")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Prometheus API 연결 실패: {response.status_code}")
    except requests.RequestException as e:
        print(f"Prometheus API 요청 오류: {e}")

def test_alertmanager_api():
    try:
        response = requests.get(f"{ALERTMANAGER_URL}/api/v2/alerts")
        if response.status_code == 200:
            print("Alertmanager API 연결 성공")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Alertmanager API 연결 실패: {response.status_code}")
    except requests.RequestException as e:
        print(f"Alertmanager API 요청 오류: {e}")

def test_grafana_api():
    headers = {
        "Authorization": f"Bearer {GRAFANA_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(f"{GRAFANA_URL}/api/health", headers=headers)
        if response.status_code == 200:
            print("Grafana API 연결 성공")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Grafana API 연결 실패: {response.status_code}")
    except requests.RequestException as e:
        print(f"Grafana API 요청 오류: {e}")

if __name__ == "__main__":
    print("Prometheus API 테스트:")
    test_prometheus_api()
    
    print("\nAlertmanager API 테스트:")
    test_alertmanager_api()
    
    print("\nGrafana API 테스트:")
    test_grafana_api()
