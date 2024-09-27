import configparser
import pandas as pd

def load_template(config_path):
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    
    if 'TEMPLATES' not in config:
        raise ValueError("TEMPLATES section not found in config file.")
    
    template = config['TEMPLATES']['info_template']
    
    # '##'를 줄바꿈으로 변경
    template = template.replace('##', '\n')
    
    return template

def load_csv(csv_path):
    return pd.read_csv(csv_path, encoding='utf-8')

def get_server_info(df, ip):
    return df[(df['사설IP'] == ip) | (df['공인/NAT IP'] == ip)]

def format_server_info(template, server_info):
    formatted_info = template
    for column in server_info.columns:
        placeholder = f"{{{column}}}"
        if placeholder in formatted_info:
            value = server_info[column].values[0]
            value = 'N/A' if pd.isna(value) or value == '' else str(value)
            formatted_info = formatted_info.replace(placeholder, value)
    return formatted_info

def main():
    config_path = 'slrepoBot.conf'
    csv_path = '../data/구성관리조회 (서버 관리자용)_202409205617.csv'  # 실제 CSV 파일 경로로 수정해주세요
    ip = '10.10.10.10'

    try:
        template = load_template(config_path)
        print("Template loaded successfully:")
        print(template)
        print("\n" + "="*50 + "\n")

        df = load_csv(csv_path)
        server_info = get_server_info(df, ip)

        if server_info.empty:
            print(f"No server info found for IP: {ip}")
        else:
            formatted_info = format_server_info(template, server_info)
            print(f"Server info for IP {ip}:")
            print(formatted_info)

    except Exception as e:
        print(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()