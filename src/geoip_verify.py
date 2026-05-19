#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GeoIP 验证模块：根据节点实际 IP 归属地纠正名称和分组。
"""

import os
import socket
import tempfile
import tarfile
from pathlib import Path

import requests

# GeoLite2 Country 数据库下载地址（GitHub 镜像，免注册）
GEOLITE2_URL = 'https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-Country.mmdb'

# 国家代码到中文名称 + emoji 映射
COUNTRY_MAP = {
    'CN': ('中国', '🇨🇳'),
    'HK': ('香港', '🇭🇰'),
    'TW': ('台湾', '🇨🇳'),
    'JP': ('日本', '🇯🇵'),
    'KR': ('韩国', '🇰🇷'),
    'SG': ('新加坡', '🇸🇬'),
    'US': ('美国', '🇺🇸'),
    'GB': ('英国', '🇬🇧'),
    'DE': ('德国', '🇩🇪'),
    'FR': ('法国', '🇫🇷'),
    'AU': ('澳大利亚', '🇦🇺'),
    'CA': ('加拿大', '🇨🇦'),
    'IN': ('印度', '🇮🇳'),
    'RU': ('俄罗斯', '🇷🇺'),
    'BR': ('巴西', '🇧🇷'),
    'NL': ('荷兰', '🇳🇱'),
    'TH': ('泰国', '🇹🇭'),
    'VN': ('越南', '🇻🇳'),
    'PH': ('菲律宾', '🇵🇭'),
    'MY': ('马来西亚', '🇲🇾'),
    'ID': ('印尼', '🇮🇩'),
    'TR': ('土耳其', '🇹🇷'),
    'IL': ('以色列', '🇮🇱'),
    'PL': ('波兰', '🇵🇱'),
    'FI': ('芬兰', '🇫🇮'),
    'PT': ('葡萄牙', '🇵🇹'),
    'IE': ('爱尔兰', '🇮🇪'),
    'AR': ('阿根廷', '🇦🇷'),
}


def _download_geolite2_db(cache_dir: str = None) -> str:
    """下载 GeoLite2 Country 数据库，返回 mmdb 文件路径。"""
    if cache_dir is None:
        cache_dir = os.path.join(tempfile.gettempdir(), 'geoip_cache')
    os.makedirs(cache_dir, exist_ok=True)

    mmdb_path = os.path.join(cache_dir, 'GeoLite2-Country.mmdb')

    # 如果缓存存在且不超过 7 天，直接使用
    if os.path.exists(mmdb_path):
        import time
        age = time.time() - os.path.getmtime(mmdb_path)
        if age < 7 * 86400:
            return mmdb_path

    print("📥 正在下载 GeoLite2 Country 数据库...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(GEOLITE2_URL, headers=headers, timeout=60)
    resp.raise_for_status()

    with open(mmdb_path, 'wb') as f:
        f.write(resp.content)

    print(f"✓ GeoLite2 数据库已缓存: {mmdb_path} ({len(resp.content) // 1024}KB)")
    return mmdb_path


def _resolve_host(host: str) -> str:
    """将域名解析为 IP 地址。如果已是 IP 则直接返回。"""
    # 简单判断是否已经是 IP
    try:
        socket.inet_aton(host)
        return host
    except socket.error:
        pass

    # IPv6 检查
    if ':' in host:
        try:
            socket.inet_pton(socket.AF_INET6, host)
            return host
        except socket.error:
            pass

    # DNS 解析
    try:
        result = socket.getaddrinfo(host, None, socket.AF_INET)
        if result:
            return result[0][4][0]
    except (socket.gaierror, socket.timeout, OSError):
        pass

    return ''


def verify_and_fix_proxies(proxies: list) -> list:
    """验证节点列表中每个节点的实际地理位置，纠正名称和标记。

    返回修正后的 proxies 列表，每个节点会新增 '_real_country' 字段。
    """
    try:
        import geoip2.database
    except ImportError:
        print("⚠️ geoip2 未安装，跳过 GeoIP 验证")
        return proxies

    try:
        mmdb_path = _download_geolite2_db()
        reader = geoip2.database.Reader(mmdb_path)
    except Exception as e:
        print(f"⚠️ GeoIP 数据库加载失败，跳过验证: {e}")
        return proxies

    fixed_count = 0
    failed_count = 0

    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue

        server = proxy.get('server', '')
        if not server:
            continue

        # 解析 IP
        ip = _resolve_host(server)
        if not ip:
            failed_count += 1
            continue

        # 查询 GeoIP
        try:
            response = reader.country(ip)
            real_country = response.country.iso_code
        except Exception:
            failed_count += 1
            continue

        if not real_country:
            failed_count += 1
            continue

        # 记录实际国家
        proxy['_real_country'] = real_country

        # 获取节点原始名称中标注的国家
        name = proxy.get('name', '')
        original_country = _detect_country_from_name(name)

        # 如果实际国家和名称标注不一致，修正名称
        if original_country and real_country != original_country:
            # 如果 GeoIP 结果是 CN（中国大陆），大概率是中转入口而非落地
            # 保持原名不改，避免误导
            if real_country == 'CN':
                continue

            country_info = COUNTRY_MAP.get(real_country)
            if country_info:
                cn_name, emoji = country_info
                # 提取原名称中的编号（如 US-29 中的 29）
                number = _extract_number(name)
                suffix = f"-{number}" if number else ""
                new_name = f"{emoji}{cn_name}{real_country}{suffix}（原标{original_country}）"
                proxy['name'] = new_name
                fixed_count += 1

    reader.close()
    print(f"✓ GeoIP 验证完成: 纠正 {fixed_count} 个节点名称"
          f"（{failed_count} 个无法解析）")
    return proxies


def _detect_country_from_name(name: str) -> str:
    """从节点名称中检测标注的国家代码。"""
    # 检查常见的国家标识
    country_indicators = {
        'HK': ['香港', 'HK', '🇭🇰'],
        'TW': ['台湾', 'TW', '🇨🇳', '🇹🇼'],
        'JP': ['日本', 'JP', '🇯🇵'],
        'KR': ['韩国', 'KR', '🇰🇷'],
        'SG': ['新加坡', '狮城', 'SG', '🇸🇬'],
        'US': ['美国', 'US', '🇺🇸'],
        'GB': ['英国', 'GB', 'UK', '🇬🇧'],
        'DE': ['德国', 'DE', '🇩🇪'],
        'FR': ['法国', 'FR', '🇫🇷'],
        'AU': ['澳大利亚', 'AU', '🇦🇺'],
        'CA': ['加拿大', 'CA', '🇨🇦'],
        'IN': ['印度', 'IN', '🇮🇳'],
        'RU': ['俄罗斯', 'RU', '🇷🇺'],
        'TH': ['泰国', 'TH', '🇹🇭'],
        'VN': ['越南', 'VN', '🇻🇳'],
    }

    for code, indicators in country_indicators.items():
        for indicator in indicators:
            if indicator in name:
                return code
    return ''


def _extract_number(name: str) -> str:
    """从节点名称中提取编号。如 '🇺🇸美国US-29' → '29'"""
    import re
    match = re.search(r'[\-](\d+)', name)
    if match:
        return match.group(1)
    return ''
