# promblueReport
Prometheus + BlueTop + LLM(Ollama) + Excel Report

## Highlights

* 외부 csv (서버 부가설명) 참조
* prometheus 쿼리 내용 반영
* 로컬 LLM에 쿼리결과 분석 피드백

## How to use parameters

* 기본 사용 (첫 번째 프롬프트 사용):
```sh
$ python3 promblueReport.py --target 172.24.203.190
```
* 특정 프롬프트 사용:
```sh
python3 promblueReport.py --target 172.24.203.190 --prompt 1
```
* 사용 가능한 프롬프트 목록 보기:
```sh
python3 promblueReport.py --list-prompts
```


## How to edit template

### Prometheus 쿼리 결과를 특정 셀에 넣는 방법

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
### csv 내용을 특정 셀에 적는 방법

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

### 엑셀 함수와 셀 꾸미기 적용 방법

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