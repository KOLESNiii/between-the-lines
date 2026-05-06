import os
import requests
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("BET365_INPLAY_URL") or os.getenv("INPLAYDIARYAPI")
if not url:
    raise SystemExit("Missing BET365_INPLAY_URL or INPLAYDIARYAPI")

headers = {
    "User-Agent": os.getenv("BET365_USER_AGENT") or os.getenv("USER_AGENT"),
    "Cookie": os.getenv("BET365_COOKIE") or os.getenv("COOKIE"),
    "Accept": os.getenv("ACCEPT", "*/*"),
    "Accept-Language": os.getenv("ACCEPT_LANGUAGE"),
    "Referer": os.getenv("REFERER"),
    "Origin": os.getenv("ORIGIN"),
}
headers = {k: v for k, v in headers.items() if v}

r = requests.get(url, headers=headers, timeout=30)

print("status:", r.status_code)
print("content-type:", r.headers.get("content-type"))
print("response bytes:", len(r.content))
print("preview:")
print(r.text[:1000])