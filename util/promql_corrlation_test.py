import requests
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# Prometheus 서버 URL 설정
prometheus_url = "http://localhost:9090/api/v1/query_range"

def query_prometheus(query, start_time, end_time, step='1m'):
    """
    지정된 시간 범위에 대해 Prometheus 쿼리를 실행합니다.
    """
    params = {
        'query': query,
        'start': start_time.timestamp(),
        'end': end_time.timestamp(),
        'step': step
    }
    
    print(f"Executing query: {query}")
    print(f"Parameters: {params}")
    
    response = requests.get(prometheus_url, params=params)
    if response.status_code != 200:
        raise Exception(f"Query failed: {response.text}")
    
    data = response.json()
    if 'data' not in data or 'result' not in data['data']:
        raise Exception("No data returned from Prometheus")
    
    # 결과가 비어있는지 확인
    if not data['data']['result']:
        raise Exception("No results found for the query")
    
    # 첫 번째 결과의 값들을 시계열로 변환
    result = data['data']['result'][0]
    timestamps = [datetime.fromtimestamp(float(x[0])) for x in result['values']]
    values = [float(x[1]) for x in result['values']]
    
    return pd.Series(values, index=timestamps)

try:
    # 시간 범위 설정 (최근 1시간)
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=1)
    
    # CPU 사용률을 계산하는 PromQL 쿼리 (수정된 버전)
    query_host_1 = 'rate(node_cpu_seconds_total{instance="172.24.203.190",mode="idle"}[5m])'
    query_host_2 = 'rate(node_cpu_seconds_total{instance="172.24.203.190",mode="idle"}[5m])'
    
    # 데이터 수집
    print("첫 번째 호스트 데이터 수집 중...")
    data_host_1 = query_prometheus(query_host_1, start_time, end_time)
    print("\n두 번째 호스트 데이터 수집 중...")
    data_host_2 = query_prometheus(query_host_2, start_time, end_time)
    
    # 데이터프레임 생성
    df = pd.DataFrame({
        'host_1_cpu': data_host_1,
        'host_2_cpu': data_host_2
    })
    
    # 결측치 처리
    df = df.dropna()
    
    if df.empty:
        raise Exception("No valid data after processing")
    
    # 상관관계 계산
    correlation = df.corr()
    
    # 결과 출력
    print("\n상관관계 행렬:")
    print(correlation)
    
    # 상관관계 히트맵 생성
    plt.figure(figsize=(8, 6))
    sns.heatmap(correlation, annot=True, cmap='coolwarm', vmin=-1, vmax=1)
    plt.title('호스트 간 CPU 사용률 상관관계')
    plt.tight_layout()
    plt.savefig('correlation_heatmap.png')
    print("\n상관관계 히트맵이 'correlation_heatmap.png'로 저장되었습니다.")
    
    # 시계열 그래프 생성
    plt.figure(figsize=(12, 6))
    df.plot()
    plt.title('CPU 사용률 비교')
    plt.xlabel('시간')
    plt.ylabel('CPU 사용률')
    plt.legend(['Host 1', 'Host 2'])
    plt.tight_layout()
    plt.savefig('cpu_usage_comparison.png')
    print("CPU 사용률 비교 그래프가 'cpu_usage_comparison.png'로 저장되었습니다.")
    
except Exception as e:
    print(f"오류 발생: {str(e)}")