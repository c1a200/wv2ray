import requests
import re


def check_v2ray():
    print("Checking v2ray direct URL...")
    url = "https://node.zyfx6.xyz/v2rayNG/"
    headers = {
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"v2ray Code: {resp.status_code}")
        if resp.status_code == 200:
            text = resp.text
            print(f"v2ray Body len: {len(text)}")
            extract_token(text, "v2ray Content")
        else:
            print(f"v2ray failed: {resp.text[:100]}")
    except Exception as e:
        print(f"v2ray Exception: {e}")


def check_clash():
    print("\nChecking clash direct URL...")
    url = "https://node.zyfx6.xyz/clash"
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36'
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"clash Code: {resp.status_code}")
        if resp.status_code == 200:
            text = resp.text
            with open("debug.html", "w", encoding="utf-8") as f:
                f.write(text)
            print("Saved debug.html")
            extract_token(text, "clash Content")
    except Exception as e:
        print(f"clash Exception: {e}")


def extract_token(content, source):
    # 查找 token 字段
    patterns = [
        r'token["\s:=]+([a-z0-9]{32})',
        r'token["\s:=]+([a-z0-9]{16,64})',
        r'token=\s*([a-zA-Z0-9]+)',
        r'5[xwthvdjbvm1sbrwomlpcralcs5km568]{31}',
    ]

    found = False
    for p in patterns:
        matches = re.findall(p, content, re.IGNORECASE)
        for m in matches:
            val = m if isinstance(m, str) else m[0]
            print(
                f"[{source}] Found potential token with pattern '{p}': {val}"
            )
            found = True

    if not found:
        print(f"[{source}] No token found.")
        # 打印包含 token 的上下文
        idx = content.lower().find("token")
        while idx != -1:
            start = max(0, idx - 50)
            end = min(len(content), idx + 100)
            print(
                f"[{source}] Context around 'token' at {idx}: "
                f"...{content[start:end]}..."
            )
            idx = content.lower().find("token", idx + 1)
            if idx > 100000:
                break  # limit


if __name__ == "__main__":
    check_v2ray()
    check_clash()
