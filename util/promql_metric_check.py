import requests
import json
from datetime import datetime, timedelta

# Prometheus 서버 URL 설정
prometheus_url = "http://localhost:9090"

# 사용 가능한 모든 메트릭 리스트
def get_metric_names():
    response = requests.get(f"{prometheus_url}/api/v1/label/__name__/values")
    if response.status_code == 200:
        return response.json()['data']
    return []

# 특정 라벨에 대한 모든 값
def get_label_values(label_name):
    response = requests.get(f"{prometheus_url}/api/v1/label/{label_name}/values")
    if response.status_code == 200:
        return response.json()['data']
    return []

# 특정 메트릭 존재 확인 및 샘플 데이터
def check_metric_exists(metric_name):
    response = requests.get(
        f"{prometheus_url}/api/v1/query",
        params={'query': metric_name}
    )
    if response.status_code == 200:
        return response.json()['data']['result']
    return []

try:
    print("Prometheus 메트릭 정보 확인 중...\n")
    
    # CPU 관련 메트릭 찾기
    print("사용 가능한 CPU 관련 메트릭:")
    metrics = get_metric_names()
    cpu_metrics = [m for m in metrics if 'cpu' in m.lower()]
    for metric in cpu_metrics:
        print(f"- {metric}")

    print("사용 가능한 MEM 관련 메트릭:")
    metrics = get_metric_names()
    mem_metrics = [m for m in metrics if 'mem' in m.lower()]
    for metric in mem_metrics:
        print(f"- {metric}")
    
    print("\n사용 가능한 인스턴스들:")
    instances = get_label_values('instance')
    for instance in instances:
        print(f"- {instance}")
    
    print("\n노드 CPU 메트릭 샘플 데이터:")
    sample_data = check_metric_exists('node_cpu_seconds_total')
    if sample_data:
        print("\n사용 가능한 CPU 메트릭 라벨:")
        # 첫 번째 결과의 모든 라벨 출력
        for result in sample_data[:1]:  # 첫 번째 결과만
            print(json.dumps(result['metric'], indent=2))
    else:
        print("CPU 메트릭 데이터를 찾을 수 없습니다.")

except Exception as e:
    print(f"오류 발생: {str(e)}")