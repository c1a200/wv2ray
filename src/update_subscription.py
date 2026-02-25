#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 v2ray 订阅文件并保存
"""

import json
import sys
import os
from pathlib import Path

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fetcher import AggregatorFetcher


def save_subscription_files(output_dir: str = '.'):
    """获取并保存订阅文件（v2ray 与 clash）"""
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # 获取订阅信息
        fetcher = AggregatorFetcher()
        print("📥 正在从 GitHub Issue 获取订阅信息...")
        info = fetcher.get_subscription_info()
        
        print(f"✓ Token: {info['token']}")
        print(f"✓ API URL: {info['api_url']}")
        
        # 构建订阅 URL (v2ray)
        v2ray_url = fetcher.build_subscribe_url(
            token=info['token'],
            api_url=info['api_url'],
            target='v2ray'
        )

        # 获取 v2ray 订阅内容（原始）
        print("📥 正在获取 v2ray 订阅内容...")
        v2ray_content = fetcher.fetch_subscription_content(v2ray_url)

        v2_file = output_path / 'subscribe.txt'
        v2_file.write_text(v2ray_content, encoding='utf-8')
        print(f"✓ v2ray 订阅文件已保存: {v2_file}")

        # 构建订阅 URL (clash)
        clash_url = fetcher.build_subscribe_url(
            token=info['token'],
            api_url=info['api_url'],
            target='clash'
        )

        # 获取 clash 订阅内容（原始 YAML）
        print("📥 正在获取 clash 订阅内容...")
        clash_content = fetcher.fetch_subscription_content(clash_url)

        clash_file = output_path / 'clash.yaml'
        # 为了确保客户端正确识别为 UTF-8（特别是在某些系统上默认为 ANSI），
        # 添加 UTF-8 BOM (byte order mark)
        clash_file.write_bytes(b'\xef\xbb\xbf' + clash_content.encode('utf-8'))
        print(f"✓ clash 订阅文件已保存: {clash_file}")
        
        # 保存订阅元数据
        metadata = {
            'token': info['token'],
            'api_url': info['api_url'],
            'v2ray_subscribe_url': v2ray_url,
            'clash_subscribe_url': clash_url,
            'fetched_at': info['fetched_at'],
            'v2ray_subscription_file': 'subscribe.txt',
            'clash_subscription_file': 'clash.yaml',
            'github_pages_v2ray': 'https://c1a200.github.io/wv2ray/subscribe.txt',
            'github_pages_clash': 'https://c1a200.github.io/wv2ray/clash.yaml'
        }
        
        metadata_file = output_path / 'metadata.json'
        metadata_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"✓ 元数据文件已保存: {metadata_file}")
        
        # 保存信息摘要
        summary = {
            'updated_at': info['fetched_at'],
            'v2ray_subscription_url': 'https://c1a200.github.io/wv2ray/subscribe.txt',
            'clash_subscription_url': 'https://c1a200.github.io/wv2ray/clash.yaml',
            'v2ray_size_kb': round(len(v2ray_content) / 1024, 2),
            'clash_size_kb': round(len(clash_content) / 1024, 2),
            'format': 'v2ray (base64, upstream original) + clash (yaml)',
            'instructions': [
                '1. 在 v2ray 客户端中添加远程订阅',
                '2. 订阅地址: https://c1a200.github.io/wv2ray/subscribe.txt',
                '3. 在 clash/Clash Meta 中添加远程订阅: https://c1a200.github.io/wv2ray/clash.yaml',
                '4. 订阅每天自动更新（北京时间每天下午3点）'
            ]
        }
        
        summary_file = output_path / 'summary.json'
        summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"✓ 摘要文件已保存: {summary_file}")
        
        print("\n✅ 所有文件生成成功！")
        print(f"📌 固定订阅链接: https://c1a200.github.io/wv2ray/subscribe.txt")
        
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
