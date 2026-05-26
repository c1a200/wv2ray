#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 v2ray 订阅文件并保存
"""

import json
import sys
import os
import base64
import urllib.parse
from pathlib import Path
from datetime import datetime

import yaml
import requests

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


DEFAULT_DIRECT_V2RAY_URL = 'https://node.zyfx6.xyz/v2rayNG/'
DEFAULT_DIRECT_CLASH_URL = 'https://node.zyfx6.xyz/clash'


def _env_to_bool(value: str, default: bool) -> bool:
    """将环境变量字符串转换为布尔值。"""
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


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


# FlClash / Clash 内核要求配置文件顶部包含这些基础字段
_CLASH_REQUIRED_HEADER = """\
port: 7890
socks-port: 7891
allow-lan: true
mode: rule
log-level: info
external-controller: 127.0.0.1:9090
"""


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


def _filter_unsupported_proxies(content: str) -> str:
    """过滤掉 FlClash/Clash Meta 不支持的代理协议类型。

    FlClash 支持的协议: vmess, vless, trojan, ss, ssr, hysteria2, tuic
    不支持的协议会导致整个配置文件导入失败（如 "invalid REALITY short ID" 等报错）。

    过滤规则：
    1. 移除不支持的协议类型: anytls, http, socks5, hysteria (v1)
    2. 移除 server 字段包含非法字符的节点（如 @）
    3. 移除 network: raw 的节点（FlClash 不支持）
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

    # FlClash/Clash Meta 支持的协议类型
    SUPPORTED_TYPES = {
        'vmess', 'vless', 'trojan', 'ss', 'ssr',
        'hysteria2', 'hy2', 'tuic', 'wireguard',
    }

    valid = []
    removed_reasons = {}
    cleaned_fields = 0

    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue

        proxy_type = str(proxy.get('type', '')).lower()
        name = proxy.get('name', '未知')

        # 检查协议类型是否支持
        if proxy_type not in SUPPORTED_TYPES:
            reason = f'不支持的协议: {proxy_type}'
            removed_reasons[reason] = removed_reasons.get(reason, 0) + 1
            continue

        # 检查 server 字段是否有效
        server = str(proxy.get('server', ''))
        if not server or server.startswith('@') or server.startswith("'@"):
            reason = '无效的 server 地址'
            removed_reasons[reason] = removed_reasons.get(reason, 0) + 1
            continue

        # 检查 network: raw（FlClash 不支持）
        network = str(proxy.get('network', '')).lower()
        if network == 'raw':
            reason = '不支持的 network: raw'
            removed_reasons[reason] = removed_reasons.get(reason, 0) + 1
            continue

        # 检查 ech-opts（Encrypted Client Hello，FlClash 不支持）
        if proxy.get('ech-opts'):
            reason = '不支持的 ech-opts (ECH)'
            removed_reasons[reason] = removed_reasons.get(reason, 0) + 1
            continue

        # 清理 reality-opts 中的非标准字段（如 _spider-x, _dns）
        # 这些字段不是协议规范的一部分，会导致某些客户端解析异常
        if proxy.get('reality-opts') and isinstance(proxy['reality-opts'], dict):
            keys_to_remove = [k for k in proxy['reality-opts'] if k.startswith('_')]
            for k in keys_to_remove:
                del proxy['reality-opts'][k]
                cleaned_fields += 1
            # 确保 short-id 是字符串（纯数字如 09 在 YAML 中会被误解析为整数）
            if 'short-id' in proxy['reality-opts']:
                proxy['reality-opts']['short-id'] = str(proxy['reality-opts']['short-id'])

        valid.append(proxy)

    removed_count = len(proxies) - len(valid)
    if removed_count > 0 or cleaned_fields > 0:
        if removed_count > 0:
            print(f"✓ 协议过滤: 移除 {removed_count} 个不兼容节点（保留 {len(valid)} 个）")
            for reason, count in sorted(removed_reasons.items(),
                                        key=lambda x: -x[1]):
                print(f"  - {reason}: {count} 个")
        if cleaned_fields > 0:
            print(f"✓ 清理了 {cleaned_fields} 个非标准字段（_spider-x 等）")
        data['proxies'] = valid
        return yaml.dump(data, allow_unicode=True, default_flow_style=False,
                         sort_keys=False, width=1000)

    return content


