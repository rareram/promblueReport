import os
import glob
import pandas as pd
import configparser

# 설정 파일 읽기
config = configparser.ConfigParser()
config.read('slrepoBot.conf')

def get_latest_csv_file(directory, prefix):
    pattern = os.path.join(directory, f"{prefix}*.csv")
    print(f"Searching for files matching pattern: {pattern}")
    files = glob.glob(pattern)
    if not files:
        print(f"No files found. Trying a more flexible pattern.")
        pattern = os.path.join(directory, f"{prefix}*.csv*")
        files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(f"No CSV files found matching the pattern: {pattern}")
    return max(files, key=os.path.getmtime)

def read_csv_file(file_path):
    try:
        # 헤더 없이 CSV 파일 읽기
        df = pd.read_csv(file_path, header=None, encoding='utf-8')
        print("Successfully read the file with UTF-8 encoding.")
    except UnicodeDecodeError:
        # UTF-8로 실패하면 CP949로 시도
        df = pd.read_csv(file_path, header=None, encoding='cp949')
        print("Successfully read the file with CP949 encoding.")
    
    # 실제 헤더 행 찾기
    header_row = df[df.iloc[:, 0] == 'ID'].index[0]
    
    # 헤더 행을 열 이름으로 설정
    df.columns = df.iloc[header_row]
    
    # 헤더 행 이후의 데이터만 유지
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    
    return df

def main():
    # CSV 파일 경로 설정
    csv_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    csv_prefix = config['FILES']['csv_file_prefix']
    
    print(f"Looking for CSV files in directory: {csv_dir}")
    print(f"CSV file prefix: {csv_prefix}")
    
    csv_file = get_latest_csv_file(csv_dir, csv_prefix)
    
    print(f"Reading CSV file: {csv_file}")
    
    df = read_csv_file(csv_file)
    
    # 열 이름 출력
    print("\nColumn names in the CSV file:")
    for col in df.columns:
        print(f"'{col}'")
    
    target_ip = '10.10.10.10'
    ip_columns = ['사설IP', '공인/NAT IP']
    
    for col in ip_columns:
        if col in df.columns:
            server_info = df[df[col] == target_ip]
            if not server_info.empty:
                break
    else:
        print(f"No server found with IP {target_ip}")
        return
    
    if not server_info.empty:
        service = server_info['서비스'].values[0]
        print(f"\nServer with IP {target_ip} belongs to service: {service}")
        print("Other information:")
        info_columns = [
            'IT구성정보명', '자산 설명', '유지보수 업체', '유지보수담당자', 
            'HW 소유부서', 'HW 담당자(정)', 'HW 담당자(부)',
            'SW 소유부서', 'SW 관리자', '도입년월'
        ]
        for column in info_columns:
            if column in server_info.columns:
                value = server_info[column].values[0]
                if pd.notna(value):  # NaN 값이 아닌 경우에만 출력
                    print(f"- {column}: {value}")
            else:
                print(f"- {column}: Column not found")

if __name__ == "__main__":
    main()