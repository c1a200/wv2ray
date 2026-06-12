#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 v2ray 订阅文件并保存

上游已直接提供 clash 和 v2ray 格式的订阅链接，
不再需要格式转换、协议过滤、proxy-groups 优化等逻辑。

保留: 去重 + short-id 引号修复 + GeoIP（可选）+ Issue 变体（可选）
"""

import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime

# 尝试加载本地 .env 文件中的环境变量 (用于本地运行 Telegram 抓取时覆盖 URL)
env_file = Path(__file__).parent / '..' / '.env'
if env_file.exists():
    try:
        for line in env_file.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()
    except Exception as e:
        print(f"⚠️ 加载本地 .env 失败: {e}")

# 确保控制台输出使用 UTF-8，避免 Windows 上的 Unicode 报错
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import yaml
import requests

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


DEFAULT_DIRECT_V2RAY_URL = 'https://node.zyfx6.xyz/v2ray'
DEFAULT_DIRECT_CLASH_URL = 'https://node.zyfx6.xyz/clash'


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _env_to_bool(value: str, default: bool) -> bool:
    """将环境变量字符串转换为布尔值。"""
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _validate_content(content: str, is_clash: bool):
    """验证订阅内容是否有效，如果包含失效 Mock 节点则抛出异常。"""
    text = content
    if not is_clash:
        # 尝试 Base64 解码
        import base64
        try:
            text = base64.b64decode(content.strip()).decode('utf-8', errors='ignore')
        except Exception:
            pass

    # 检测失效关键字
    invalid_keywords = ['订阅已失效', '请重新获取', 'xmsubbot', 'txwl666']
    for kw in invalid_keywords:
        if kw in text:
            raise ValueError(f"订阅内容包含失效特征词 '{kw}'，判定为已失效 Mock 数据")


def _apply_token_to_url(url: str, token: str) -> str:
    """如果提供了 token，则在 URL 中追加或更新 token 参数。"""
    if not token:
        return url
    from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
    parsed = urlparse(url)
    query_params = dict(parse_qsl(parsed.query))
    query_params['token'] = token
    new_query = urlencode(query_params)
    return urlunparse(parsed._replace(query=new_query))


def _fetch_direct_content(url: str) -> str:
    """直接抓取订阅地址内容。"""
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36'
        ),
        'Accept': '*/*',
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = 'utf-8'
    content = resp.text
    if not content.strip():
        raise Exception(f'直接抓取返回空内容: {url}')
    return content


def _dedup_proxies(content: str) -> str:
    """根据核心参数去除重复节点，只保留第一个出现的。

    判断依据：server + port + type + password/uuid 相同即为重复。
    """
    try:
        data = yaml.safe_load(content)
    except Exception:
        return content

    if not isinstance(data, dict) or 'proxies' not in data:
        return content

    proxies = data['proxies']
    if not proxies:
        return content

    seen = set()
    unique = []
    for proxy in proxies:
        if not isinstance(proxy, dict):
            unique.append(proxy)
            continue

        # 生成指纹：server + port + type + 密钥字段
        server = str(proxy.get('server', ''))
        port = str(proxy.get('port', ''))
        ptype = str(proxy.get('type', ''))
        # 不同协议用不同字段作为密钥
        key = proxy.get('uuid') or proxy.get('password') or ''
        fingerprint = f"{server}:{port}:{ptype}:{key}"

        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        unique.append(proxy)

    removed = len(proxies) - len(unique)
    if removed > 0:
        print(f"✓ 去重: 移除 {removed} 个重复节点（保留 {len(unique)} 个）")
        data['proxies'] = unique
        return yaml.dump(data, allow_unicode=True, default_flow_style=False,
                         sort_keys=False, width=1000)

    return content


def _fix_short_id_quotes(content: str) -> str:
    """修复 YAML 输出中纯数字 short-id 未加引号的问题。

    如 short-id: 09 会被 Clash YAML 1.1 解析器当作无效八进制，
    需要加上引号变成 short-id: '09'。
    """
    return re.sub(
        r'([ ]+short-id: )(\d+)$',
        lambda m: f"{m.group(1)}'{m.group(2)}'",
        content,
        flags=re.MULTILINE,
    )


def _fix_short_id_quotes(content: str) -> str:
    """修复 YAML 输出中纯数字 short-id 未加引号的问题。

    如 short-id: 09 会被 Clash YAML 1.1 解析器当作无效八进制，
    需要加上引号变成 short-id: '09'。
    """
    return re.sub(
        r'([ ]+short-id: )(\d+)$',
        lambda m: f"{m.group(1)}'{m.group(2)}'",
        content,
        flags=re.MULTILINE,
    )


# 国家代码 → 国旗 + 中文名
COUNTRY_MAP = {
    'HK': ('🇭🇰', '香港'),
    'TW': ('🇨🇳', '台湾'),
    'JP': ('🇯🇵', '日本'),
    'SG': ('🇸🇬', '新加坡'),
    'US': ('🇺🇸', '美国'),
    'KR': ('🇰🇷', '韩国'),
    'GB': ('🇬🇧', '英国'),
    'DE': ('🇩🇪', '德国'),
    'FR': ('🇫🇷', '法国'),
    'NL': ('🇳🇱', '荷兰'),
    'CA': ('🇨🇦', '加拿大'),
    'AU': ('🇦🇺', '澳大利亚'),
    'RU': ('🇷🇺', '俄罗斯'),
    'IN': ('🇮🇳', '印度'),
    'BR': ('🇧🇷', '巴西'),
    'IT': ('🇮🇹', '意大利'),
    'CH': ('🇨🇭', '瑞士'),
    'SE': ('🇸🇪', '瑞典'),
    'FI': ('🇫🇮', '芬兰'),
    'NO': ('🇳🇴', '挪威'),
    'PL': ('🇵🇱', '波兰'),
    'ES': ('🇪🇸', '西班牙'),
    'AT': ('🇦🇹', '奥地利'),
    'IE': ('🇮🇪', '爱尔兰'),
    'TR': ('🇹🇷', '土耳其'),
    'TH': ('🇹🇭', '泰国'),
    'MY': ('🇲🇾', '马来西亚'),
    'PH': ('🇵🇭', '菲律宾'),
    'VN': ('🇻🇳', '越南'),
    'ID': ('🇮🇩', '印尼'),
}


def _detect_country_from_name(name: str) -> str:
    name_upper = name.upper()
    if any(w in name_upper for w in ['香港', 'HK', 'HONG KONG', 'HONGKONG']):
        return 'HK'
    if any(w in name_upper for w in ['台湾', 'TW', 'TAIWAN', 'ROC']):
        return 'TW'
    if any(w in name_upper for w in ['日本', 'JP', 'JAPAN', '东京', '大阪']):
        return 'JP'
    if any(w in name_upper for w in ['新加坡', 'SG', 'SINGAPORE', '狮城']):
        return 'SG'
    if any(w in name_upper for w in ['美国', 'US', 'UNITED STATES', 'AMERICA', '纽约', '洛杉矶', '硅谷', '波特兰']):
        return 'US'
    if any(w in name_upper for w in ['韩国', 'KR', 'KOREA', '首尔']):
        return 'KR'
    if any(w in name_upper for w in ['英国', 'GB', 'UK', 'UNITED KINGDOM', '伦敦']):
        return 'GB'
    if any(w in name_upper for w in ['德国', 'DE', 'GERMANY', '法兰克福']):
        return 'DE'
    if any(w in name_upper for w in ['法国', 'FR', 'FRANCE', '巴黎']):
        return 'FR'
    if any(w in name_upper for w in ['荷兰', 'NL', 'NETHERLANDS', '阿姆斯特丹']):
        return 'NL'
    if any(w in name_upper for w in ['加拿大', 'CA', 'CANADA', '温哥华', '多伦多']):
        return 'CA'
    if any(w in name_upper for w in ['澳大利亚', 'AU', 'AUSTRALIA', '悉尼', '墨尔本']):
        return 'AU'
    if any(w in name_upper for w in ['俄罗斯', 'RU', 'RUSSIA', '莫斯科']):
        return 'RU'
    if any(w in name_upper for w in ['印度', 'IN', 'INDIA', '孟买']):
        return 'IN'
    if any(w in name_upper for w in ['巴西', 'BR', 'BRAZIL']):
        return 'BR'
    return 'OTHERS'


def _get_node_info(proxy: dict) -> dict:
    name = proxy.get('name', '')
    ptype = proxy.get('type', 'unknown')
    server = str(proxy.get('server', ''))
    port = str(proxy.get('port', ''))
    
    masked_server = ''
    if server:
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', server):
            parts = server.split('.')
            masked_server = f"{parts[0]}.{parts[1]}.***.***"
        else:
            parts = server.split('.')
            if len(parts) >= 2:
                domain = parts[0]
                tld = '.'.join(parts[1:])
                mask_len = max(2, len(domain) - 2)
                masked_server = f"{domain[:2]}{'*'*mask_len}.{tld}"
            else:
                masked_server = f"{server[:2]}***"
    
    flag = '🌐'
    country_code = 'OTHERS'
    country_name = '其它地区'
    
    flag_match = re.match(r'^([\U0001F1E6-\U0001F1FF]{2})', name)
    if flag_match:
        flag = flag_match.group(1)
        for code, (f, cn) in COUNTRY_MAP.items():
            if f == flag:
                country_code = code
                country_name = cn
                break
    else:
        for code, (f, cn) in COUNTRY_MAP.items():
            if code in name.upper() or cn in name:
                flag = f
                country_code = code
                country_name = cn
                break
                
    if country_code == 'OTHERS':
        detected = _detect_country_from_name(name)
        if detected != 'OTHERS':
            country_code = detected
            flag, country_name = COUNTRY_MAP[detected]
            
    return {
        'name': name,
        'type': ptype,
        'server': masked_server,
        'port': port,
        'country_code': country_code,
        'country_name': country_name,
        'flag': flag
    }


def _get_v2ray_node_count(content: str) -> int:
    if not content:
        return 0
    try:
        import base64
        try:
            decoded = base64.b64decode(content.strip()).decode('utf-8', errors='ignore')
        except Exception:
            decoded = content
        lines = [line.strip() for line in decoded.splitlines() if line.strip()]
        return len([line for line in lines if not line.startswith('#')])
    except Exception:
        return 0


def _generate_dashboard_html(output_path: Path, summary: dict, metadata: dict):
    """生成漂亮的响应式 HTML 仪表盘。"""
    summary_json_str = json.dumps(summary, ensure_ascii=False)
    
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>V2ray / Clash 自动订阅中心</title>
    <meta name="description" content="全自动更新的高速代理订阅节点获取中心，支持 Clash, Shadowrocket, Sing-box, v2rayN 等客户端的一键导入和配置。">
    <!-- Google Fonts Outfit & Inter -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <!-- FontAwesome icons via cdnjs -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- QRCode.js client-side library -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: rgba(17, 24, 39, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --primary: #3b82f6;
            --primary-glow: rgba(59, 130, 246, 0.15);
            --secondary: #10b981;
            --secondary-glow: rgba(16, 185, 129, 0.15);
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --accent: #f59e0b;
            --glass-blur: 16px;
        }}

        .light-mode {{
            --bg-color: #f3f4f6;
            --card-bg: rgba(255, 255, 255, 0.8);
            --card-border: rgba(0, 0, 0, 0.08);
            --primary: #2563eb;
            --primary-glow: rgba(37, 99, 235, 0.1);
            --secondary: #059669;
            --secondary-glow: rgba(5, 150, 105, 0.1);
            --text-main: #1f2937;
            --text-muted: #6b7280;
            --accent: #d97706;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Inter', -apple-system, sans-serif;
            transition: background-color 0.3s ease, border-color 0.3s ease, color 0.3s ease;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            min-height: 100vh;
            padding: 2rem 1rem;
            display: flex;
            flex-direction: column;
            align-items: center;
            overflow-x: hidden;
            background-image: radial-gradient(circle at 10% 20%, rgba(59, 130, 246, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(16, 185, 129, 0.05) 0%, transparent 40%);
            background-attachment: fixed;
        }}

        header {{
            width: 100%;
            max-width: 1100px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2.5rem;
            padding: 0 0.5rem;
        }}

        .brand-container {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .brand-logo {{
            width: 2.75rem;
            height: 2.75rem;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 1.25rem;
            font-weight: bold;
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3);
        }}

        .brand-title {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.5rem;
            font-weight: 700;
            background: linear-gradient(to right, var(--text-main), var(--text-muted));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .header-controls {{
            display: flex;
            align-items: center;
            gap: 1rem;
        }}

        .theme-btn {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            color: var(--text-main);
            width: 2.5rem;
            height: 2.5rem;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            backdrop-filter: blur(var(--glass-blur));
        }}

        .theme-btn:hover {{
            border-color: var(--primary);
            color: var(--primary);
            transform: scale(1.05);
        }}

        .status-badge {{
            background: var(--primary-glow);
            border: 1px solid rgba(59, 130, 246, 0.3);
            color: var(--primary);
            padding: 0.4rem 0.8rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .status-badge::before {{
            content: '';
            display: inline-block;
            width: 8px;
            height: 8px;
            background-color: var(--primary);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--primary);
            animation: pulse 2s infinite;
        }}

        @keyframes pulse {{
            0% {{ transform: scale(0.9); opacity: 0.6; }}
            50% {{ transform: scale(1.2); opacity: 1; }}
            100% {{ transform: scale(0.9); opacity: 0.6; }}
        }}

        main {{
            width: 100%;
            max-width: 1100px;
            display: grid;
            grid-template-columns: 1.8fr 1.2fr;
            gap: 2rem;
        }}

        @media (max-width: 900px) {{
            main {{
                grid-template-columns: 1fr;
            }}
        }}

        .glass-card {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            backdrop-filter: blur(var(--glass-blur));
            border-radius: 16px;
            padding: 1.5rem;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
            margin-bottom: 2rem;
        }}

        .section-title {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            color: var(--text-main);
            border-left: 4px solid var(--primary);
            padding-left: 0.6rem;
        }}

        /* Stats Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            margin-bottom: 2rem;
        }}

        @media (max-width: 500px) {{
            .stats-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .stat-card {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 1rem;
            text-align: center;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}

        .stat-val {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--primary);
            margin-bottom: 0.25rem;
        }}

        .stat-lbl {{
            font-size: 0.8rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        /* Subscription Cards */
        .sub-card {{
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1.25rem;
            position: relative;
            overflow: hidden;
        }}

        .sub-card:hover {{
            border-color: rgba(59, 130, 246, 0.3);
            box-shadow: 0 4px 20px rgba(59, 130, 246, 0.05);
        }}

        .sub-card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.75rem;
        }}

        .sub-name {{
            font-weight: 600;
            font-size: 1.05rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .sub-format-badge {{
            font-size: 0.75rem;
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .v2ray-badge {{
            background: rgba(16, 185, 129, 0.15);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.2);
        }}

        .clash-badge {{
            background: rgba(245, 158, 11, 0.15);
            color: #f59e0b;
            border: 1px solid rgba(245, 158, 11, 0.2);
        }}

        .url-box {{
            display: flex;
            align-items: center;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 0.6rem 0.8rem;
            margin-bottom: 0.75rem;
            position: relative;
        }}

        .url-text {{
            font-family: monospace;
            font-size: 0.85rem;
            overflow-x: auto;
            white-space: nowrap;
            width: 100%;
            color: var(--text-main);
            scrollbar-width: none; /* Firefox */
        }}

        .url-text::-webkit-scrollbar {{
            display: none; /* Safari/Chrome */
        }}

        .action-btns {{
            display: flex;
            gap: 0.5rem;
        }}

        .btn {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            color: var(--text-main);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.4rem;
            text-decoration: none;
        }}

        .btn:hover {{
            background: var(--primary);
            border-color: var(--primary);
            color: white;
            transform: translateY(-1px);
        }}

        .btn-primary {{
            background: var(--primary);
            border-color: var(--primary);
            color: white;
        }}

        .btn-primary:hover {{
            opacity: 0.9;
        }}

        .btn-icon-only {{
            width: 2.25rem;
            height: 2.25rem;
            padding: 0;
            border-radius: 8px;
        }}

        /* QR Drawer */
        .qr-drawer {{
            display: none;
            padding: 1rem 0 0.5rem 0;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            border-top: 1px dashed var(--card-border);
            margin-top: 0.75rem;
            animation: fadeIn 0.3s ease;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(-5px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .qr-canvas-wrapper {{
            background: white;
            padding: 0.75rem;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.15);
            margin-bottom: 0.5rem;
        }}

        .qr-canvas-wrapper canvas, .qr-canvas-wrapper img {{
            display: block;
        }}

        .qr-desc {{
            font-size: 0.75rem;
            color: var(--text-muted);
        }}

        /* Node Explorer */
        .search-filter-bar {{
            display: flex;
            gap: 0.75rem;
            margin-bottom: 1.25rem;
        }}

        @media (max-width: 600px) {{
            .search-filter-bar {{
                flex-direction: column;
            }}
        }}

        .search-input-wrapper {{
            position: relative;
            flex-grow: 1;
        }}

        .search-input-wrapper i {{
            position: absolute;
            left: 0.85rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
            font-size: 0.9rem;
        }}

        .search-input {{
            width: 100%;
            background: rgba(0, 0, 0, 0.15);
            border: 1px solid var(--card-border);
            color: var(--text-main);
            padding: 0.6rem 1rem 0.6rem 2.2rem;
            border-radius: 8px;
            font-size: 0.9rem;
            outline: none;
        }}

        .search-input:focus {{
            border-color: var(--primary);
        }}

        .filter-select {{
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            color: var(--text-main);
            padding: 0.6rem 1rem;
            border-radius: 8px;
            font-size: 0.9rem;
            outline: none;
            cursor: pointer;
        }}

        .filter-select:focus {{
            border-color: var(--primary);
        }}

        .node-list-container {{
            max-height: 500px;
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: var(--card-border) transparent;
        }}

        .node-list-container::-webkit-scrollbar {{
            width: 6px;
        }}

        .node-list-container::-webkit-scrollbar-thumb {{
            background: var(--card-border);
            border-radius: 3px;
        }}

        .node-item {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.8rem 1rem;
            background: rgba(255,255,255,0.01);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            margin-bottom: 0.6rem;
        }}

        .node-item:hover {{
            background: rgba(255,255,255,0.03);
            border-color: rgba(59, 130, 246, 0.2);
        }}

        .node-left {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-width: 0; /* allows text truncation */
        }}

        .node-flag {{
            font-size: 1.4rem;
        }}

        .node-details {{
            display: flex;
            flex-direction: column;
            min-width: 0;
        }}

        .node-name {{
            font-weight: 550;
            font-size: 0.9rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 0.15rem;
        }}

        .node-meta {{
            display: flex;
            align-items: center;
            gap: 0.6rem;
            font-size: 0.75rem;
            color: var(--text-muted);
        }}

        .node-type-tag {{
            background: rgba(59, 130, 246, 0.12);
            color: var(--primary);
            padding: 0.1rem 0.4rem;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.7rem;
            text-transform: uppercase;
        }}

        .node-right {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .node-port {{
            font-size: 0.8rem;
            color: var(--text-muted);
            background: rgba(0, 0, 0, 0.15);
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            border: 1px solid var(--card-border);
        }}

        /* Distributions and Charts */
        .dist-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 0.8rem;
            font-size: 0.85rem;
        }}

        .dist-label {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 500;
        }}

        .dist-bar-wrapper {{
            flex-grow: 1;
            margin: 0 1rem;
            background: rgba(255, 255, 255, 0.05);
            height: 6px;
            border-radius: 3px;
            overflow: hidden;
        }}

        .dist-bar {{
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            height: 100%;
            border-radius: 3px;
        }}

        .dist-count {{
            font-weight: 600;
            color: var(--primary);
            min-width: 25px;
            text-align: right;
        }}

        /* Accordion Instructions */
        .accordion {{
            border: 1px solid var(--card-border);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 0.75rem;
        }}

        .accordion-header {{
            background: rgba(255, 255, 255, 0.01);
            padding: 1rem;
            font-weight: 600;
            font-size: 0.95rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
        }}

        .accordion-header:hover {{
            background: rgba(255, 255, 255, 0.03);
        }}

        .accordion-content {{
            display: none;
            padding: 1rem;
            background: rgba(0,0,0,0.1);
            border-top: 1px solid var(--card-border);
            font-size: 0.85rem;
            line-height: 1.6;
            color: var(--text-muted);
        }}

        .accordion-content ol {{
            padding-left: 1.2rem;
        }}

        .accordion-content li {{
            margin-bottom: 0.5rem;
        }}

        .accordion.active .accordion-content {{
            display: block;
        }}

        .accordion.active .accordion-header i {{
            transform: rotate(180deg);
        }}

        .accordion-header i {{
            transition: transform 0.2s ease;
        }}

        /* Toast Alert */
        .toast {{
            position: fixed;
            bottom: 2rem;
            background: #10b981;
            color: white;
            padding: 0.75rem 1.5rem;
            border-radius: 50px;
            box-shadow: 0 10px 25px rgba(16, 185, 129, 0.3);
            font-size: 0.9rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            transform: translateY(100px);
            opacity: 0;
            transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), opacity 0.3s ease;
            z-index: 1000;
        }}

        .toast.show {{
            transform: translateY(0);
            opacity: 1;
        }}

        footer {{
            width: 100%;
            max-width: 1100px;
            text-align: center;
            margin-top: 3rem;
            padding: 1.5rem 0;
            border-top: 1px solid var(--card-border);
            font-size: 0.8rem;
            color: var(--text-muted);
            line-height: 1.6;
        }}

        footer a {{
            color: var(--primary);
            text-decoration: none;
        }}

        footer a:hover {{
            text-decoration: underline;
        }}

        .footer-note {{
            margin-top: 0.5rem;
            color: var(--accent);
        }}
    </style>
</head>
<body>
    <header>
        <div class="brand-container">
            <div class="brand-logo"><i class="fa-solid fa-paper-plane"></i></div>
            <div class="brand-title">wv2ray 订阅中心</div>
        </div>
        <div class="header-controls">
            <div class="status-badge" id="statusBadge">自动更新中</div>
            <button class="theme-btn" id="themeToggle" title="切换主题"><i class="fa-solid fa-moon"></i></button>
        </div>
    </header>

    <main>
        <!-- Left Column -->
        <div class="column-left">
            <!-- Stats -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-val" id="totalNodesStat">0</div>
                    <div class="stat-lbl">可用节点总数</div>
                </div>
                <div class="stat-card">
                    <div class="stat-val" id="clashSizeStat">0 KB</div>
                    <div class="stat-lbl">Clash 文件大小</div>
                </div>
                <div class="stat-card">
                    <div class="stat-val" id="v2raySizeStat">0 KB</div>
                    <div class="stat-lbl">V2ray 文件大小</div>
                </div>
            </div>

            <!-- Subscription URLs -->
            <div class="glass-card">
                <div class="section-title"><i class="fa-solid fa-link"></i> 节点订阅链接</div>
                
                <!-- Clash -->
                <div class="sub-card">
                    <div class="sub-card-header">
                        <div class="sub-name"><i class="fa-solid fa-circle-nodes"></i> Clash 专属订阅</div>
                        <span class="sub-format-badge clash-badge">Clash YAML</span>
                    </div>
                    <div class="url-box">
                        <div class="url-text" id="clashUrlText">https://c1a200.github.io/wv2ray/clash.yaml</div>
                    </div>
                    <div class="action-btns">
                        <button class="btn btn-primary" onclick="copyUrl('clashUrlText')"><i class="fa-solid fa-copy"></i> 复制链接</button>
                        <button class="btn" onclick="toggleQR('clashUrlText', 'clashQR')"><i class="fa-solid fa-qrcode"></i> 二维码</button>
                        <a class="btn" href="clash://install-config?url=https://c1a200.github.io/wv2ray/clash.yaml" title="一键导入 Clash"><i class="fa-solid fa-arrow-down-to-bracket"></i> 导入 Clash</a>
                    </div>
                    <div class="qr-drawer" id="clashQR">
                        <div class="qr-canvas-wrapper" id="clashQRCanvas"></div>
                        <div class="qr-desc">使用手机客户端扫描二维码导入订阅</div>
                    </div>
                </div>

                <!-- V2ray -->
                <div class="sub-card">
                    <div class="sub-card-header">
                        <div class="sub-name"><i class="fa-solid fa-share-nodes"></i> V2ray / 通用订阅</div>
                        <span class="sub-format-badge v2ray-badge">Base64</span>
                    </div>
                    <div class="url-box">
                        <div class="url-text" id="v2rayUrlText">https://c1a200.github.io/wv2ray/subscribe.txt</div>
                    </div>
                    <div class="action-btns">
                        <button class="btn btn-primary" onclick="copyUrl('v2rayUrlText')"><i class="fa-solid fa-copy"></i> 复制链接</button>
                        <button class="btn" onclick="toggleQR('v2rayUrlText', 'v2rayQR')"><i class="fa-solid fa-qrcode"></i> 二维码</button>
                        <a class="btn" href="shadowrocket://add/sub://aHR0cHM6Ly9jMWEyMDAuZ2l0aHViLmlvL3d2MnJheS9zdWJzY3JpYmUudHh0" title="一键导入 Shadowrocket"><i class="fa-solid fa-arrow-down-to-bracket"></i> 导入 小火箭</a>
                    </div>
                    <div class="qr-drawer" id="v2rayQR">
                        <div class="qr-canvas-wrapper" id="v2rayQRCanvas"></div>
                        <div class="qr-desc">使用手机客户端扫描二维码导入订阅</div>
                    </div>
                </div>

                <!-- V2ray Issue Variant -->
                <div class="sub-card" id="issueV2rayCard" style="display:none;">
                    <div class="sub-card-header">
                        <div class="sub-name"><i class="fa-solid fa-code-fork"></i> V2ray 对照订阅 (Issue #91)</div>
                        <span class="sub-format-badge v2ray-badge">Base64</span>
                    </div>
                    <div class="url-box">
                        <div class="url-text" id="v2rayIssueUrlText">https://c1a200.github.io/wv2ray/subscribe1.txt</div>
                    </div>
                    <div class="action-btns">
                        <button class="btn btn-primary" onclick="copyUrl('v2rayIssueUrlText')"><i class="fa-solid fa-copy"></i> 复制</button>
                        <button class="btn" onclick="toggleQR('v2rayIssueUrlText', 'v2rayIssueQR')"><i class="fa-solid fa-qrcode"></i></button>
                        <a class="btn" href="shadowrocket://add/sub://aHR0cHM6Ly9jMWEyMDAuZ2l0aHViLmlvL3d2MnJheS9zdWJzY3JpYmUxLnR4dA=="><i class="fa-solid fa-arrow-down-to-bracket"></i> 导入</a>
                    </div>
                    <div class="qr-drawer" id="v2rayIssueQR">
                        <div class="qr-canvas-wrapper" id="v2rayIssueQRCanvas"></div>
                        <div class="qr-desc">扫描二维码导入对照订阅</div>
                    </div>
                </div>

                <!-- Clash Issue Variant -->
                <div class="sub-card" id="issueClashCard" style="display:none;">
                    <div class="sub-card-header">
                        <div class="sub-name"><i class="fa-solid fa-code-fork"></i> Clash 对照订阅 (Issue #91)</div>
                        <span class="sub-format-badge clash-badge">Clash YAML</span>
                    </div>
                    <div class="url-box">
                        <div class="url-text" id="clashIssueUrlText">https://c1a200.github.io/wv2ray/clash1.yaml</div>
                    </div>
                    <div class="action-btns">
                        <button class="btn btn-primary" onclick="copyUrl('clashIssueUrlText')"><i class="fa-solid fa-copy"></i> 复制</button>
                        <button class="btn" onclick="toggleQR('clashIssueUrlText', 'clashIssueQR')"><i class="fa-solid fa-qrcode"></i></button>
                        <a class="btn" href="clash://install-config?url=https://c1a200.github.io/wv2ray/clash1.yaml"><i class="fa-solid fa-arrow-down-to-bracket"></i> 导入</a>
                    </div>
                    <div class="qr-drawer" id="clashIssueQR">
                        <div class="qr-canvas-wrapper" id="clashIssueQRCanvas"></div>
                        <div class="qr-desc">扫描二维码导入对照订阅</div>
                    </div>
                </div>
            </div>

            <!-- Node Explorer -->
            <div class="glass-card">
                <div class="section-title"><i class="fa-solid fa-magnifying-glass-chart"></i> 节点在线预览</div>
                <div class="search-filter-bar">
                    <div class="search-input-wrapper">
                        <i class="fa-solid fa-magnifying-glass"></i>
                        <input type="text" class="search-input" id="nodeSearch" placeholder="搜索节点名称或地址...">
                    </div>
                    <select class="filter-select" id="regionFilter">
                        <option value="ALL">全部地区</option>
                    </select>
                    <select class="filter-select" id="typeFilter">
                        <option value="ALL">全部协议</option>
                    </select>
                </div>
                <div class="node-list-container" id="nodeList">
                    <!-- Nodes populated dynamically -->
                    <div style="text-align:center; padding: 2rem; color: var(--text-muted);">暂无可用节点数据</div>
                </div>
            </div>
        </div>

        <!-- Right Column -->
        <div class="column-right">
            <!-- Region Stats -->
            <div class="glass-card">
                <div class="section-title"><i class="fa-solid fa-earth-asia"></i> 节点地区分布</div>
                <div id="regionDistContainer">
                    <!-- Regions populated dynamically -->
                    <div style="color:var(--text-muted); font-size: 0.85rem; text-align:center;">暂无分布数据</div>
                </div>
            </div>

            <!-- Type Stats -->
            <div class="glass-card">
                <div class="section-title"><i class="fa-solid fa-sliders"></i> 节点协议分布</div>
                <div id="typeDistContainer">
                    <!-- Types populated dynamically -->
                    <div style="color:var(--text-muted); font-size: 0.85rem; text-align:center;">暂无分布数据</div>
                </div>
            </div>

            <!-- Help & Manuals -->
            <div class="glass-card">
                <div class="section-title"><i class="fa-solid fa-circle-question"></i> 客户端使用指南</div>
                
                <div class="accordion">
                    <div class="accordion-header" onclick="toggleAccordion(this)">
                        <span>Clash / FlClash 客户端配置</span>
                        <i class="fa-solid fa-chevron-down"></i>
                    </div>
                    <div class="accordion-content">
                        <ol>
                            <li>复制 <b>Clash 专属订阅</b> 链接；</li>
                            <li>打开 Clash / FlClash，进入「配置」或「Profiles」界面；</li>
                            <li>粘贴复制好的链接到输入框，点击「下载」或「Import」导入；</li>
                            <li>导入完成后选中该配置文件，在「代理/Proxies」中挑选延迟较低的节点使用。</li>
                        </ol>
                    </div>
                </div>

                <div class="accordion">
                    <div class="accordion-header" onclick="toggleAccordion(this)">
                        <span>v2rayN (Windows) 客户端配置</span>
                        <i class="fa-solid fa-chevron-down"></i>
                    </div>
                    <div class="accordion-content">
                        <ol>
                            <li>复制上面的 <b>V2ray / 通用订阅</b> 链接；</li>
                            <li>打开 v2rayN，在顶部菜单选择「订阅管理」->「添加」；</li>
                            <li>在「地址(url)」栏粘贴链接，并点击「保存」；</li>
                            <li>保存后返回主界面，点击顶部「订阅」->「更新订阅」，等待节点导入完成即可使用。</li>
                        </ol>
                    </div>
                </div>

                <div class="accordion">
                    <div class="accordion-header" onclick="toggleAccordion(this)">
                        <span>Shadowrocket (iOS 小火箭) 配置</span>
                        <i class="fa-solid fa-chevron-down"></i>
                    </div>
                    <div class="accordion-content">
                        <ol>
                            <li>在 iPhone 浏览器上直接点击 <b>导入 小火箭</b> 一键导入；</li>
                            <li>或者复制 <b>V2ray / 通用订阅</b> 地址或生成其二维码；</li>
                            <li>在小火箭中点击右上角「+」，类型选择「Subscribe」，粘贴链接保存，或者点击左上角扫描二维码导入。</li>
                        </ol>
                    </div>
                </div>
            </div>

            <!-- Token Management -->
            <div class="glass-card">
                <div class="section-title"><i class="fa-solid fa-key"></i> 快捷更新 Token</div>
                <div style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1rem; line-height: 1.5;">
                    如果您从 Telegram 获取了新 Token，可以直接在此输入并保存。这会自动更新 GitHub 变量并触发自动同步任务。
                </div>
                
                <div style="margin-bottom: 0.75rem;">
                    <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 0.3rem;">GitHub 个人访问令牌 (PAT)</label>
                    <input type="password" id="githubPat" class="search-input" style="padding-left: 1rem;" placeholder="ghp_xxxxxxxxxxxx">
                    <span style="font-size: 0.7rem; color: var(--text-muted); display: block; margin-top: 0.2rem; line-height: 1.4;">
                        需要 <code>repo</code> 权限。保存在您本地浏览器中。
                        <a href="https://github.com/settings/tokens/new?scopes=repo" target="_blank" style="color: var(--primary); text-decoration: none;">点击去创建 PAT</a>
                    </span>
                </div>
                
                <div style="margin-bottom: 1.25rem;">
                    <label style="font-size: 0.8rem; color: var(--text-muted); display: block; margin-bottom: 0.3rem;">最新上游 Token</label>
                    <input type="text" id="newToken" class="search-input" style="padding-left: 1rem;" placeholder="输入新 Token...">
                </div>
                
                <button class="btn btn-primary" style="width: 100%; display: flex; align-items: center; justify-content: center; gap: 0.5rem;" id="updateTokenBtn">
                    <i class="fa-solid fa-rotate"></i> 更新 Token 并同步
                </button>
            </div>
        </div>
    </main>

    <footer>
        <p>© 2026 wv2ray 自动订阅服务。页面基于 GitHub Pages 驱动。</p>
        <p class="footer-note">声明：本项目所有数据均来自网络公开共享资源，仅供学习、测试和科学研究使用。请在遵守当地法律法规的前提下使用。</p>
    </footer>

    <div class="toast" id="toast">
        <i class="fa-solid fa-circle-check"></i>
        <span id="toastMsg">链接复制成功！</span>
    </div>

    <script>
        // Embed the Python-generated summary directly into the page
        const subData = {summary_json_str};

        // DOM Elements
        const themeToggle = document.getElementById('themeToggle');
        const statusBadge = document.getElementById('statusBadge');
        const totalNodesStat = document.getElementById('totalNodesStat');
        const clashSizeStat = document.getElementById('clashSizeStat');
        const v2raySizeStat = document.getElementById('v2raySizeStat');
        
        const regionFilter = document.getElementById('regionFilter');
        const typeFilter = document.getElementById('typeFilter');
        const nodeSearch = document.getElementById('nodeSearch');
        const nodeList = document.getElementById('nodeList');
        
        const regionDistContainer = document.getElementById('regionDistContainer');
        const typeDistContainer = document.getElementById('typeDistContainer');
        
        const issueV2rayCard = document.getElementById('issueV2rayCard');
        const issueClashCard = document.getElementById('issueClashCard');
        const toast = document.getElementById('toast');
        const toastMsg = document.getElementById('toastMsg');

        // Theme management
        if (localStorage.getItem('theme') === 'light') {{
            document.body.classList.add('light-mode');
            themeToggle.innerHTML = '<i class="fa-solid fa-sun"></i>';
        }}
        
        themeToggle.addEventListener('click', () => {{
            document.body.classList.toggle('light-mode');
            const isLight = document.body.classList.contains('light-mode');
            localStorage.setItem('theme', isLight ? 'light' : 'dark');
            themeToggle.innerHTML = isLight ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
        }});

        // Dynamic Relative Time Formatter
        function formatRelativeTime(isoString) {{
            if (!isoString) return '未知时间';
            const past = new Date(isoString);
            const now = new Date();
            const diffMs = now - past;
            const diffMins = Math.floor(diffMs / 60000);
            
            if (diffMins < 1) return '刚刚';
            if (diffMins < 60) return `${{diffMins}} 分钟前`;
            const diffHours = Math.floor(diffMins / 60);
            if (diffHours < 24) return `${{diffHours}} 小时前`;
            const diffDays = Math.floor(diffHours / 24);
            return `${{diffDays}} 天前`;
        }}

        // Initialize UI with data
        function initDashboard() {{
            if (!subData) return;
            
            // Set update status
            const updatedAtStr = formatRelativeTime(subData.updated_at);
            statusBadge.innerText = `同步于 ${{updatedAtStr}}`;
            
            // Set stats
            const totalNodes = subData.clash_nodes_count || (subData.clash_nodes_list ? subData.clash_nodes_list.length : 0);
            totalNodesStat.innerText = totalNodes;
            clashSizeStat.innerText = subData.clash_size_kb ? `${{subData.clash_size_kb}} KB` : '未知';
            v2raySizeStat.innerText = subData.v2ray_size_kb ? `${{subData.v2ray_size_kb}} KB` : '未知';
            
            // Show issue variants cards if available
            if (subData.issue_variant_status === 'ok') {{
                issueV2rayCard.style.display = 'block';
                issueClashCard.style.display = 'block';
            }}

            const nodes = subData.clash_nodes_list || [];
            
            // Setup filters
            const regions = new Set();
            const types = new Set();
            
            nodes.forEach(node => {{
                if (node.country_code) regions.add(node.country_code);
                if (node.type) types.add(node.type.toUpperCase());
            }});

            // Pop region select options
            const regionNames = {{}};
            nodes.forEach(node => {{
                if (node.country_code && node.country_name) {{
                    regionNames[node.country_code] = `${{node.flag || ''}} ${{node.country_name}}`;
                }}
            }});
            
            [...regions].sort().forEach(code => {{
                const opt = document.createElement('option');
                opt.value = code;
                opt.innerText = regionNames[code] || code;
                regionFilter.appendChild(opt);
            }});

            // Pop type select options
            [...types].sort().forEach(t => {{
                const opt = document.createElement('option');
                opt.value = t;
                opt.innerText = t;
                typeFilter.appendChild(opt);
            }});

            // Render Node List
            renderNodes(nodes);
            
            // Render Stats Dist
            renderRegionStats(nodes);
            renderTypeStats(nodes);

            // Setup Event listeners for filtering
            nodeSearch.addEventListener('input', filterAndRender);
            regionFilter.addEventListener('change', filterAndRender);
            typeFilter.addEventListener('change', filterAndRender);
        }}

        function filterAndRender() {{
            const query = nodeSearch.value.toLowerCase().trim();
            const regSel = regionFilter.value;
            const typeSel = typeFilter.value;
            const nodes = subData.clash_nodes_list || [];

            const filtered = nodes.filter(node => {{
                const matchQuery = node.name.toLowerCase().includes(query) || node.server.toLowerCase().includes(query);
                const matchRegion = regSel === 'ALL' || node.country_code === regSel;
                const matchType = typeSel === 'ALL' || (node.type && node.type.toUpperCase() === typeSel);
                return matchQuery && matchRegion && matchType;
            }});

            renderNodes(filtered);
        }}

        function renderNodes(nodes) {{
            nodeList.innerHTML = '';
            
            if (nodes.length === 0) {{
                nodeList.innerHTML = '<div style="text-align:center; padding: 3rem; color: var(--text-muted); font-size: 0.9rem;">未找到符合过滤条件的节点</div>';
                return;
            }}
            
            nodes.forEach(node => {{
                const item = document.createElement('div');
                item.className = 'node-item';
                
                item.innerHTML = `
                    <div class="node-left">
                        <span class="node-flag">${{node.flag || '🌐'}}</span>
                        <div class="node-details">
                            <span class="node-name" title="${{node.name}}">${{node.name}}</span>
                            <div class="node-meta">
                                <span class="node-type-tag">${{node.type || 'UNKNOWN'}}</span>
                                <span class="node-server">${{node.server || '***'}}</span>
                            </div>
                        </div>
                    </div>
                    <div class="node-right">
                        <span class="node-port">:${{node.port || '0'}}</span>
                    </div>
                `;
                nodeList.appendChild(item);
            }});
        }}

        function renderRegionStats(nodes) {{
            regionDistContainer.innerHTML = '';
            
            const stats = {{}};
            nodes.forEach(n => {{
                const code = n.country_code || 'OTHERS';
                if (!stats[code]) {{
                    stats[code] = {{
                        flag: n.flag || '🌐',
                        name: n.country_name || '其它地区',
                        count: 0
                    }};
                }}
                stats[code].count++;
            }});

            const sorted = Object.entries(stats).sort((a, b) => b[1].count - a[1].count);
            const maxCount = sorted.length > 0 ? sorted[0][1].count : 1;

            sorted.forEach(([code, data]) => {{
                const pct = (data.count / maxCount) * 100;
                const distRow = document.createElement('div');
                distRow.className = 'dist-row';
                distRow.innerHTML = `
                    <div class="dist-label"><span>${{data.flag}}</span> <span>${{data.name}}</span></div>
                    <div class="dist-bar-wrapper">
                        <div class="dist-bar" style="width: ${{pct}}%"></div>
                    </div>
                    <div class="dist-count">${{data.count}}</div>
                `;
                regionDistContainer.appendChild(distRow);
            }});
            
            if (sorted.length === 0) {{
                regionDistContainer.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; text-align:center;">暂无分布数据</div>';
            }}
        }}

        function renderTypeStats(nodes) {{
            typeDistContainer.innerHTML = '';
            
            const stats = {{}};
            nodes.forEach(n => {{
                const t = (n.type || 'UNKNOWN').toUpperCase();
                stats[t] = (stats[t] || 0) + 1;
            }});

            const sorted = Object.entries(stats).sort((a, b) => b - a);
            const maxCount = sorted.length > 0 ? sorted[0][1] : 1;

            sorted.forEach(([type, count]) => {{
                const pct = (count / maxCount) * 100;
                const distRow = document.createElement('div');
                distRow.className = 'dist-row';
                distRow.innerHTML = `
                    <div class="dist-label"><span>${{type}}</span></div>
                    <div class="dist-bar-wrapper">
                        <div class="dist-bar" style="width: ${{pct}}%; background: linear-gradient(90deg, var(--secondary), var(--primary));"></div>
                    </div>
                    <div class="dist-count">${{count}}</div>
                `;
                typeDistContainer.appendChild(distRow);
            }});
            
            if (sorted.length === 0) {{
                typeDistContainer.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; text-align:center;">暂无分布数据</div>';
            }}
        }}

        // Copy functionality
        function copyUrl(elementId) {{
            const urlText = document.getElementById(elementId).innerText;
            navigator.clipboard.writeText(urlText).then(() => {{
                showToast('订阅链接已复制到剪贴板！');
            }}).catch(err => {{
                const input = document.createElement('input');
                input.value = urlText;
                document.body.appendChild(input);
                input.select();
                document.execCommand('copy');
                document.body.removeChild(input);
                showToast('订阅链接已复制到剪贴板！');
            }});
        }}

        function showToast(msg) {{
            toastMsg.innerText = msg;
            toast.classList.add('show');
            setTimeout(() => {{
                toast.classList.remove('show');
            }}, 2500);
        }}

        // QR Code toggle
        const qrInstances = {{}};
        function toggleQR(elementId, qrId) {{
            const drawer = document.getElementById(qrId);
            const canvasWrapper = document.getElementById(qrId + 'Canvas');
            const isVisible = window.getComputedStyle(drawer).display !== 'none';
            
            document.querySelectorAll('.qr-drawer').forEach(d => d.style.display = 'none');
            
            if (!isVisible) {{
                drawer.style.display = 'flex';
                const url = document.getElementById(elementId).innerText;
                
                if (!qrInstances[qrId]) {{
                    canvasWrapper.innerHTML = '';
                    qrInstances[qrId] = new QRCode(canvasWrapper, {{
                        text: url,
                        width: 180,
                        height: 180,
                        colorDark : "#0b0f19",
                        colorLight : "#ffffff",
                        correctLevel : QRCode.CorrectLevel.M
                    }});
                }}
            }}
        }}

        // Accordion toggle
        function toggleAccordion(element) {{
            const card = element.parentElement;
            card.classList.toggle('active');
        }}

        // Setup Token Update handler
        const savedPat = localStorage.getItem('github_pat') || '';
        if (savedPat) {{
            document.getElementById('githubPat').value = savedPat;
        }}

        document.getElementById('updateTokenBtn').addEventListener('click', async () => {{
            const pat = document.getElementById('githubPat').value.trim();
            const tokenVal = document.getElementById('newToken').value.trim();
            const btn = document.getElementById('updateTokenBtn');
            
            if (!pat) {{
                showToast('请输入 GitHub PAT 令牌！');
                return;
            }}
            if (!tokenVal) {{
                showToast('请输入新的 Token 值！');
                return;
            }}
            
            localStorage.setItem('github_pat', pat);
            
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 正在更新...';
            
            try {{
                const githubUrl = subData.github_pages_v2ray || '';
                const match = githubUrl.match(/https:\/\/([^.]+)\.github\.io\/([^/]+)/);
                const owner = match ? match[1] : 'c1a200';
                const repo = match ? match[2] : 'wv2ray';
                
                // 1. Update Repository Variable
                const varUrl = `https://api.github.com/repos/${{owner}}/${{repo}}/actions/variables/DIRECT_TOKEN`;
                const varResp = await fetch(varUrl, {{
                    method: 'PATCH',
                    headers: {{
                        'Accept': 'application/vnd.github+json',
                        'Authorization': `Bearer ${{pat}}`,
                        'X-GitHub-Api-Version': '2022-11-28',
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{ name: 'DIRECT_TOKEN', value: tokenVal }})
                }});
                
                if (!varResp.ok) {{
                    const errInfo = await varResp.text();
                    throw new Error(`更新变量失败: ${{varResp.status}} ${{errInfo}}`);
                }}
                
                // 2. Trigger Workflow Dispatch
                const dispatchUrl = `https://api.github.com/repos/${{owner}}/${{repo}}/actions/workflows/update-subscription.yml/dispatches`;
                const dispatchResp = await fetch(dispatchUrl, {{
                    method: 'POST',
                    headers: {{
                        'Accept': 'application/vnd.github+json',
                        'Authorization': `Bearer ${{pat}}`,
                        'X-GitHub-Api-Version': '2022-11-28',
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{ ref: 'main' }})
                }});
                
                if (!dispatchResp.ok) {{
                    const errInfo = await dispatchResp.text();
                    throw new Error(`触发工作流失败: ${{dispatchResp.status}} ${{errInfo}}`);
                }}
                
                showToast('Token 更新成功！自动同步已启动，请等待几分钟。');
                document.getElementById('newToken').value = '';
            }} catch (err) {{
                console.error(err);
                showToast(`操作失败: ${{err.message}}`);
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-rotate"></i> 更新 Token 并同步';
            }}
        }});

        // Init on page load
        window.addEventListener('DOMContentLoaded', initDashboard);
    </script>
</body>
</html>
"""
    html_file = output_path / 'index.html'
    html_file.write_text(html_content, encoding='utf-8')
    print(f"✓ HTML 仪表盘文件已保存: {html_file}")