def _ensure_proxy_groups(content: str) -> str:
    """确保 Clash 配置包含 proxy-groups 和 rules。

    如果上游只返回了 proxies 列表而没有 proxy-groups/rules，
    自动补充默认的分组和规则，使 FlClash 等客户端能正常使用。
    """
    try:
        data = yaml.safe_load(content)
    except Exception:
        return content

    if not isinstance(data, dict):
        return content

    # 如果已有 proxy-groups，直接返回
    if data.get('proxy-groups'):
        return content

    if not data.get('proxies'):
        return content

    print("⚠️ 上游缺少 proxy-groups/rules，自动补充默认分组...")

    # 生成默认 proxy-groups
    data['proxy-groups'] = [
        {
            'name': '🚀 节点选择',
            'type': 'select',
            'include-all': True,
            'proxies': ['♻️ 自动选择', '🌍 地区选择', 'DIRECT'],
        },
        {
            'name': '🌍 地区选择',
            'type': 'select',
            'proxies': ['🇭🇰 香港节点', '🇯🇵 日本节点', '🇺🇸 美国节点',
                        '🇸🇬 新加坡节点', '🇰🇷 韩国节点', '🇨🇳 台湾节点'],
        },
        {
            'name': '♻️ 自动选择',
            'type': 'url-test',
            'include-all': True,
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🇭🇰 香港节点',
            'type': 'url-test',
            'include-all': True,
            'filter': '(?i)香港|HK|Hong',
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🇯🇵 日本节点',
            'type': 'url-test',
            'include-all': True,
            'filter': '(?i)日本|JP|Japan',
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🇺🇸 美国节点',
            'type': 'url-test',
            'include-all': True,
            'filter': '(?i)美国|US|United States',
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🇸🇬 新加坡节点',
            'type': 'url-test',
            'include-all': True,
            'filter': '(?i)新加坡|狮城|SG|Singapore',
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🇰🇷 韩国节点',
            'type': 'url-test',
            'include-all': True,
            'filter': '(?i)韩国|KR|Korea',
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🇨🇳 台湾节点',
            'type': 'url-test',
            'include-all': True,
            'filter': '(?i)台湾|TW|Taiwan',
            'interval': 300,
            'tolerance': 50,
        },
        {
            'name': '🎯 全球直连',
            'type': 'select',
            'proxies': ['DIRECT', '🚀 节点选择'],
        },
    ]

    # 生成默认 rules
    data['rules'] = [
        'GEOIP,LAN,DIRECT',
        'GEOIP,CN,DIRECT',
        'MATCH,🚀 节点选择',
    ]

    return yaml.dump(data, allow_unicode=True, default_flow_style=False,
                     sort_keys=False, width=1000)


