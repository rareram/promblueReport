# promblueReport

## Overview

Prometheus + BlueTop + LLM(Ollama) + Excel Report
이 프로젝트는 리눅스OS계열 서버 기반의 시스템의 진단을 위해 대상서버에 부하를 주지 않고, Prometheus의 node_exporter에서 수집한 메트릭을 활용하여 보고서를 생성하는데 목적이 있습니다.
또한 대상 서버의 정보를 식별하는데 도움을 받기 위해 csv로 작성된 자산 정보를 참조하고, 로컬에 설치한 LLM (Ollama)에 Prometheus 메트릭을 분석시켜 보고서 내용을 보완하도록 합니다.

## Features

* PromQL로 Prometheus 서버에 쿼리하여 내용 반영 (기간 설정 가능)
* AI 기반 분석을 위해 로컬 LLM에 쿼리결과 분석 피드백 (Ollama API)
* 외부 csv에서 서버 자산 정보 추출하여 부가설명
* 엑셀 보고서 생성
* 보고서 생성 원격제어 및 csv 서버 자산 정보 확인을 도와주는 슬랙봇

## Installation

1. Clone the repository:

```sh
git clone https://github.com/rareram/promblueReport.git
cd promblueReport
```

2. Install the required dependencies:

```sh
pip install -r requirements.txt
```

3. Configure setup:

* Copy `slrepoBot.conf.example` to `slrepoBot.conf` and update with your Slack tokens
* Copy `promblueReport.conf.example` to `promblueReport.conf` and update with your Proemtheus and Ollama settings

## Usage

1. Start the Slack bot:

```sh
python slrepoBot.py
```

2. In Slack, use the following commands:
  * `/report <IP> [time_range]` : Generate a server report
  * `/info <IP>` : Get server information
  * `/bot-ver` : Check the bot version

3. To generate a report manually:

```python
python promblueReport.py --target <IP_or_Service> --time <time_range>
# Use default prompt
$ python3 promblueReport.py --target xxx.xxx.xxx.xxx
# Use Specific prompt
$ python3 promblueReport.py --target xxx.xxx.xxx.xxx --prompt 2
# Show prompt list
$ python3 promblueReport.py --list-prompts
```

### How to edit template

#### Prometheus 쿼리 결과를 특정 셀에 넣는 방법

```python
def write_prometheus_data(worksheet, row, col, query, ip_address, start_time, end_time, formats):
    formatted_query = format_query(query, ip_address)
    result = query_prometheus(config['prometheus']['url'], formatted_query, start_time, end_time)
    if result and result[0]['values']:
        value = result[0]['values'][-1][1]
        worksheet.write(row, col, float(value), formats['format_stat1'])
    else:
        worksheet.write(row, col, 'N/A', formats['format_string2'])

# 사용 예:
write_prometheus_data(worksheet, 3, 3, cpu_query, ip_address, start_time, end_time, formats)
```
#### csv 내용을 특정 셀에 적는 방법

```python
def write_csv_data(worksheet, row, col, server_data, column_name, formats):
    if column_name in server_data and pd.notnull(server_data[column_name]):
        value = server_data[column_name]
        worksheet.write(row, col, value, formats['format_string1'])
    else:
        worksheet.write(row, col, 'N/A', formats['format_string2'])

# 사용 예:
write_csv_data(worksheet, 2, 1, server, 'IT구성정보명', formats)
```

#### 엑셀 함수와 셀 꾸미기 적용 방법

```python
def apply_excel_formatting(workbook, worksheet):
    # 셀 병합
    worksheet.merge_range('A1:E1', '서버 점검 보고서', workbook.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter', 'font_size': 16}))
    
    # 조건부 서식 적용 (예: CPU 사용률이 80% 이상이면 빨간색으로 표시)
    worksheet.conditional_format('D4:D100', {'type': 'cell', 'criteria': '>=', 'value': 80, 'format': workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})})
    
    # 엑셀 함수 적용
    worksheet.write_formula('F4', '=AVERAGE(D4:E4)', workbook.add_format({'num_format': '0.00%'}))
    
    # 테두리 설정
    border_format = workbook.add_format({'border': 1})
    worksheet.conditional_format('A3:F100', {'type': 'no_blanks', 'format': border_format})
    
    # 열 너비 조정
    worksheet.set_column('A:A', 20)
    worksheet.set_column('B:B', 15)
    worksheet.set_column('C:F', 12)

# 사용 예:
apply_excel_formatting(workbook, worksheet)
```

```python
def generate_report(config_df, config, start_time, end_time, output_file, target, prompt_index):
    workbook = Workbook(output_file)
    worksheet = workbook.add_worksheet('Server Report')
    formats = create_workbook_formats(workbook, config)

    servers = get_target_servers(config_df, target)
    queries = get_queries(config)
    selected_prompt = config['ollama']['prompts'][prompt_index]

    for i, (_, server) in enumerate(servers.iterrows(), start=3):
        ip_address = server['사설IP'] if pd.notnull(server['사설IP']) else server['공인/NAT IP']
        
        write_csv_data(worksheet, i, 0, server, 'IT구성정보명', formats)
        write_csv_data(worksheet, i, 1, server, '사설IP', formats)
        write_csv_data(worksheet, i, 2, server, '서버 OS', formats)
        
        for j, query in enumerate(queries):
            write_prometheus_data(worksheet, i, j+3, query, ip_address, start_time, end_time, formats)
    
    apply_excel_formatting(workbook, worksheet)
    
    # Ollama feedback and other operations...

    workbook.close()
```

#### Slack 앱 생성 및 토큰 생성

1. Slack 앱 생성
   - https://api.slack.com/apps 에 접속
   - "Create New App" 을 클릭
   - "From scratch" 를 선택
   - 앱 이름(예: slrepoBot)을 입력 및 앱을 설치한 워크스페이스 선택
2. 봇 토큰 (Bot Token) 생성
   - 좌측 사이드바에서 "OAuth & Permissions" 선택
   - "Scopes" 섹션에서 'Bot Token Scopes'를 찾아 권한 추가
      + `chat:write`
      + `commands`
      + `files:write`
   - 페이지 상단의 'Install to Workspace'를 클릭하여 앱을 워크스페이스에 설치
   - 설치 후 'Bot User OAuth Token' 에 나온 봇 토큰 복사
3. 앱 토큰 (App Token) 생성
   - 좌측 사이드바에서 "Basic Information" 클릭
   - 'App-Level Token' 섹션에서 'Generate Token and Scopes' 클릭
   - 토큰 이름을 입력하고 'connections:write' 스코프를 추가
   - 'Generate'를 클릭하고 생성된 앱 토큰 복사
4. Socket Mode 설정
   - 좌측 사이드바에서 "Socket Mode" 클릭
   - 'Enable Socket Mode' 토글 스위치를 ON 으로 설정
   - 좌측 사이드바에서 "Event Subscriptions" 클릭
   - 'Enable Events' 토글 스위치를 ON 으로 설정
5. Slack Commands 설정
   - 좌측 사이드바에서 "Slash Commands" 클릭
   - 다음 명령어들을 각각 추가
      + Command: `/report `
      + Request URL: blank
      + Short Description: 프로메테우스 보고서 생성