#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 GitHub Issue 页面抓取 aggregator 订阅信息并转换为标准 v2ray 格式
"""

import re
import json
import os
import requests
import base64
from typing import Dict, Optional, List
from datetime import datetime


class AggregatorFetcher:
    """从 GitHub Issue 获取 aggregator 订阅信息（动态抓取，无默认值）"""
    
    ISSUE_URL = "https://github.com/wzdnzd/aggregator/issues/91"
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        # DEBUG_FETCH=true 时输出非敏感诊断信息
        self.debug = os.getenv('DEBUG_FETCH', '').lower() in {'1', 'true', 'yes', 'y'}

    def _content_has_token(self, content: str) -> bool:
        try:
            return bool(self.extract_token(content))
        except Exception:
            return False
    
    def fetch_issue_content(self) -> str:
        """获取 GitHub Issue 页面内容"""
        issue_api_url = "https://api.github.com/repos/wzdnzd/aggregator/issues/91"
        combined = ""
        try:
            # 优先使用 GitHub API 获取 Issue 与评论内容（避免 HTML 中信息被脚本渲染）
            api_headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            issue_resp = self.session.get(issue_api_url, headers=api_headers, timeout=self.timeout)
            issue_resp.raise_for_status()
            issue_data = issue_resp.json()

            parts = [issue_data.get("body") or ""]

            comments_url = issue_data.get("comments_url")
            if comments_url:
                comments_resp = self.session.get(comments_url, headers=api_headers, timeout=self.timeout)
                comments_resp.raise_for_status()
                for item in comments_resp.json() or []:
                    parts.append(item.get("body") or "")

            combined = "\n".join(parts).strip()
            if combined and self._content_has_token(combined):
                if self.debug:
                    print(f"[DEBUG] api_combined_len={len(combined)} token_found=True")
                return combined
            if self.debug:
                print(f"[DEBUG] api_combined_len={len(combined)} token_found=False")

        except requests.RequestException:
            # API 失败则回退到 HTML 抓取
            pass

        try:
            response = self.session.get(self.ISSUE_URL, timeout=self.timeout)
            response.raise_for_status()
            html = response.text
            if self.debug:
                print(f"[DEBUG] html_len={len(html)} token_found={self._content_has_token(html)}")
            if self._content_has_token(html):
                return html
            # HTML 未包含 token 时，返回 API 内容兜底
            if combined:
                return combined
            return html
        except requests.RequestException as e:
            raise Exception(f"获取 Issue 页面失败: {e}")
    
    def extract_token(self, content: str) -> Optional[str]:
        """从页面内容中提取 token"""
        # 优先从表格行提取（HTML 格式）
        table_pattern = r'<td>\s*token\s*</td>.*?<code[^>]*>([A-Za-z0-9_\-+.]{8,128})</code>'
        match = re.search(table_pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)

        # Issue body 中的 details/summary 结构（Markdown 或渲染后的 HTML）
        details_patterns = [
            r'<details>\s*<summary>\s*点击查看最新密钥\s*</summary>\s*([A-Za-z0-9_\-+.]{8,128})\s*</details>',
            r'<details>\s*<summary>\s*.*?密钥.*?\s*</summary>\s*([A-Za-z0-9_\-+.]{8,128})\s*</details>',
            r'<details>\s*<summary>\s*点击查看最新密钥\s*</summary>\s*([A-Za-z0-9_\-+.]{8,128})',
            r'点击查看最新密钥\s*</summary>\s*([A-Za-z0-9_\-+.]{8,128})\s*</details>',
        ]
        for pattern in details_patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1)

        # Markdown 表格里包含 details 的情况
        md_details_pattern = r'\|\s*token\s*\|.*?<details>.*?</summary>\s*([A-Za-z0-9_\-+.]{8,128})\s*</details>'
        match = re.search(md_details_pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
        
        # Markdown 格式兜底（如评论或 issue body）
        md_pattern = r'\|\s*token\s*\|.*?\|\s*`?([A-Za-z0-9_\-+.]{8,128})`?\s*\|'
        match = re.search(md_pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
        
        # 通用格式兜底
        patterns = [
            r'token=([A-Za-z0-9_\-+.]{8,128})',
            r'token["\s:=]+([A-Za-z0-9_\-+.]{8,128})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def extract_api_url(self, content: str) -> Optional[str]:
        """从页面内容中提取 API 地址"""
        # 优先从"在线服务接口地址"后提取完整 URL
        context_pattern = r'在线服务接口地址.*?(https://[^\s<>"]+/api/v1/subscribe[^\s<>"]*)'
        match = re.search(context_pattern, content, re.DOTALL)
        if match:
            url = match.group(1)
            # 移除示例参数（如 ?token=xxx&target=xxx）
            base_url = url.split('?')[0]
            return base_url
        
        # 通用格式兜底
        pattern = r'https://[^\s\"<>]+/api/v1/subscribe'
        match = re.search(pattern, content)
        if match:
            url = match.group(0)
            return url.split('?')[0]
        
        return None
    
    def get_subscription_info(self) -> Dict:
        """获取订阅信息（每次实时从 Issue 页面动态抓取）"""
        content = self.fetch_issue_content()
        
        token = self.extract_token(content)
        api_url = self.extract_api_url(content)

        # 必须从页面抓取到 token 和 API URL，不使用任何默认值或缓存
        if not token:
            raise Exception("无法从 Issue 页面提取 token，请检查页面格式是否变化")
        
        if not api_url:
            raise Exception("无法从 Issue 页面提取 API URL，请检查页面格式是否变化")
        
        return {
            'token': token,
            'api_url': api_url,
            'fetched_at': datetime.utcnow().isoformat() + 'Z'
        }
    
    def build_subscribe_url(self, token: str, api_url: str, target: str = 'v2ray') -> str:
        """构建订阅 URL（必须提供 api_url，不使用默认值）"""
        if not api_url:
            raise ValueError("api_url 不能为空，必须从 Issue 页面动态获取")
        
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
        
        print(f"Token: {info['token']}")
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