def _optimize_proxy_groups(content: str) -> str:
    """优化 Clash 配置中的 proxy-groups 结构。

    改动：
    1. 「节点选择」改为 include-all，可直接选具体节点
    2. 「手动切换」改名为「地区选择」，只保留地区分组作为选项
    3. 各地区组保持按名称过滤 + url-test（地区内自动测速选最快）
    4. 「自动选择」保持 include-all + url-test（全局最快）
    """
    try:
        data = yaml.safe_load(content)
    except Exception:
        return content

    if not isinstance(data, dict) or 'proxy-groups' not in data:
        return content

    groups = data['proxy-groups']
    if not groups:
        return content

    # 找到「节点选择」和「手动切换」
    select_group = None
    manual_group = None
    manual_group_name = None
    for g in groups:
        name = g.get('name', '')
        if '节点选择' in name:
            select_group = g
        if '手动切换' in name:
            manual_group = g
            manual_group_name = name

    # 收集地区组名称（用于「地区选择」的 proxies 列表）
    region_keywords = ('香港', '台湾', '狮城', '新加坡', '日本', '美国',
                       '韩国', '英国', '德国', '澳大利亚', '加拿大',
                       'HK', 'TW', 'SG', 'JP', 'US', 'KR')
    region_group_names = []
    for g in groups:
        name = g.get('name', '')
        if any(kw in name for kw in region_keywords) and '节点' in name:
            region_group_names.append(name)

    if select_group:
        # 把「节点选择」改为 include-all，可直接选具体节点
        select_group['include-all'] = True
        # proxies 只保留：自动选择、DIRECT（不再引用地区选择，避免重复）
        select_group['proxies'] = ['♻️ 自动选择', 'DIRECT']

    if manual_group:
        # 把「手动切换」改名为「地区选择」，只包含地区分组
        manual_group['name'] = '🌍 地区选择'
        manual_group['type'] = 'select'
        # 移除 include-all，改为手动列出地区组
        manual_group.pop('include-all', None)
        manual_group['proxies'] = region_group_names if region_group_names else [
            '♻️ 自动选择'
        ]

    # 更新所有引用「手动切换」的地方为「地区选择」
    if manual_group_name:
        for g in groups:
            if 'proxies' in g:
                g['proxies'] = [
                    '🌍 地区选择' if p == manual_group_name else p
                    for p in g['proxies']
                ]

    return yaml.dump(data, allow_unicode=True, default_flow_style=False,
                     sort_keys=False, width=1000)


def _ensure_clash_headers(content: str) -> str:
    """确保 clash 配置包含必要的顶级字段。

    如果上游返回的内容直接以 proxies: 开头（缺少 port/mode 等），
    则自动补充默认 Clash 配置头部，使 FlClash 等客户端能正确识别。
    同时去除可能存在的 UTF-8 BOM。
    """
    # 去除 BOM（如果存在）
    content = content.lstrip('\ufeff')

    # 检查是否已包含关键顶级字段
    stripped = content.lstrip()
    has_port = stripped.startswith('port:') or '\nport:' in content
    has_mode = '\nmode:' in content or stripped.startswith('mode:')

    if has_port and has_mode:
        # 已经包含完整头部，直接返回
        return content

    # 缺少头部，补充默认配置
    print("⚠️ 上游 clash 内容缺少必要头部字段，自动补充默认配置...")
    return _CLASH_REQUIRED_HEADER + content


def _is_valid_v2ray_subscription(content: str) -> bool:
    """判断内容是否是有效的 v2rayNG 订阅格式。

    有效格式：
    1. Base64 编码的 URI 列表（解码后每行是 vmess://、vless://、trojan://、ss:// 等）
    2. 纯文本 URI 列表（每行以协议前缀开头）
    """
    stripped = content.strip()

    # 如果以 proxies: 开头，说明是 Clash YAML 格式，不是 v2ray 格式
    if stripped.startswith('proxies:'):
        return False

    # 检查是否是纯文本 URI 列表
    first_line = stripped.split('\n')[0].strip()
    v2ray_prefixes = ('vmess://', 'vless://', 'trojan://', 'ss://', 'ssr://',
                      'hysteria2://', 'hysteria://', 'hy2://')
    if first_line.startswith(v2ray_prefixes):
        return True

    # 尝试 base64 解码
    try:
        # 补齐 base64 padding
        padded = stripped + '=' * (-len(stripped) % 4)
        decoded = base64.b64decode(padded).decode('utf-8', errors='replace')
        # 跳过空行找第一个有效行
        for line in decoded.split('\n'):
            first_decoded_line = line.strip()
            if first_decoded_line:
                break
        else:
            first_decoded_line = ''
        if first_decoded_line.startswith(v2ray_prefixes):
            return True
    except Exception:
        pass

    return False


