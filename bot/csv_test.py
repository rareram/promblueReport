import configparser
import pandas as pd

def load_templates(config_path):
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    
    if 'TEMPLATES' not in config:
        raise ValueError("TEMPLATES section not found in config file.")
    
    templates = {}
    for key, value in config['TEMPLATES'].items():
        if key.endswith('_template'):
            templates[key] = value.replace('##', '\n')
    
    return templates

def load_csv(csv_path):
    # return pd.read_csv(csv_path, encoding='utf-8')
    return pd.read_csv(csv_path, encoding='euc-kr')

def get_server_info(df, ip):
    return df[(df['사설IP'] == ip) | (df['공인/NAT IP'] == ip)]

def format_server_info(template, server_info):
    formatted_info = template
    for column in server_info.columns:
        placeholder = f"{{{column}}}"
        if placeholder in formatted_info:
            value = server_info[column].values[0]
            value = '-' if pd.isna(value) or value == '' else str(value)
            formatted_info = formatted_info.replace(placeholder, value)
    return formatted_info

def main():
    config_path = 'slrepoBot.conf'
    csv_path = '../data/구성관리조회 (서버 관리자용)_20240923102100.csv'
    # ip = '10.10.10.10'
    ip = '175.123.252.167'

    try:
        df = load_csv(csv_path)
        
        print("CSV columns:")
        for col in df.columns:
            print(f"- {col}")
        print("\n" + "="*50 + "\n")

        templates = load_templates(config_path)
        server_info = get_server_info(df, ip)

        if server_info.empty:
            print(f"No server info found for IP: {ip}")
        else:
            print(f"Server info for IP {ip}:")
            for name, template in templates.items():
                print(f"\n{name} result:\n{'-'*50}")
                formatted_info = format_server_info(template, server_info)
                print(formatted_info)

    except Exception as e:
        print(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()