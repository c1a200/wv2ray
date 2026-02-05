#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 GitHub API 触发工作流
需要设置 GITHUB_TOKEN 环境变量
"""

import os
import requests
import sys

def trigger_workflow():
    """触发 GitHub Actions 工作流"""
    
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        print("❌ 错误: 需要设置 GITHUB_TOKEN 环境变量")
        print("   请在 GitHub 设置中生成一个 Personal Access Token")
        print("   然后设置: $env:GITHUB_TOKEN = 'your_token'")
        return False
    
    owner = 'c1a200'
    repo = 'wv2ray'
    workflow_id = 'update-subscription.yml'  # 工作流文件名
    
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
    
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    
    data = {
        'ref': 'main'  # 指定要在哪个分支上运行
    }
    
    print(f"📤 正在触发工作流: {workflow_id}")
    print(f"   仓库: {owner}/{repo}")
    print(f"   分支: main\n")
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        
        if response.status_code == 204:
            print("✅ 工作流已成功触发！")
            print("\n📊 查看进度:")
            print(f"   https://github.com/{owner}/{repo}/actions")
            return True
        elif response.status_code == 401:
            print("❌ 认证失败: Token 无效或已过期")
            return False
        elif response.status_code == 404:
            print("❌ 工作流未找到")
            print(f"   URL: {url}")
            return False
        else:
            print(f"❌ 错误: HTTP {response.status_code}")
            print(f"   响应: {response.text}")
            return False
            
    except requests.RequestException as e:
        print(f"❌ 网络错误: {e}")
        return False

if __name__ == '__main__':
    success = trigger_workflow()
    sys.exit(0 if success else 1)
