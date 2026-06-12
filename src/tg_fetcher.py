#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 订阅抓取器
通过 Telethon 模拟用户登录，向 @xmsubbot 发送 /start，获取最新带有 token 的订阅地址。
自动更新本地的 .env 配置文件，并触发订阅生成脚本。
"""

import sys
import os
import re
import asyncio
import subprocess
from pathlib import Path

# 确保控制台输出使用 UTF-8 编码，防止 Windows 控制台 Unicode 报错
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 检查并安装依赖
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
        print(f"❌ 安装 Telethon 失败，请手动执行: pip install telethon. 错误信息: {e}")
        sys.exit(1)


# 配置与路径
BASE_DIR = Path(__file__).parent.parent
ENV_FILE = BASE_DIR / '.env'
SESSION_FILE = BASE_DIR / 'wv2ray_tg'


def load_env_vars() -> dict:
    """从 .env 加载现有的环境变量。"""
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


def write_env_vars(updates: dict):
    """写入/更新 .env 文件。"""
    current_vars = load_env_vars()
    current_vars.update(updates)
    
    lines = []
    # 写入必要配置提示
    lines.append("# wv2ray Auto-Generated Configuration")
    lines.append("# 请妥善保管您的 Telegram API 密钥。不要提交此文件到 Git！")
    lines.append("")
    
    # 优先写入 API ID 和 Hash
    if 'TELEGRAM_API_ID' in current_vars:
        lines.append(f"TELEGRAM_API_ID={current_vars.pop('TELEGRAM_API_ID')}")
    if 'TELEGRAM_API_HASH' in current_vars:
        lines.append(f"TELEGRAM_API_HASH={current_vars.pop('TELEGRAM_API_HASH')}")
    lines.append("")
    
    # 写入抓取出的 URL
    if 'DIRECT_V2RAY_URL' in current_vars:
        lines.append(f"DIRECT_V2RAY_URL={current_vars.pop('DIRECT_V2RAY_URL')}")
    if 'DIRECT_CLASH_URL' in current_vars:
        lines.append(f"DIRECT_CLASH_URL={current_vars.pop('DIRECT_CLASH_URL')}")
    lines.append("")
    
    # 写入其余变量
    for k, v in sorted(current_vars.items()):
        lines.append(f"{k}={v}")
        
    try:
        ENV_FILE.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(f"✓ 配置文件已更新: {ENV_FILE}")
    except Exception as e:
        print(f"❌ 写入 .env 失败: {e}")


async def main():
    print("=" * 60)
    print("🤖 Telegram 订阅地址自动抓取同步工具")
    print("=" * 60)
    
    # 1. 确保有 API ID 和 API HASH
    env_vars = load_env_vars()
    api_id = env_vars.get('TELEGRAM_API_ID')
    api_hash = env_vars.get('TELEGRAM_API_HASH')
    
    if not api_id or not api_hash:
        print("💡 首次运行，需要配置您的 Telegram API 凭证（可从 my.telegram.org 免费获取）:")
        try:
            api_id = input("请输入 Telegram API ID: ").strip()
            api_hash = input("请输入 Telegram API HASH: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n操作已取消。")
            return
            
        if not api_id or not api_hash:
            print("❌ API ID 和 API HASH 不能为空！")
            return
            
        # 写入保存
        write_env_vars({
            'TELEGRAM_API_ID': api_id,
            'TELEGRAM_API_HASH': api_hash
        })
    
    # 2. 初始化 Telethon 客户端并登录
    print("🔄 正在连接 Telegram 客户端...")
    session_str = os.getenv('TELEGRAM_SESSION', '').strip()
    
    if session_str:
        print("🔄 正在使用 TELEGRAM_SESSION 环境变量初始化客户端...")
        client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
    else:
        print("🔄 正在使用本地会话文件初始化客户端...")
        client = TelegramClient(str(SESSION_FILE), int(api_id), api_hash)
    
    try:
        await client.connect()
    except Exception as conn_err:
        print(f"❌ 无法连接至 Telegram: {conn_err}")
        print("提示: 请检查本地代理/网络设置。")
        return

    # 检查授权
    if not await client.is_user_authorized():
        if session_str:
            print("❌ 错误: 环境变量中的 TELEGRAM_SESSION 已失效或未授权！请运行 generate_session.py 重新生成。")
            return
            
        print("🔑 账号未登录，正在开启登录验证流程...")
        # Telethon 会自动在控制台提示输入手机号、验证码以及两步验证密码
        try:
            # 兼容 Windows CMD 输入
            phone = input("请输入您的 Telegram 绑定手机号 (格式如 +86138xxxx): ").strip()
            await client.start(phone=phone)
        except Exception as auth_err:
            print(f"❌ 授权登录失败: {auth_err}")
            return
            
    print("✅ Telegram 账号连接成功！")
    
    # 3. 发送消息给机器人并等待回复
    bot_username = 'xmsubbot'
    print(f"📤 正在向 @{bot_username} 发送指令...")
    
    try:
        await client.send_message(bot_username, '/start')
    except Exception as send_err:
        print(f"❌ 发送消息失败: {send_err}")
        return
        
    print("⏳ 等待机器人回复 (最长等待 15 秒)...")
    
    reply_text = None
    for attempt in range(15):
        await asyncio.sleep(1)
        # 抓取最近的一条消息
        messages = await client.get_messages(bot_username, limit=1)
        if messages:
            latest_msg = messages[0]
            # 排除我们发出的消息，并且消息应该有文本内容
            if not latest_msg.out and latest_msg.text:
                reply_text = latest_msg.text
                break
                
    if not reply_text:
        print("❌ 等待超时，未收到机器人的回复。")
        return
        
    print("📥 成功获取机器人回复，内容预览:")
    print("-" * 40)
    print("\n".join(reply_text.splitlines()[:10]))
    print("..." if len(reply_text.splitlines()) > 10 else "")
    print("-" * 40)
    
    # 4. 解析订阅链接
    clash_url = None
    v2ray_url = None
    
    # 使用正则表达式提取 Clash 和 v2ray 的 URL
    clash_match = re.search(r'(https?://\S+/clash\?token=\w+)', reply_text)
    v2ray_match = re.search(r'(https?://\S+/v2ray\?token=\w+)', reply_text)
    
    # 兜底通用匹配模式（防格式稍微变动）
    if not clash_match:
        clash_match = re.search(r'(https?://\S+/clash\S*)', reply_text)
    if not v2ray_match:
        v2ray_match = re.search(r'(https?://\S+/v2ray\S*)', reply_text)
        
    if clash_match:
        clash_url = clash_match.group(1).strip()
    if v2ray_match:
        v2ray_url = v2ray_match.group(1).strip()
        
    if not clash_url or not v2ray_url:
        print("⚠️ 未能在回复中提取出完整的 Clash 或 V2ray 订阅地址。")
        print("请检查机器人回复格式是否更改，或者当前 token 是否生成失败。")
        return
        
    print(f"✓ 提取到 Clash 订阅: {clash_url}")
    print(f"✓ 提取到 V2ray 订阅: {v2ray_url}")
    
    # 5. 更新本地环境变量配置文件
    write_env_vars({
        'DIRECT_CLASH_URL': clash_url,
        'DIRECT_V2RAY_URL': v2ray_url
    })
    
    # 6. 关闭客户端连接
    await client.disconnect()
    
    # 7. 调用本地更新脚本，执行去重、纠偏和 HTML 生成
    print("\n🔄 正在触发本地订阅更新程序...")
    try:
        script_path = BASE_DIR / 'src' / 'update_subscription.py'
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        print(result.stdout)
        if result.returncode == 0:
            print("🎉 订阅与动态仪表盘已在本地同步更新完毕！")
            
            # 8. (提示/可选) 执行推送
            print("\n💡 提示: 如果您想立即推送到 GitHub 部署发布，可在终端运行:")
            print("   python trigger_via_commit.py")
        else:
            print(f"❌ 运行本地更新失败，错误信息:\n{result.stderr}")
    except Exception as update_err:
        print(f"❌ 触发本地更新失败: {update_err}")


if __name__ == '__main__':
    # 运行异步主逻辑
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n操作被用户中断。")
        sys.exit(1)
