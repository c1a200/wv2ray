import requests
import re
import json

def check_api():
    print("Checking API...")
    url = "https://api.github.com/repos/wzdnzd/aggregator/issues/91"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Mozilla/5.0",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"API Code: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            body = data.get("body", "")
            print(f"API Body len: {len(body)}")
            extract_token(body, "API Body")
        else:
            print(f"API failed: {resp.text[:100]}")
    except Exception as e:
        print(f"API Exception: {e}")

def check_html():
    print("\nChecking HTML...")
    url = "https://github.com/wzdnzd/aggregator/issues/91"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"HTML Code: {resp.status_code}")
        if resp.status_code == 200:
            text = resp.text
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(text)
            print("Saved debug.html")
            extract_token(text, "HTML Content")
    except Exception as e:
        print(f"HTML Exception: {e}")

def extract_token(content, source):
    # 查找 token 字段
    patterns = [
        r'token["\s:=]+([a-z0-9]{32})',
        r'token["\s:=]+([a-z0-9]{16,64})',
        r'token=\s*([a-zA-Z0-9]+)',
        r'5[xwthvdjbvm1sbrwomlpcralcs5km568]{31}'
    ]
    
    found = False
    for p in patterns:
        matches = re.findall(p, content, re.IGNORECASE)
        for m in matches:
            val = m if isinstance(m, str) else m[0]
            print(f"[{source}] Found potential token with pattern '{p}': {val}")
            found = True
            
    if not found:
        print(f"[{source}] No token found.")
        # 打印包含 token 的上下文
        idx = content.lower().find("token")
        while idx != -1:
            start = max(0, idx - 50)
            end = min(len(content), idx + 100)
            print(f"[{source}] Context around 'token' at {idx}: ...{content[start:end]}...")
            idx = content.lower().find("token", idx + 1)
            if idx > 100000: break # limit

if __name__ == "__main__":
    check_api()
    check_html()
