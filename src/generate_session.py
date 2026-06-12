#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 会话生成器
本地运行此脚本以登录您的 Telegram，并生成适用于 GitHub Actions (StringSession) 的会话密钥字符串。
"""

import sys
import os
import asyncio
import subprocess
from pathlib import Path

# 确保控制台输出使用 UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 自动安装 Telethon
try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("📥 正在安装依赖库 Telethon...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "telethon"])
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except Exception as e:
        print(f"❌ 安装 Telethon 失败: {e}")
        sys.exit(1)

BASE_DIR = Path(__file__).parent.parent
ENV_FILE = BASE_DIR / '.env'


def load_env_vars() -> dict:
    vars_dict = {}
    if ENV_FILE.exists():
        try:
            for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    vars_dict[k.strip()] = v.strip()
        except Exception:
            pass
    return vars_dict


def append_to_env(key: str, val: str):
    """保存或更新本地的 .env 文件。"""
    current = load_env_vars()
    current[key] = val
    
    lines = []
    lines.append("# wv2ray Configuration")
    lines.append("# 请妥善保管此文件，切勿将其提交到 Git！")
    lines.append("")
    
    # 优先写入 API ID 和 Hash 以及 Session
    if 'TELEGRAM_API_ID' in current:
        lines.append(f"TELEGRAM_API_ID={current.pop('TELEGRAM_API_ID')}")
    if 'TELEGRAM_API_HASH' in current:
        lines.append(f"TELEGRAM_API_HASH={current.pop('TELEGRAM_API_HASH')}")
    if 'TELEGRAM_SESSION' in current:
        lines.append(f"TELEGRAM_SESSION={current.pop('TELEGRAM_SESSION')}")
    lines.append("")
    
    for k, v in sorted(current.items()):
        lines.append(f"{k}={v}")
        
    try:
        ENV_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f"✓ 已保存至 .env 文件中。")
    except Exception as e:
        print(f"❌ 写入 .env 失败: {e}")


async def main():
    print("=" * 60)
    print("🔑 Telegram StringSession 会话生成器")
    print("=" * 60)
    
    env_vars = load_env_vars()
    api_id = env_vars.get('TELEGRAM_API_ID')
    api_hash = env_vars.get('TELEGRAM_API_HASH')
    
    if not api_id or not api_hash:
        print("💡 请先输入您的 Telegram API 密钥（可从 my.telegram.org 免费获取）:")
        try:
            api_id = input("API ID (数字): ").strip()
            api_hash = input("API HASH (字符串): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n已取消。")
            return
            
        if not api_id or not api_hash:
            print("❌ API ID 和 API HASH 不能为空！")
            return
            
        append_to_env('TELEGRAM_API_ID', api_id)
        append_to_env('TELEGRAM_API_HASH', api_hash)
    
    print("🔄 正在初始化客户端，准备进行 Telegram 授权登录...")
    # 使用 StringSession 进行无文件会话初始化
    client = TelegramClient(StringSession(), int(api_id), api_hash)
    
    try:
        await client.connect()
    except Exception as e:
        print(f"❌ 无法连接至 Telegram: {e}")
        print("提示: 请检查本地代理或网络设置。")
        return
        
    if not await client.is_user_authorized():
        try:
            phone = input("请输入您的 Telegram 绑定手机号 (格式如 +86138xxxx): ").strip()
            await client.start(phone=phone)
        except Exception as e:
            print(f"❌ 登录授权失败: {e}")
            return
            
    print("✅ 登录成功！")
    
    # 导出 session 文本
    session_str = client.session.save()
    
    print("\n" + "=" * 60)
    print("🎉 您的 TELEGRAM_SESSION 会话字符串生成成功：")
    print("=" * 60)
    print(session_str)
    print("=" * 60 + "\n")
    
    print("💡 接下来您可以：")
    print("1. 复制上面整行包含字母数字的字符串。")
    print("2. 登录您的 GitHub 仓库 -> Settings -> Secrets and variables -> Actions。")
    print("3. 分别添加以下三个 Secrets:")
    print("   - 密钥名: TELEGRAM_API_ID   值: (您的 API ID)")
    print("   - 密钥名: TELEGRAM_API_HASH 值: (您的 API HASH)")
    print("   - 密钥名: TELEGRAM_SESSION  值: (复制的这一长串会话字符串)")
    print("\n完成之后，您的 GitHub Action 即可实现全自动云端同步抓取，无需本地电脑运行！")
    
    # 自动保存到本地 .env 以备本地测试
    append_to_env('TELEGRAM_SESSION', session_str)
    
    await client.disconnect()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已取消操作。")
        sys.exit(1)
