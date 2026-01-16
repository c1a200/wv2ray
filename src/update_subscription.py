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

from fetcher import AggregatorFetcher, V2rayFormatter


def save_subscription_files(output_dir: str = '.'):
    """获取并保存订阅文件"""
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    try:
        # 获取订阅信息
        fetcher = AggregatorFetcher()
        print("📥 正在从 GitHub Issue 获取订阅信息...")
        info = fetcher.get_subscription_info()
        
        print(f"✓ Token: {info['token'][:10]}...{info['token'][-5:]}")
        print(f"✓ API URL: {info['api_url']}")
        
        # 构建订阅 URL
        subscribe_url = fetcher.build_subscribe_url(
            token=info['token'],
            api_url=info['api_url']
        )
        
        # 获取订阅内容
        print("📥 正在获取订阅内容...")
        subscription_content = fetcher.fetch_subscription_content(subscribe_url)
        
        # 转换为 v2ray 格式
        formatter = V2rayFormatter()
        v2ray_subscription = formatter.format_to_v2ray_subscription(
            subscription_content,
            fetch_time=info['fetched_at']
        )
        
        # 保存订阅文件（base64 格式）
        subscribe_file = output_path / 'subscribe.txt'
        subscribe_file.write_text(v2ray_subscription, encoding='utf-8')
        print(f"✓ 订阅文件已保存: {subscribe_file}")
        
        # 保存订阅元数据
        metadata = {
            'token': info['token'],
            'api_url': info['api_url'],
            'subscribe_url': subscribe_url,
            'fetched_at': info['fetched_at'],
            'subscription_file': 'subscribe.txt',
            'github_pages_url': 'https://c1a200.github.io/wv2ray/subscribe.txt'
        }
        
        metadata_file = output_path / 'metadata.json'
        metadata_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"✓ 元数据文件已保存: {metadata_file}")
        
        # 保存信息摘要
        summary = {
            'updated_at': info['fetched_at'],
            'subscription_url': 'https://c1a200.github.io/wv2ray/subscribe.txt',
            'subscription_size_kb': round(len(v2ray_subscription) / 1024, 2),
            'format': 'v2ray (base64)',
            'instructions': [
                '1. 在 v2ray 客户端中添加远程订阅',
                '2. 订阅地址: https://c1a200.github.io/wv2ray/subscribe.txt',
                '3. 订阅每天自动更新（北京时间每天下午3点）'
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
    # 输出目录为当前目录
    output_dir = os.path.dirname(os.path.abspath(__file__))
    success = save_subscription_files(output_dir)
    sys.exit(0 if success else 1)
