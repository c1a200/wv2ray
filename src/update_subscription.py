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

import yaml
import requests

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


DEFAULT_DIRECT_V2RAY_URL = 'https://node.zyfx6.xyz/v2rayNG/'
DEFAULT_DIRECT_CLASH_URL = 'https://node.zyfx6.xyz/clash'


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


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
        v2ray_url = (
            os.getenv('DIRECT_V2RAY_URL') or DEFAULT_DIRECT_V2RAY_URL
        ).strip()
        clash_url = (
            os.getenv('DIRECT_CLASH_URL') or DEFAULT_DIRECT_CLASH_URL
        ).strip()

        fetched_at = datetime.utcnow().isoformat() + 'Z'

        print(f'✓ v2ray 源地址: {v2ray_url}')
        print(f'✓ clash 源地址: {clash_url}')

        # --- v2ray: 直接保存 ---
        print('📥 正在直接抓取 v2ray 订阅内容...')
        v2ray_content = _fetch_direct_content(v2ray_url)

        v2_file = output_path / 'subscribe.txt'
        v2_file.write_text(v2ray_content, encoding='utf-8')
        print(f"✓ v2ray 订阅文件已保存: {v2_file}")

        # --- clash: 去重 + short-id 修复 + GeoIP（可选）---
        print('📥 正在直接抓取 clash 订阅内容...')
        clash_content = _fetch_direct_content(clash_url)

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
