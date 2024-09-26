import argparse
import logging
import sys
from datetime import datetime, timedelta

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

logging.info("Script started")
logging.debug(f"System arguments: {sys.argv}")

def parse_time(time_str):
    now = datetime.now()
    if time_str.endswith('h'):
        hours = int(time_str[:-1])
        return now - timedelta(hours=hours)
    elif time_str.endswith('d'):
        days = int(time_str[:-1])
        return now - timedelta(days=days)
    elif time_str == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_str == 'yesterday':
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d")
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid time format: {time_str}")

parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('--time', type=parse_time, help='Time parameter (e.g., 24h, 7d, today, yesterday, or YYYY-MM-DD)')
parser.add_argument('--target', required=True, help='Target IP or service name')

logging.info("Attempting to parse arguments")

args = parser.parse_args()

logging.info(f"Arguments parsed: {args}")
print(f"Time: {args.time}")
print(f"Target: {args.target}")

logging.info("Script completed")

print(f"Python version: {sys.version}")

# python3 parser_test.py --time 24h --target 10.10.10.10
# python3 parser_test.py --time 7d --target 10.10.10.10
# python3 parser_test.py --time today --target 10.10.10.10
# python3 parser_test.py --time 2024-09-23 --target 10.10.10.10
# python3 parser_test.py --target 10.10.10.10