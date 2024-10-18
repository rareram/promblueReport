import requests
import yaml

# YAML 파일 로드
with open("kube_api_get_pod_name.yml", 'r') as file:
    config = yaml.safe_load(file)

KUBE_API_URL = config['kube_api']['url']
TOKEN = config['kube_api']['token']

# 쿠버네티스 API 호출
headers = {"Authorization": f"Bearer {TOKEN}"}
response = requests.get(KUBE_API_URL, headers=headers)

if response.status_code == 200:
    pods = response.json()
    for pod in pods['items']:
        print(pod['metadata']['name'], pod['metadata']['labels'])
else:
    print(f"Error: {response.status_code} - {response.text}")