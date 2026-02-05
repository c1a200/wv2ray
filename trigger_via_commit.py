#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过空提交自动触发工作流的替代方案
"""

import subprocess
import sys

def trigger_via_empty_commit():
    """通过提交空提交来触发工作流"""
    
    print("🔄 通过空提交触发工作流...\n")
    
    try:
        # 创建空提交
        result = subprocess.run(
            ['git', 'commit', '--allow-empty', '-m', 'trigger: 运行 GitHub Actions 工作流'],
            capture_output=True,
            text=True,
            cwd='E:\\pyprojects\\wzndn'
        )
        
        if result.returncode != 0:
            print(f"❌ 创建提交失败: {result.stderr}")
            return False
        
        print("✓ 空提交已创建")
        print(f"  {result.stdout.strip()}\n")
        
        # 推送到 GitHub
        print("📤 正在推送到 GitHub...")
        result = subprocess.run(
            ['git', 'push'],
            capture_output=True,
            text=True,
            cwd='E:\\pyprojects\\wzndn'
        )
        
        if result.returncode != 0:
            print(f"❌ 推送失败: {result.stderr}")
            return False
        
        print("✓ 已推送到 GitHub\n")
        print("✅ 工作流应该会自动运行！")
        print("\n📊 查看进度:")
        print("   https://github.com/c1a200/wv2ray/actions\n")
        
        return True
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False

if __name__ == '__main__':
    success = trigger_via_empty_commit()
    sys.exit(0 if success else 1)