def _proxy_to_vmess_uri(proxy: dict) -> str:
    """将 Clash vmess 节点转换为 vmess:// URI。"""
    vmess_obj = {
        'v': '2',
        'ps': proxy.get('name', ''),
        'add': proxy.get('server', ''),
        'port': str(proxy.get('port', '')),
        'id': proxy.get('uuid', ''),
        'aid': str(proxy.get('alterId', 0)),
        'scy': proxy.get('cipher', 'auto'),
        'net': proxy.get('network', 'tcp'),
        'type': 'none',
        'host': '',
        'path': '',
        'tls': 'tls' if proxy.get('tls') else '',
        'sni': proxy.get('servername', ''),
    }

    ws_opts = proxy.get('ws-opts', {})
    if ws_opts:
        vmess_obj['path'] = ws_opts.get('path', '')
        headers = ws_opts.get('headers', {})
        vmess_obj['host'] = headers.get('Host', '')

    grpc_opts = proxy.get('grpc-opts', {})
    if grpc_opts:
        vmess_obj['path'] = grpc_opts.get('grpc-service-name', '')

    encoded = base64.b64encode(
        json.dumps(vmess_obj, ensure_ascii=False).encode('utf-8')
    ).decode('utf-8')
    return f'vmess://{encoded}'


def _proxy_to_vless_uri(proxy: dict) -> str:
    """将 Clash vless 节点转换为 vless:// URI。"""
    uuid = proxy.get('uuid', '')
    server = proxy.get('server', '')
    port = proxy.get('port', '')
    name = urllib.parse.quote(proxy.get('name', ''))

    params = {}
    if proxy.get('tls'):
        params['security'] = 'tls'
    if proxy.get('reality-opts'):
        params['security'] = 'reality'
        reality = proxy['reality-opts']
        if reality.get('public-key'):
            params['pbk'] = reality['public-key']
        if reality.get('short-id'):
            params['sid'] = reality['short-id']
    if proxy.get('flow'):
        params['flow'] = proxy['flow']
    if proxy.get('network'):
        params['type'] = proxy['network']
    if proxy.get('servername'):
        params['sni'] = proxy['servername']
    if proxy.get('client-fingerprint'):
        params['fp'] = proxy['client-fingerprint']

    ws_opts = proxy.get('ws-opts', {})
    if ws_opts:
        params['path'] = ws_opts.get('path', '')
        headers = ws_opts.get('headers', {})
        if headers.get('Host'):
            params['host'] = headers['Host']

    grpc_opts = proxy.get('grpc-opts', {})
    if grpc_opts:
        params['serviceName'] = grpc_opts.get('grpc-service-name', '')

    if proxy.get('skip-cert-verify'):
        params['allowInsecure'] = '1'

    query = urllib.parse.urlencode(params)
    return f'vless://{uuid}@{server}:{port}?{query}#{name}'


def _proxy_to_trojan_uri(proxy: dict) -> str:
    """将 Clash trojan 节点转换为 trojan:// URI。"""
    password = urllib.parse.quote(str(proxy.get('password', '')), safe='')
    server = proxy.get('server', '')
    port = proxy.get('port', '')
    name = urllib.parse.quote(proxy.get('name', ''))

    params = {}
    if proxy.get('sni'):
        params['sni'] = proxy['sni']
    if proxy.get('skip-cert-verify'):
        params['allowInsecure'] = '1'
    if proxy.get('network') == 'ws':
        params['type'] = 'ws'
        ws_opts = proxy.get('ws-opts', {})
        if ws_opts.get('path'):
            params['path'] = ws_opts['path']
        headers = ws_opts.get('headers', {})
        if headers.get('Host'):
            params['host'] = headers['Host']

    query = urllib.parse.urlencode(params)
    return f'trojan://{password}@{server}:{port}?{query}#{name}'


