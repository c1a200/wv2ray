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
import urllib.request
from urllib.parse import urlencode, quote
from typing import Dict, Optional, List
from datetime import datetime


class AggregatorFetcher:
    """从 GitHub Issue 获取 aggregator 订阅信息（动态抓取，无默认值）"""
    
    ISSUE_URL = "https://github.com/wzdnzd/aggregator/issues/91"
    ISSUE_API_URL = "https://api.github.com/repos/wzdnzd/aggregator/issues/91"
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        # DEBUG_FETCH=true 时输出非敏感诊断信息
        self.debug = os.getenv('DEBUG_FETCH', '').lower() in {'1', 'true', 'yes', 'y'}
        self.last_source = ""
        self.last_url = ""

    def _content_has_token(self, content: str) -> bool:
        try:
            return bool(self.extract_token(content))
        except Exception:
            return False

    def _fetch_text_via_urllib(self, url: str) -> str:
        """当 requests 在特定环境返回空响应时，使用 urllib 兜底。"""
        req = urllib.request.Request(
            url,
            headers={'User-Agent': self.session.headers.get('User-Agent', 'Mozilla/5.0')},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = resp.read()
        return data.decode('utf-8', errors='ignore')
    
    def fetch_issue_content(self) -> str:
        """获取 GitHub Issue 页面内容"""
        combined = ""
        try:
            # 优先使用 GitHub API 获取 Issue 与评论内容（避免 HTML 中信息被脚本渲染）
            api_headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            issue_resp = self.session.get(self.ISSUE_API_URL, headers=api_headers, timeout=self.timeout)
            issue_resp.raise_for_status()
            issue_data = issue_resp.json()

            parts = [issue_data.get("body") or ""]

            comments_url = issue_data.get("comments_url")
            if comments_url:
                # 处理评论分页，避免 token 出现在后续页面时漏抓
                page = 1
                while True:
                    paged_url = f"{comments_url}?per_page=100&page={page}"
                    comments_resp = self.session.get(paged_url, headers=api_headers, timeout=self.timeout)
                    comments_resp.raise_for_status()
                    items = comments_resp.json() or []
                    for item in items:
                        parts.append(item.get("body") or "")
                    # 没有更多评论时退出
                    if len(items) < 100:
                        break
                    page += 1

            combined = "\n".join(parts).strip()
            if combined and self._content_has_token(combined):
                if self.debug:
                    print(f"[DEBUG] api_combined_len={len(combined)} token_found=True")
                self.last_source = "api"
                self.last_url = self.ISSUE_API_URL
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
                self.last_source = "html"
                self.last_url = self.ISSUE_URL
                return html
            # 尝试 plain=1 版本（某些场景下更易包含明文）
            plain_url = f"{self.ISSUE_URL}?plain=1"
            plain_resp = self.session.get(plain_url, timeout=self.timeout)
            if plain_resp.ok:
                plain_html = plain_resp.text
                if self.debug:
                    print(f"[DEBUG] html_plain_len={len(plain_html)} token_found={self._content_has_token(plain_html)}")
                if self._content_has_token(plain_html):
                    self.last_source = "html_plain"
                    self.last_url = plain_url
                    return plain_html
            # HTML 未包含 token 时，返回 API 内容兜底
            if combined:
                self.last_source = "api_fallback"
                self.last_url = self.ISSUE_API_URL
                return combined
            self.last_source = "html_fallback"
            self.last_url = self.ISSUE_URL
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
            preview = content[:500].replace('\n', ' ')
            print(f"[DEBUG] token_not_found source={self.last_source} url={self.last_url} len={len(content)} preview={preview}")
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

    def _build_converted_url(self, source_url: str, target: str,
                             minimal: bool = False) -> Optional[str]:
        """根据环境变量构建 subconverter 转换 URL。未配置时返回 None。"""
        converter_base = (os.getenv('SUBCONVERTER_URL') or '').strip()
        if not converter_base:
            return None

        # 支持把根地址自动补全为 /sub，也支持用户自行填写完整 /sub 路径
        base = converter_base.rstrip('/')
        if base.endswith('/sub'):
            sub_url = base
        else:
            sub_url = f"{base}/sub"

        target_v2ray = (os.getenv('SUBCONVERTER_TARGET_V2RAY') or 'v2ray').strip()
        target_clash = (os.getenv('SUBCONVERTER_TARGET_CLASH') or 'clash').strip()
        convert_target = target_v2ray if target == 'v2ray' else target_clash

        query = {
            'target': convert_target,
            'url': source_url,
        }
        if not minimal:
            insert = (os.getenv('SUBCONVERTER_INSERT') or 'false').strip()
            emoji = (os.getenv('SUBCONVERTER_EMOJI') or 'true').strip()
            list_value = (os.getenv('SUBCONVERTER_LIST') or 'false').strip()
            query.update({
                'insert': insert,
                'emoji': emoji,
                'list': list_value,
            })
        # 让 URL 参数编码行为与 subconverter 文档约定保持一致。
        return f"{sub_url}?{urlencode(query, quote_via=quote, safe='')}"

    def _raise_if_error_payload(self, content: str, url: str) -> None:
        """识别上游返回的 JSON 错误，避免把错误信息发布成订阅文件。"""
        stripped = content.strip()
        if not stripped.startswith('{'):
            return

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return

        if isinstance(payload, dict) and (payload.get('success') is False or payload.get('code')):
            code = payload.get('code', 'unknown')
            message = payload.get('message', 'unknown error')
            raise Exception(
                f"上游接口返回错误 payload，未生成订阅文件: code={code}, message={message}, url={url}"
            )

    def _validate_subscription_content(self, content: str, target: str, url: str) -> str:
        """校验返回内容是否看起来像真实订阅，而不是错误页或空数据。"""
        stripped = content.strip()
        if not stripped:
            raise Exception(f"上游接口返回空内容: {url}")

        self._raise_if_error_payload(stripped, url)

        if target == 'v2ray':
            try:
                decoded = base64.b64decode(stripped, validate=True).decode('utf-8', errors='ignore')
            except Exception as exc:
                preview = stripped[:160].replace('\n', ' ')
                raise Exception(
                    f"v2ray 订阅内容不是合法 base64，疑似被风控或返回了错误页: {preview}"
                ) from exc

            nodes = [line.strip() for line in decoded.splitlines() if line.strip() and not line.startswith('#')]
            supported_prefixes = ('vmess://', 'vless://', 'trojan://', 'ss://', 'ssr://', 'hysteria://', 'hysteria2://', 'tuic://')
            if not nodes or not any(line.startswith(supported_prefixes) for line in nodes):
                preview = decoded[:200].replace('\n', ' ')
                raise Exception(f"v2ray 订阅内容校验失败，未发现有效节点: {preview}")
            return stripped

        if target == 'clash':
            markers = ('proxies:', 'proxy-groups:', 'mixed-port:', 'port:')
            if not any(marker in stripped for marker in markers):
                preview = stripped[:200].replace('\n', ' ')
                raise Exception(f"clash 订阅内容校验失败，未发现 YAML 关键字段: {preview}")
            return content

        return content
    
    def fetch_subscription_content(self, url: str, target: str = 'v2ray') -> str:
        """获取订阅内容"""
        request_url = self._build_converted_url(url, target) or url
        minimal_url = self._build_converted_url(url, target, minimal=True)

        def _try_minimal_once() -> Optional[str]:
            if not (request_url != url and minimal_url and minimal_url != request_url):
                return None

            if self.debug:
                print('[DEBUG] converter_retry_with_minimal_query=true')
                print(f"[DEBUG] converted_url_minimal={minimal_url}")

            retry_resp = self.session.get(minimal_url, timeout=self.timeout)
            retry_resp.raise_for_status()
            retry_resp.encoding = 'utf-8'
            return self._validate_subscription_content(
                retry_resp.text,
                target=target,
                url=minimal_url,
            )

        try:
            if self.debug and request_url != url:
                print(f"[DEBUG] converter_enabled target={target}")
                print(f"[DEBUG] source_url={url}")
                print(f"[DEBUG] converted_url={request_url}")

            response = self.session.get(request_url, timeout=self.timeout)
            response.raise_for_status()
            # 显式指定 UTF-8 编码，确保正确处理中文字符
            response.encoding = 'utf-8'
            response_text = response.text
            if request_url != url and not (response_text or '').strip():
                if self.debug:
                    print('[DEBUG] converter_empty_response_retry_via_urllib=true')
                response_text = self._fetch_text_via_urllib(request_url)

            try:
                return self._validate_subscription_content(
                    response_text,
                    target=target,
                    url=request_url,
                )
            except Exception:
                minimal_result = _try_minimal_once()
                if minimal_result is not None:
                    return minimal_result
                raise

        except requests.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            should_retry_minimal = status_code == 400

            if should_retry_minimal:
                try:
                    minimal_result = _try_minimal_once()
                    if minimal_result is not None:
                        return minimal_result
                except requests.RequestException:
                    pass

            if request_url != url:
                try:
                    if self.debug:
                        print('[DEBUG] converter_http_error_retry_via_urllib=true')
                    fallback_text = self._fetch_text_via_urllib(request_url)
                    return self._validate_subscription_content(
                        fallback_text,
                        target=target,
                        url=request_url,
                    )
                except Exception:
                    pass

            body_preview = ''
            if e.response is not None and e.response.text:
                body_preview = e.response.text[:300].replace('\n', ' ')

            detail = f"获取订阅内容失败: HTTP {status_code}"
            if body_preview:
                detail += f", body={body_preview}"
            detail += f", url={request_url}"
            raise Exception(detail) from e

        except requests.RequestException as e:
            if request_url != url:
                try:
                    if self.debug:
                        print('[DEBUG] converter_request_exception_retry_via_urllib=true')
                    fallback_text = self._fetch_text_via_urllib(request_url)
                    return self._validate_subscription_content(
                        fallback_text,
                        target=target,
                        url=request_url,
                    )
                except Exception:
                    pass
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
