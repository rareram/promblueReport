import requests
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Prometheus 서버 URL 설정
prometheus_url = "http://localhost:9090/api/v1/query"

# Prometheus에서 PromQL 쿼리를 사용해 데이터를 가져오는 함수
def query_prometheus(query):
    response = requests.get(prometheus_url, params={'query': query})
    data = response.json()
    # 결과에서 시간값과 메트릭값을 추출
    results = [(float(item['value'][1])) for item in data['data']['result']]
    return results

# Target Host 1 의 CPU 사용량 데이터를 가져오기
query_host_20 = 'node_cpu_seconds_total{instance="10.10.10.20"}'
data_host_20 = query_prometheus(query_host_20)

# Target Host 2 호스트의 CPU 사용량 데이터를 가져오기
query_host_30 = 'node_cpu_seconds_total{instance="10.10.10.30"}'
data_host_30 = query_prometheus(query_host_30)

# 데이터를 데이터프레임으로 변환
df = pd.DataFrame({
    'host_20_cpu': data_host_20,
    'host_30_cpu': data_host_30
})

# 상관관계 계산
correlation = df.corr()

# 상관관계 출력
print("상관관계 행렬:")
print(correlation)

# 상관관계 행렬 히트맵 시각화
plt.figure(figsize=(8, 6))
sns.heatmap(correlation, annot=True, cmap='coolwarm')
plt.title('호스트 간 메트릭 상관관계 히트맵')
plt.show()

# 시간에 따른 CPU 사용량 시각화
df.plot()
plt.title('10.10.10.20 vs 10.10.10.30 CPU 사용량 비교')
plt.xlabel('시간')
plt.ylabel('CPU 사용량 (초)')
plt.show()