def _proxy_to_ss_uri(proxy: dict) -> str:
    """将 Clash ss 节点转换为 ss:// URI。"""
    cipher = proxy.get('cipher', '')
    password = proxy.get('password', '')
    server = proxy.get('server', '')
    port = proxy.get('port', '')
    name = urllib.parse.quote(proxy.get('name', ''))

    # ss:// 格式: base64(method:password)@server:port#name
    user_info = base64.b64encode(
        f'{cipher}:{password}'.encode('utf-8')
    ).decode('utf-8').rstrip('=')

    plugin = proxy.get('plugin', '')
    plugin_opts = proxy.get('plugin-opts', {})
    if plugin:
        plugin_str = f'{plugin};'
        opts_parts = []
        for k, v in plugin_opts.items():
            opts_parts.append(f'{k}={v}')
        plugin_str += ';'.join(opts_parts)
        plugin_param = urllib.parse.quote(plugin_str)
        return f'ss://{user_info}@{server}:{port}?plugin={plugin_param}#{name}'

    return f'ss://{user_info}@{server}:{port}#{name}'


def _proxy_to_hysteria2_uri(proxy: dict) -> str:
    """将 Clash hysteria2 节点转换为 hysteria2:// URI。"""
    password = urllib.parse.quote(str(proxy.get('password', '')), safe='')
    server = proxy.get('server', '')
    port = proxy.get('port', '')
    name = urllib.parse.quote(proxy.get('name', ''))

    params = {}
    if proxy.get('sni'):
        params['sni'] = proxy['sni']
    if proxy.get('skip-cert-verify'):
        params['insecure'] = '1'
    if proxy.get('obfs') == 'salamander':
        params['obfs'] = 'salamander'
        if proxy.get('obfs-password'):
            params['obfs-password'] = proxy['obfs-password']
    if proxy.get('ports'):
        params['mport'] = proxy['ports']

    query = urllib.parse.urlencode(params)
    return f'hysteria2://{password}@{server}:{port}?{query}#{name}'


def _proxy_to_ssr_uri(proxy: dict) -> str:
    """将 Clash ssr 节点转换为 ssr:// URI。"""
    server = proxy.get('server', '')
    port = str(proxy.get('port', ''))
    protocol = proxy.get('protocol', 'origin')
    cipher = proxy.get('cipher', '')
    obfs = proxy.get('obfs', 'plain')
    password = proxy.get('password', '')

    # SSR URI: base64(server:port:protocol:method:obfs:base64(password)/
    #   ?obfsparam=base64(obfs-param)&protoparam=base64(proto-param)&remarks=base64(name))
    def b64_encode(s):
        return base64.urlsafe_b64encode(
            s.encode('utf-8')
        ).decode('utf-8').rstrip('=')

    password_b64 = b64_encode(password)
    main_part = f'{server}:{port}:{protocol}:{cipher}:{obfs}:{password_b64}'

    params_parts = []
    obfs_param = proxy.get('obfs-param', '')
    if obfs_param:
        params_parts.append(f'obfsparam={b64_encode(obfs_param)}')
    proto_param = proxy.get('protocol-param', '')
    if proto_param:
        params_parts.append(f'protoparam={b64_encode(proto_param)}')
    name = proxy.get('name', '')
    if name:
        params_parts.append(f'remarks={b64_encode(name)}')

    if params_parts:
        main_part += '/?' + '&'.join(params_parts)

    encoded = base64.urlsafe_b64encode(
        main_part.encode('utf-8')
    ).decode('utf-8').rstrip('=')
    return f'ssr://{encoded}'


def _proxy_to_http_uri(proxy: dict) -> str:
    """将 Clash http 节点转换为简易 URI 格式（v2rayN 可识别）。"""
    server = proxy.get('server', '')
    port = proxy.get('port', '')
    name = urllib.parse.quote(proxy.get('name', ''))
    username = proxy.get('username', '')
    password = proxy.get('password', '')
    tls = proxy.get('tls', False)

    scheme = 'https' if tls else 'http'
    if username and password:
        userinfo = f'{urllib.parse.quote(username)}:{urllib.parse.quote(password)}@'
    else:
        userinfo = ''

    return f'{scheme}://{userinfo}{server}:{port}#{name}'


