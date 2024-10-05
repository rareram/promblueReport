import requests
import time

def check_website(url):
    try:
        start_time = time.time()  # 시작 시간 기록
        response = requests.get(url)
        end_time = time.time()  # 종료 시간 기록

        # 응답 시간 계산
        response_time = end_time - start_time

        # 상태 코드 확인
        if response.status_code == 200:
            print(f"웹사이트 {url}가 정상입니다.")
            print(f"응답 시간: {response_time:.2f} 초")
        else:
            print(f"웹사이트 {url}가 비정상입니다. 상태 코드: {response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"웹사이트 {url}에 접근할 수 없습니다: {e}")

# 사용 예
check_website("https://google.com")
