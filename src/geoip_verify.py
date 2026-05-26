#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GeoIP 节点名称纠正模块

使用 GeoLite2 Country 数据库验证节点实际归属地，纠正错误标记。
"""

import os
import socket
import re
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timedelta

import requests

# GeoLite2 数据库下载地址（GitHub 镜像，免注册）
GEOIP_DB_URL = 'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb'
GEOIP_DB_CACHE_DIR = os.path.join(tempfile.gettempdir(), 'geoip_cache')
GEOIP_DB_PATH = os.path.join(GEOIP_DB_CACHE_DIR, 'GeoLite2-Country.mmdb')
GEOIP_CACHE_DAYS = 7

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
    'UA': ('🇺🇦', '乌克兰'),
    'CZ': ('🇨🇿', '捷克'),
    'RO': ('🇷🇴', '罗马尼亚'),
    'BG': ('🇧🇬', '保加利亚'),
    'HU': ('🇭🇺', '匈牙利'),
    'LT': ('🇱🇹', '立陶宛'),
    'LV': ('🇱🇻', '拉脱维亚'),
    'EE': ('🇪🇪', '爱沙尼亚'),
    'HR': ('🇭🇷', '克罗地亚'),
    'AZ': ('🇦🇿', '阿塞拜疆'),
    'AR': ('🇦🇷', '阿根廷'),
    'CL': ('🇨🇱', '智利'),
    'CO': ('🇨🇴', '哥伦比亚'),
    'MX': ('🇲🇽', '墨西哥'),
    'ZA': ('🇿🇦', '南非'),
    'IL': ('🇮🇱', '以色列'),
    'AE': ('🇦🇪', '阿联酋'),
    'SA': ('🇸🇦', '沙特'),
}

# 从节点名提取国家的正则模式
NAME_COUNTRY_PATTERNS = [
    (r'香港|HK|Hong\s*Kong', 'HK'),
    (r'台湾|TW|Taiwan', 'TW'),
    (r'日本|JP|Japan', 'JP'),
    (r'新加坡|狮城|SG|Singapore', 'SG'),
    (r'美国|US|United\s*States', 'US'),
    (r'韩国|KR|Korea', 'KR'),
    (r'英国|GB|UK|United\s*Kingdom', 'GB'),
    (r'德国|DE|Germany', 'DE'),
    (r'法国|FR|France', 'FR'),
    (r'荷兰|NL|Netherlands', 'NL'),
    (r'加拿大|CA|Canada', 'CA'),
    (r'澳大利亚|AU|Australia', 'AU'),
    (r'俄罗斯|RU|Russia', 'RU'),
    (r'意大利|IT|Italy', 'IT'),
    (r'瑞士|CH|Switzerland', 'CH'),
    (r'瑞典|SE|Sweden', 'SE'),
    (r'芬兰|FI|Finland', 'FI'),
    (r'巴西|BR|Brazil', 'BR'),
    (r'印度|IN|India', 'IN'),
]

# CDN 域名关键词（这些域名的 IP 不代表实际落地地区）
CDN_KEYWORDS = [
    'cloudflare', 'cloudfront', 'akamai', 'fastly', 'cdn',
    'shopify', 'apple.com', 'itunes', 'icloud',
    'microsoft.com', 'azure', 'workers.dev', 'pages.dev',
    'vercel', 'netlify', 'github.io',
]


def _download_geoip_db():
    """下载 GeoLite2 Country 数据库（带缓存）。"""
    os.makedirs(GEOIP_DB_CACHE_DIR, exist_ok=True)

    # 检查缓存是否有效
    if os.path.exists(GEOIP_DB_PATH):
        mtime = datetime.fromtimestamp(os.path.getmtime(GEOIP_DB_PATH))
        if datetime.now() - mtime < timedelta(days=GEOIP_CACHE_DAYS):
            return GEOIP_DB_PATH

    print("📥 下载 GeoLite2 Country 数据库...")
    try:
        resp = requests.get(GEOIP_DB_URL, timeout=60)
        resp.raise_for_status()
        with open(GEOIP_DB_PATH, 'wb') as f:
            f.write(resp.content)
        print(f"✓ GeoIP 数据库已下载 ({len(resp.content) // 1024}KB)")
        return GEOIP_DB_PATH
    except Exception as e:
        print(f"⚠️ GeoIP 数据库下载失败: {e}")
        # 如果有旧缓存，继续用
        if os.path.exists(GEOIP_DB_PATH):
            print("  使用旧缓存继续...")
            return GEOIP_DB_PATH
        return None


def _is_cdn_domain(server: str) -> bool:
    """判断是否为 CDN 域名（IP 不代表落地地区）。"""
    server_lower = server.lower()
    return any(kw in server_lower for kw in CDN_KEYWORDS)


def _resolve_ip(server: str) -> str:
    """将域名解析为 IP 地址。如果已经是 IP 则直接返回。"""
    # 检查是否已经是 IP
    try:
        socket.inet_aton(server)
        return server
    except socket.error:
        pass

    # IPv6 检查
    try:
        socket.inet_pton(socket.AF_INET6, server)
        return server
    except socket.error:
        pass

    # DNS 解析
    try:
        ip = socket.gethostbyname(server)
        return ip
    except (socket.gaierror, socket.herror, OSError):
        return None


def _get_country_from_name(name: str) -> str:
    """从节点名称中提取标记的国家代码。"""
    for pattern, code in NAME_COUNTRY_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            return code
    return None


def _get_node_suffix(name: str) -> str:
    """提取节点名中的编号后缀（如 -29, -103 等）。"""
    m = re.search(r'[-_](\d+)(?:\s|$)', name)
    if m:
        return m.group(0).strip()
    return ''


def verify_and_fix_proxies(proxies: list) -> list:
    """验证并修正节点名称中的地区标记。

    Args:
        proxies: Clash 格式的 proxies 列表

    Returns:
        修正后的 proxies 列表
    """
    try:
        import geoip2.database
    except ImportError:
        print("⚠️ geoip2 未安装，跳过 GeoIP 验证")
        return proxies

    db_path = _download_geoip_db()
    if not db_path:
        print("⚠️ 无法获取 GeoIP 数据库，跳过验证")
        return proxies

    try:
        reader = geoip2.database.Reader(db_path)
    except Exception as e:
        print(f"⚠️ GeoIP 数据库打开失败: {e}")
        return proxies

    fixed_count = 0
    skipped_cdn = 0
    skipped_cn = 0
    skipped_resolve = 0

    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue

        name = proxy.get('name', '')
        server = str(proxy.get('server', ''))

        if not name or not server:
            continue

        # 提取节点名中标记的国家
        labeled_country = _get_country_from_name(name)
        if not labeled_country:
            continue  # 无法识别标记国家，跳过

        # 跳过 CDN 域名
        if _is_cdn_domain(server):
            skipped_cdn += 1
            continue

        # 解析 IP
        ip = _resolve_ip(server)
        if not ip:
            skipped_resolve += 1
            continue

        # GeoIP 查询
        try:
            response = reader.country(ip)
            actual_country = response.country.iso_code
        except Exception:
            continue

        if not actual_country:
            continue

        # 跳过 CN（大概率是中转入口）
        if actual_country == 'CN':
            skipped_cn += 1
            continue

        # 比较：标记国家 vs 实际国家
        if labeled_country == actual_country:
            continue  # 一致，不改

        # 需要纠正
        if actual_country in COUNTRY_MAP:
            flag, cn_name = COUNTRY_MAP[actual_country]
            suffix = _get_node_suffix(name)
            old_label = labeled_country
            new_name = f"{flag} {cn_name}{actual_country}{suffix}（原标{old_label}）"
            proxy['name'] = new_name
            fixed_count += 1

    reader.close()

    if fixed_count > 0 or skipped_cdn > 0:
        print(f"✓ GeoIP 验证完成: 纠正 {fixed_count} 个节点名称")
        if skipped_cdn:
            print(f"  - 跳过 CDN 域名: {skipped_cdn} 个")
        if skipped_cn:
            print(f"  - 跳过 CN 中转: {skipped_cn} 个")
        if skipped_resolve:
            print(f"  - 无法解析: {skipped_resolve} 个")

    return proxies