def _proxy_to_socks5_uri(proxy: dict) -> str:
    """将 Clash socks5 节点转换为 socks5:// URI。"""
    server = proxy.get('server', '')
    port = proxy.get('port', '')
    name = urllib.parse.quote(proxy.get('name', ''))
    username = proxy.get('username', '')
    password = proxy.get('password', '')

    if username and password:
        userinfo = f'{urllib.parse.quote(username)}:{urllib.parse.quote(password)}@'
    else:
        userinfo = ''

    return f'socks5://{userinfo}{server}:{port}#{name}'


def _clash_proxies_to_v2ray_uris(content: str) -> str:
    """将 Clash YAML 格式的 proxies 列表转换为 v2rayNG 订阅格式（base64 编码的 URI 列表）。"""
    # 去除 BOM
    content = content.lstrip('\ufeff')

    try:
        data = yaml.safe_load(content)
    except Exception as e:
        print(f"⚠️ YAML 解析失败，尝试手动提取 proxies: {e}")
        return content

    proxies = data if isinstance(data, list) else (
        data.get('proxies', []) if isinstance(data, dict) else []
    )
    if not proxies:
        print("⚠️ 未找到 proxies 列表，返回原始内容")
        return content

    uris = []
    skipped = 0
    for proxy in proxies:
        # 有些上游返回的 proxies 元素是 JSON 字符串而非字典，需要解析
        if isinstance(proxy, str):
            try:
                proxy = json.loads(proxy)
            except (json.JSONDecodeError, TypeError):
                skipped += 1
                continue
        if not isinstance(proxy, dict):
            skipped += 1
            continue

        proxy_type = proxy.get('type', '').lower()
        try:
            if proxy_type == 'vmess':
                uris.append(_proxy_to_vmess_uri(proxy))
            elif proxy_type == 'vless':
                uris.append(_proxy_to_vless_uri(proxy))
            elif proxy_type == 'trojan':
                uris.append(_proxy_to_trojan_uri(proxy))
            elif proxy_type == 'ss':
                uris.append(_proxy_to_ss_uri(proxy))
            elif proxy_type == 'ssr':
                uris.append(_proxy_to_ssr_uri(proxy))
            elif proxy_type in ('hysteria2', 'hy2', 'hysteria'):
                uris.append(_proxy_to_hysteria2_uri(proxy))
            elif proxy_type == 'http':
                uris.append(_proxy_to_http_uri(proxy))
            elif proxy_type == 'socks5':
                uris.append(_proxy_to_socks5_uri(proxy))
            else:
                # anytls 等无标准 URI 格式的协议，跳过
                skipped += 1
        except Exception as e:
            skipped += 1
            continue

    print(f"✓ 已转换 {len(uris)} 个节点为 v2ray URI 格式"
          f"（跳过 {skipped} 个不支持的节点）")

    if not uris:
        print("⚠️ 无法转换任何节点，返回原始内容")
        return content

    # v2rayNG 只支持 vmess/vless/trojan/ss/ssr 协议
    # hysteria2/http/socks5 等会导致 v2rayNG 整体解析失败
    # 所以只保留兼容的协议行
    v2rayng_prefixes = ('vmess://', 'vless://', 'trojan://', 'ss://', 'ssr://')
    compatible_uris = [u for u in uris if u.startswith(v2rayng_prefixes)]
    extra_count = len(uris) - len(compatible_uris)
    if extra_count > 0:
        print(f"⚠️ 过滤掉 {extra_count} 个 v2rayNG 不兼容的协议"
              f"（hysteria2/http/socks5），这些节点仍可通过 clash.yaml 使用")

    # v2rayNG 订阅格式：所有 URI 用换行连接，然后整体 base64 编码
    uri_text = '\n'.join(compatible_uris)
    encoded = base64.b64encode(uri_text.encode('utf-8')).decode('utf-8')
    return encoded


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