def _fetch_issue_variant() -> dict:
    """从 Issue #91 获取 v2ray/clash 内容，返回用于 subscribe1/clash1 的数据。"""
    from fetcher import AggregatorFetcher

    fetcher = AggregatorFetcher()
    print('📥 正在从 GitHub Issue 获取 subscribe1/clash1 数据...')
    info = fetcher.get_subscription_info()

    v2ray_url = fetcher.build_subscribe_url(
        token=info['token'],
        api_url=info['api_url'],
        target='v2ray',
    )
    clash_url = fetcher.build_subscribe_url(
        token=info['token'],
        api_url=info['api_url'],
        target='clash',
    )

    print('📥 正在直接获取 subscribe1 (issue/v2ray) 内容...')
    v2ray_content = _fetch_direct_content(v2ray_url)

    print('📥 正在直接获取 clash1 (issue/clash) 内容...')
    clash_content = _fetch_direct_content(clash_url)

    return {
        'token': info['token'],
        'api_url': info['api_url'],
        'fetched_at': info['fetched_at'],
        'v2ray_url': v2ray_url,
        'clash_url': clash_url,
        'v2ray_content': v2ray_content,
        'clash_content': clash_content,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def save_subscription_files(output_dir: str = '.'):
    """获取并保存订阅文件（v2ray 与 clash）"""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        direct_token = os.getenv('DIRECT_TOKEN', '').strip()
        v2ray_url = (
            os.getenv('DIRECT_V2RAY_URL') or DEFAULT_DIRECT_V2RAY_URL
        ).strip()
        clash_url = (
            os.getenv('DIRECT_CLASH_URL') or DEFAULT_DIRECT_CLASH_URL
        ).strip()

        if direct_token:
            v2ray_url = _apply_token_to_url(v2ray_url, direct_token)
            clash_url = _apply_token_to_url(clash_url, direct_token)

        fetched_at = datetime.utcnow().isoformat() + 'Z'

        print(f'✓ v2ray 源地址: {v2ray_url}')
        print(f'✓ clash 源地址: {clash_url}')

        # 初始化内容变量，用于跟踪获取状态
        v2ray_content = None
        clash_content = None
        failed_sources = []

        # --- v2ray: 直接保存 ---
        try:
            print('📥 正在直接抓取 v2ray 订阅内容...')
            v2ray_content = _fetch_direct_content(v2ray_url)
            _validate_content(v2ray_content, is_clash=False)

            v2_file = output_path / 'subscribe.txt'
            v2_file.write_text(v2ray_content, encoding='utf-8')
            print(f"✓ v2ray 订阅文件已保存: {v2_file}")
        except Exception as v2ray_err:
            failed_sources.append(('v2ray', str(v2ray_err)))
            print(f"⚠️ v2ray 订阅获取失败: {v2ray_err}")
            print("   → 保留上次有效的 subscribe.txt 文件")

        # --- clash: 去重 + short-id 修复 + GeoIP（可选）---
        try:
            print('📥 正在直接抓取 clash 订阅内容...')
            clash_content = _fetch_direct_content(clash_url)
            _validate_content(clash_content, is_clash=True)

            clash_final = _dedup_proxies(clash_content)

            # GeoIP 验证并纠正节点名称（默认禁用，ENABLE_GEOIP=true 启用）
            if _env_to_bool(os.getenv('ENABLE_GEOIP'), default=False):
                try:
                    from geoip_verify import verify_and_fix_proxies as _geoip_fix
                    _geoip_data = yaml.safe_load(clash_final)
                    if isinstance(_geoip_data, dict) and _geoip_data.get('proxies'):
                        _geoip_data['proxies'] = _geoip_fix(_geoip_data['proxies'])
                        clash_final = yaml.dump(
                            _geoip_data, allow_unicode=True,
                            default_flow_style=False, sort_keys=False, width=1000,
                        )
                except Exception as geoip_err:
                    print(f"⚠️ GeoIP 纠正跳过: {geoip_err}")

            # 修复纯数字 short-id 引号问题
            clash_final = _fix_short_id_quotes(clash_final)

            clash_file = output_path / 'clash.yaml'
            clash_file.write_text(clash_final, encoding='utf-8')
            print(f"✓ clash 订阅文件已保存: {clash_file}")
        except Exception as clash_err:
            failed_sources.append(('clash', str(clash_err)))
            print(f"⚠️ clash 订阅获取失败: {clash_err}")
            print("   → 保留上次有效的 clash.yaml 文件")

        # --- 上游失败醒目提示 ---
        if failed_sources:
            print("\n" + "=" * 60)
            print("⚠️  警告: 部分上游订阅获取失败！")
            print("=" * 60)
            for source_name, error_msg in failed_sources:
                print(f"  ✗ {source_name}: {error_msg}")
            print("-" * 60)
            print("  已保留上次有效文件，用户仍可使用旧节点。")
            print("  可能原因: token过期、网络问题、上游服务不可用")
            print("=" * 60 + "\n")

        # --- Issue 变体: subscribe1.txt / clash1.yaml（可选）---
        issue_variant_enabled = _env_to_bool(
            os.getenv('GENERATE_ISSUE_VARIANTS'),
            default=True,
        )
        issue_variant_status = 'disabled'
        issue_variant = None

        if issue_variant_enabled:
            try:
                issue_variant = _fetch_issue_variant()

                # subscribe1.txt
                v2_file_issue = output_path / 'subscribe1.txt'
                v2_file_issue.write_text(
                    issue_variant['v2ray_content'], encoding='utf-8'
                )
                print(f"✓ issue v2ray 订阅文件已保存: {v2_file_issue}")

                # clash1.yaml
                clash_issue_final = _dedup_proxies(
                    issue_variant['clash_content']
                )
                clash_issue_final = _fix_short_id_quotes(clash_issue_final)

                clash_file_issue = output_path / 'clash1.yaml'
                clash_file_issue.write_text(
                    clash_issue_final, encoding='utf-8'
                )
                print(f"✓ issue clash 订阅文件已保存: {clash_file_issue}")
                issue_variant_status = 'ok'
            except Exception as issue_err:
                issue_variant_status = f'failed: {issue_err}'
                print(f"⚠️ issue 增量产物生成失败，已跳过: {issue_err}")

        # --- 保存元数据 ---
        metadata = {
            'source_mode': 'direct',
            'v2ray_subscribe_url': v2ray_url,
            'clash_subscribe_url': clash_url,
            'issue_variant_enabled': issue_variant_enabled,
            'issue_variant_status': issue_variant_status,
            'issue_token': issue_variant['token'] if issue_variant else None,
            'issue_api_url': (
                issue_variant['api_url'] if issue_variant else None
            ),
            'v2ray_subscribe_url_issue': (
                issue_variant['v2ray_url'] if issue_variant else None
            ),
            'clash_subscribe_url_issue': (
                issue_variant['clash_url'] if issue_variant else None
            ),
            'fetched_at': fetched_at,
            'v2ray_subscription_file': 'subscribe.txt',
            'clash_subscription_file': 'clash.yaml',
            'v2ray_subscription_file_issue': 'subscribe1.txt',
            'clash_subscription_file_issue': 'clash1.yaml',
            'github_pages_v2ray': (
                'https://c1a200.github.io/wv2ray/subscribe.txt'
            ),
            'github_pages_clash': 'https://c1a200.github.io/wv2ray/clash.yaml',
            'github_pages_v2ray_issue': (
                'https://c1a200.github.io/wv2ray/subscribe1.txt'
            ),
            'github_pages_clash_issue': (
                'https://c1a200.github.io/wv2ray/clash1.yaml'
            ),
        }

        metadata_file = output_path / 'metadata.json'
        metadata_file.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        print(f"✓ 元数据文件已保存: {metadata_file}")

        # --- 计算统计与提取节点信息 ---
        v2ray_nodes_count = 0
        v2ray_final_content = v2ray_content
        if not v2ray_final_content:
            v2_file = output_path / 'subscribe.txt'
            if v2_file.exists():
                try:
                    v2ray_final_content = v2_file.read_text(encoding='utf-8')
                except Exception:
                    pass
        if v2ray_final_content:
            v2ray_nodes_count = _get_v2ray_node_count(v2ray_final_content)

        clash_nodes_count = 0
        clash_node_types = {}
        clash_node_regions = {}
        clash_nodes_list = []
        clash_final_content = clash_content
        if not clash_final_content:
            clash_file = output_path / 'clash.yaml'
            if clash_file.exists():
                try:
                    clash_final_content = clash_file.read_text(encoding='utf-8')
                except Exception:
                    pass

        if clash_final_content:
            try:
                clash_data = yaml.safe_load(clash_final_content)
                if isinstance(clash_data, dict) and 'proxies' in clash_data:
                    proxies = clash_data['proxies'] or []
                    clash_nodes_count = len(proxies)
                    for proxy in proxies:
                        if not isinstance(proxy, dict):
                            continue
                        node_info = _get_node_info(proxy)
                        clash_nodes_list.append(node_info)
                        
                        ptype = node_info['type'].upper()
                        clash_node_types[ptype] = clash_node_types.get(ptype, 0) + 1
                        
                        region_code = node_info['country_code']
                        if region_code not in clash_node_regions:
                            clash_node_regions[region_code] = {
                                'flag': node_info['flag'],
                                'name': node_info['country_name'],
                                'count': 0
                            }
                        clash_node_regions[region_code]['count'] += 1
            except Exception as e:
                print(f"⚠️ 解析 Clash 统计信息失败: {e}")

        v2ray_nodes_count_issue = 0
        if issue_variant and issue_variant.get('v2ray_content'):
            v2ray_nodes_count_issue = _get_v2ray_node_count(issue_variant['v2ray_content'])

        clash_nodes_count_issue = 0
        if issue_variant and issue_variant.get('clash_content'):
            try:
                clash_issue_data = yaml.safe_load(issue_variant['clash_content'])
                if isinstance(clash_issue_data, dict) and 'proxies' in clash_issue_data:
                    clash_nodes_count_issue = len(clash_issue_data['proxies'] or [])
            except Exception:
                pass

        # --- 保存摘要 ---
        summary = {
            'updated_at': fetched_at,
            'v2ray_subscription_url': (
                'https://c1a200.github.io/wv2ray/subscribe.txt'
            ),
            'clash_subscription_url': (
                'https://c1a200.github.io/wv2ray/clash.yaml'
            ),
            'v2ray_subscription_url_issue': (
                'https://c1a200.github.io/wv2ray/subscribe1.txt'
            ),
            'clash_subscription_url_issue': (
                'https://c1a200.github.io/wv2ray/clash1.yaml'
            ),
            'v2ray_size_kb': (
                round(len(v2ray_content) / 1024, 2)
                if v2ray_content else (round(len(v2ray_final_content) / 1024, 2) if v2ray_final_content else None)
            ),
            'clash_size_kb': (
                round(len(clash_content) / 1024, 2)
                if clash_content else (round(len(clash_final_content) / 1024, 2) if clash_final_content else None)
            ),
            'v2ray_size_kb_issue': (
                round(len(issue_variant['v2ray_content']) / 1024, 2)
                if issue_variant else None
            ),
            'clash_size_kb_issue': (
                round(len(issue_variant['clash_content']) / 1024, 2)
                if issue_variant else None
            ),
            'v2ray_nodes_count': v2ray_nodes_count,
            'clash_nodes_count': clash_nodes_count,
            'v2ray_nodes_count_issue': v2ray_nodes_count_issue,
            'clash_nodes_count_issue': clash_nodes_count_issue,
            'clash_node_types': clash_node_types,
            'clash_node_regions': clash_node_regions,
            'clash_nodes_list': clash_nodes_list,
            'format': 'v2ray (upstream original) + clash (yaml)',
            'source_mode': 'direct',
            'issue_variant_status': issue_variant_status,
            'instructions': [
                '1. 在 v2ray 客户端中添加远程订阅',
                '2. 订阅地址: https://c1a200.github.io/wv2ray/subscribe.txt',
                (
                    '3. 在 clash/Clash Meta 中添加远程订阅: '
                    'https://c1a200.github.io/wv2ray/clash.yaml'
                ),
                (
                    '4. Issue 对照订阅: '
                    'https://c1a200.github.io/wv2ray/subscribe1.txt '
                    '与 https://c1a200.github.io/wv2ray/clash1.yaml'
                ),
                '5. 订阅每天自动更新（北京时间每天下午3点）',
            ],
        }

        summary_file = output_path / 'summary.json'
        summary_file.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        print(f"✓ 摘要文件已保存: {summary_file}")

        # --- 生成 HTML 仪表盘 ---
        try:
            _generate_dashboard_html(output_path, summary, metadata)
        except Exception as html_err:
            print(f"⚠️ 生成 HTML 仪表盘失败: {html_err}")

        print("\n✅ 所有文件生成成功！")
        print("📌 固定订阅链接: https://c1a200.github.io/wv2ray/subscribe.txt")

        return True

    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


if __name__ == '__main__':
    # 优先输出到 docs 目录（GitHub Pages），其次为当前目录
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # 检查是否在 GitHub Actions 中运行
    if os.path.exists(os.path.join(script_dir, '..', 'docs')):
        output_dir = os.path.join(script_dir, '..', 'docs')
    else:
        output_dir = script_dir

    success = save_subscription_files(output_dir)
    sys.exit(0 if success else 1)
