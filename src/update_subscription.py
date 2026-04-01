#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 v2ray 订阅文件并保存
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

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

    print('📥 正在获取 subscribe1 (issue/v2ray) 内容...')
    v2ray_content = fetcher.fetch_subscription_content(
        v2ray_url,
        target='v2ray',
    )

    print('📥 正在获取 clash1 (issue/clash) 内容...')
    clash_content = fetcher.fetch_subscription_content(
        clash_url,
        target='clash',
    )

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
        v2_file.write_text(v2ray_content, encoding='utf-8')
        print(f"✓ v2ray 订阅文件已保存: {v2_file}")

        clash_file = output_path / 'clash.yaml'
        # 为了确保客户端正确识别为 UTF-8（特别是在某些系统上默认为 ANSI），
        # 添加 UTF-8 BOM (byte order mark)
        clash_file.write_bytes(b'\xef\xbb\xbf' + clash_content.encode('utf-8'))
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
                v2_file_issue.write_text(
                    issue_variant['v2ray_content'],
                    encoding='utf-8',
                )
                print(f"✓ issue v2ray 订阅文件已保存: {v2_file_issue}")

                clash_file_issue = output_path / 'clash1.yaml'
                clash_file_issue.write_bytes(
                    b'\xef\xbb\xbf'
                    + issue_variant['clash_content'].encode('utf-8')
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