def save_subscription_files(output_dir: str = '.'):
    """获取并保存订阅文件（v2ray 与 clash）"""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        use_direct_source = _env_to_bool(
            os.getenv('USE_DIRECT_SOURCE'),
            default=True,
        )

        if use_direct_source:
            v2ray_url = (
                os.getenv('DIRECT_V2RAY_URL') or DEFAULT_DIRECT_V2RAY_URL
            ).strip()
            clash_url = (
                os.getenv('DIRECT_CLASH_URL') or DEFAULT_DIRECT_CLASH_URL
            ).strip()

            fetched_at = datetime.utcnow().isoformat() + 'Z'

            print('📥 已启用直链模式，暂停抓取 GitHub Issue #91')
            print(f'✓ v2ray 源地址: {v2ray_url}')
            print(f'✓ clash 源地址: {clash_url}')

            print('📥 正在直接抓取 v2ray 订阅内容...')
            v2ray_content = _fetch_direct_content(v2ray_url)

            print('📥 正在直接抓取 clash 订阅内容...')
            clash_content = _fetch_direct_content(clash_url)
        else:
            # 保留旧模式：从 GitHub Issue 动态提取 token + api_url
            from fetcher import AggregatorFetcher

            fetcher = AggregatorFetcher()
            print('📥 正在从 GitHub Issue 获取订阅信息...')
            info = fetcher.get_subscription_info()

            print(f"✓ Token: {info['token']}")
            print(f"✓ API URL: {info['api_url']}")

            v2ray_url = fetcher.build_subscribe_url(
                token=info['token'],
                api_url=info['api_url'],
                target='v2ray'
            )

            clash_url = fetcher.build_subscribe_url(
                token=info['token'],
                api_url=info['api_url'],
                target='clash'
            )

            print('📥 正在获取 v2ray 订阅内容...')
            v2ray_content = fetcher.fetch_subscription_content(
                v2ray_url,
                target='v2ray',
            )

            print('📥 正在获取 clash 订阅内容...')
            clash_content = fetcher.fetch_subscription_content(
                clash_url,
                target='clash',
            )

            fetched_at = info['fetched_at']

        v2_file = output_path / 'subscribe.txt'
        # 检测 v2ray 内容格式，如果是 Clash YAML 则自动转换为 v2rayNG 格式
        if _is_valid_v2ray_subscription(v2ray_content):
            v2_final_content = v2ray_content
            print("✓ v2ray 内容已是有效的订阅格式")
        else:
            print("⚠️ 上游 v2ray 源返回了 Clash 格式，自动转换为 v2rayNG 订阅格式...")
            # 先去重 + GeoIP 纠正，再转换为 v2ray URI
            _v2_processed = _dedup_proxies(_ensure_clash_headers(v2ray_content))
            try:
                from geoip_verify import verify_and_fix_proxies as _geoip_fix_v2
                _v2_data = yaml.safe_load(_v2_processed)
                if isinstance(_v2_data, dict) and _v2_data.get('proxies'):
                    _v2_data['proxies'] = _geoip_fix_v2(_v2_data['proxies'])
                    _v2_processed = yaml.dump(
                        _v2_data, allow_unicode=True,
                        default_flow_style=False, sort_keys=False, width=1000,
                    )
            except Exception:
                pass
            v2_final_content = _clash_proxies_to_v2ray_uris(_v2_processed)
        v2_file.write_text(v2_final_content, encoding='utf-8')
        print(f"✓ v2ray 订阅文件已保存: {v2_file}")

        clash_file = output_path / 'clash.yaml'
        # 确保 clash 配置包含必要的顶级字段（FlClash/Clash 内核要求）
        clash_final_content = _ensure_clash_headers(clash_content)
        # 去除重复节点
        clash_final_content = _dedup_proxies(clash_final_content)
        # GeoIP 验证并纠正节点名称（clash 和 subscribe 共用）
        try:
            from geoip_verify import verify_and_fix_proxies as _geoip_fix
            _geoip_data = yaml.safe_load(clash_final_content)
            if isinstance(_geoip_data, dict) and _geoip_data.get('proxies'):
                _geoip_data['proxies'] = _geoip_fix(_geoip_data['proxies'])
                clash_final_content = yaml.dump(
                    _geoip_data, allow_unicode=True,
                    default_flow_style=False, sort_keys=False, width=1000,
                )
        except Exception as geoip_err:
            print(f"⚠️ GeoIP 纠正跳过: {geoip_err}")
        # 过滤掉 FlClash 不支持的协议类型（anytls/http/socks5/hysteria v1 等）
        clash_final_content = _filter_unsupported_proxies(clash_final_content)
        # 确保包含 proxy-groups 和 rules（上游可能只返回 proxies 列表）
        clash_final_content = _ensure_proxy_groups(clash_final_content)
        # 优化 proxy-groups 结构
        clash_final_content = _optimize_proxy_groups(clash_final_content)
        # 修复 YAML 输出中纯数字 short-id 未加引号的问题
        # （如 short-id: 09 会被 Clash YAML 1.1 解析器当作无效八进制）
        import re as _re
        clash_final_content = _re.sub(
            r'([ ]+short-id: )(\d+)$',
            lambda m: f"{m.group(1)}'{m.group(2)}'",
            clash_final_content,
            flags=_re.MULTILINE,
        )
        # 不再添加 BOM —— BOM 会导致 Clash 内核 YAML 解析失败
        clash_file.write_text(clash_final_content, encoding='utf-8')
        print(f"✓ clash 订阅文件已保存: {clash_file}")

        # 额外生成 issue 版本：subscribe1.txt / clash1.yaml
        issue_variant_enabled = _env_to_bool(
            os.getenv('GENERATE_ISSUE_VARIANTS'),
            default=True,
        )
        issue_variant_status = 'disabled'
        issue_variant = None

        if issue_variant_enabled:
            try:
                issue_variant = _fetch_issue_variant()

                v2_file_issue = output_path / 'subscribe1.txt'
                issue_v2_content = issue_variant['v2ray_content']
                if _is_valid_v2ray_subscription(issue_v2_content):
                    v2_final_issue = issue_v2_content
                else:
                    print("⚠️ issue v2ray 源也返回了 Clash 格式，自动转换...")
                    v2_final_issue = _clash_proxies_to_v2ray_uris(
                        issue_v2_content
                    )
                v2_file_issue.write_text(
                    v2_final_issue,
                    encoding='utf-8',
                )
                print(f"✓ issue v2ray 订阅文件已保存: {v2_file_issue}")

                clash_file_issue = output_path / 'clash1.yaml'
                clash_final_issue = _ensure_clash_headers(
                    issue_variant['clash_content']
                )
                clash_final_issue = _filter_unsupported_proxies(
                    clash_final_issue
                )
                clash_final_issue = _optimize_proxy_groups(clash_final_issue)
                # 修复纯数字 short-id 引号问题
                clash_final_issue = _re.sub(
                    r'([ ]+short-id: )(\d+)$',
                    lambda m: f"{m.group(1)}'{m.group(2)}'",
                    clash_final_issue,
                    flags=_re.MULTILINE,
                )
                clash_file_issue.write_text(
                    clash_final_issue, encoding='utf-8'
                )
                print(f"✓ issue clash 订阅文件已保存: {clash_file_issue}")
                issue_variant_status = 'ok'
            except Exception as issue_err:
                issue_variant_status = f'failed: {issue_err}'
                print(f"⚠️ issue 增量产物生成失败，已跳过: {issue_err}")

        # 保存订阅元数据
        metadata = {
            'source_mode': 'direct' if use_direct_source else 'issue',
            'token': None if use_direct_source else info['token'],
            'api_url': None if use_direct_source else info['api_url'],
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

        # 保存信息摘要
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
            'v2ray_size_kb': round(len(v2ray_content) / 1024, 2),
            'clash_size_kb': round(len(clash_content) / 1024, 2),
            'v2ray_size_kb_issue': (
                round(len(issue_variant['v2ray_content']) / 1024, 2)
                if issue_variant else None
            ),
            'clash_size_kb_issue': (
                round(len(issue_variant['clash_content']) / 1024, 2)
                if issue_variant else None
            ),
            'format': 'v2ray (base64, upstream original) + clash (yaml)',
            'source_mode': 'direct' if use_direct_source else 'issue',
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
