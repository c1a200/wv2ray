#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 GitHub Issue 页面抓取 aggregator 订阅信息并转换为标准 v2ray 格式
"""

import re
import json
import requests
import base64
from typing import Dict, Optional, List
from datetime import datetime


class AggregatorFetcher:
    """从 GitHub Issue 获取 aggregator 订阅信息"""
    
    ISSUE_URL = "https://github.com/wzdnzd/aggregator/issues/91"
    API_BASE = "https://qybndbviblvt.us-west-1.clawcloudrun.com/api/v1/subscribe"
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_issue_content(self) -> str:
        """获取 GitHub Issue 页面内容"""
        try:
            response = self.session.get(self.ISSUE_URL, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise Exception(f"获取 Issue 页面失败: {e}")
    
    def extract_token(self, content: str) -> Optional[str]:
        """从页面内容中提取 token"""
        # 查找 token 字段，支持多种格式
        patterns = [
            r'5[xwthvdjbvm1sbrwomlpcralcs5km568]{31}',  # 当前格式
            r'token["\s:=]+([a-z0-9]{32})',              # 通用格式
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1) if match.lastindex else match.group(0)
        
        return None
    
    def extract_api_url(self, content: str) -> Optional[str]:
        """从页面内容中提取 API 地址"""
        # 查找 API URL
        pattern = r'https://[^\s\"<>]+/api/v1/subscribe'
        match = re.search(pattern, content)
        return match.group(0) if match else None
    
    def get_subscription_info(self) -> Dict:
        """获取订阅信息"""
        content = self.fetch_issue_content()
        
        token = self.extract_token(content)
        api_url = self.extract_api_url(content)
        
        if not token or not api_url:
            raise Exception("无法从 Issue 页面提取 token 或 API URL")
        
        return {
            'token': token,
            'api_url': api_url,
            'fetched_at': datetime.utcnow().isoformat() + 'Z'
        }
    
    def build_subscribe_url(self, token: str, target: str = 'v2ray', 
                           api_url: str = None) -> str:
        """构建订阅 URL"""
        if api_url is None:
            api_url = self.API_BASE
        
        return f"{api_url}?token={token}&target={target}&list=false"
    
    def fetch_subscription_content(self, url: str) -> str:
        """获取订阅内容"""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            # 显式指定 UTF-8 编码，确保正确处理中文字符
            response.encoding = 'utf-8'
            return response.text
        except requests.RequestException as e:
            raise Exception(f"获取订阅内容失败: {e}")


class V2rayFormatter:
    """将代理节点转换为标准 v2ray 订阅格式"""
    
    def format_to_v2ray_subscription(self, content: str, 
                                     fetch_time: str = None) -> str:
        """
        将订阅内容转换为标准 v2ray 格式（base64 编码）
        
        Args:
            content: 订阅内容（通常是 base64 编码的）
            fetch_time: 获取时间
            
        Returns:
            base64 编码的 v2ray 订阅内容
        """
        try:
            # 如果已经是 base64 编码，直接解码
            decoded = base64.b64decode(content.strip()).decode('utf-8')
        except Exception:
            # 如果解码失败，直接使用原内容
            decoded = content
        
        # 处理和验证节点信息
        nodes = self._parse_nodes(decoded)
        
        # 添加时间戳注释
        if fetch_time:
            header = f"# Updated at: {fetch_time}\n"
        else:
            header = f"# Updated at: {datetime.utcnow().isoformat()}Z\n"
        
        formatted_content = header + decoded
        
        # 返回 base64 编码结果
        return base64.b64encode(formatted_content.encode('utf-8')).decode('utf-8')
    
    def _parse_nodes(self, content: str) -> List[str]:
        """解析节点列表"""
        nodes = []
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                nodes.append(line)
        return nodes
    
    def format_to_json(self, content: str) -> Dict:
        """将订阅信息格式化为 JSON"""
        try:
            decoded = base64.b64decode(content.strip()).decode('utf-8')
            node_count = len([l for l in decoded.split('\n') if l.strip() and not l.startswith('#')])
        except Exception:
            decoded = content
            node_count = 0
        
        return {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'node_count': node_count,
            'subscription': content,
            'format': 'v2ray'
        }


def main():
    """主函数"""
    try:
        # 获取订阅信息
        fetcher = AggregatorFetcher()
        print("正在从 GitHub Issue 获取订阅信息...")
        info = fetcher.get_subscription_info()
        
        print(f"Token: {info['token'][:10]}...{info['token'][-5:]}")
        print(f"API URL: {info['api_url']}")
        
        # 构建订阅 URL
        subscribe_url = fetcher.build_subscribe_url(
            token=info['token'],
            api_url=info['api_url']
        )
        print(f"订阅 URL: {subscribe_url}")
        
        # 获取订阅内容
        print("正在获取订阅内容...")
        subscription_content = fetcher.fetch_subscription_content(subscribe_url)
        
        # 转换为 v2ray 格式
        formatter = V2rayFormatter()
        v2ray_subscription = formatter.format_to_v2ray_subscription(
            subscription_content,
            fetch_time=info['fetched_at']
        )
        
        print(f"订阅内容长度: {len(v2ray_subscription)} 字符")
        
        # 输出结果
        result = {
            'source_info': info,
            'subscribe_url': subscribe_url,
            'subscription': v2ray_subscription
        }
        
        return result
        
    except Exception as e:
        print(f"错误: {e}")
        raise


if __name__ == '__main__':
    result = main()
    print(json.dumps({
        'success': True,
        'subscribe_url': result['subscribe_url'],
        'subscription_length': len(result['subscription'])
    }, indent=2))
