#!/usr/bin/env python3
"""Standalone web service for the subscription generator.

The service does not use GitHub Actions or GitHub Issues. Configure the two
upstream URLs with environment variables and it will refresh them periodically.
"""

import os
import json
import base64
import secrets
from urllib.parse import quote, urljoin
import sys
import threading
import time
import re
from urllib.parse import urlsplit, urlunsplit, urlencode
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for

ROOT = Path(__file__).resolve().parent
configured_data_dir = Path(os.getenv("DATA_DIR", "runtime_data"))
DATA_DIR = configured_data_dir if configured_data_dir.is_absolute() else ROOT / configured_data_dir
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    DATA_DIR = Path("/tmp/wv2ray-data")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "src"))
from update_subscription import save_subscription_files  # noqa: E402

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_urlsafe(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
refresh_lock = threading.Lock()
last_refresh = None
last_error = None
source_results = []
refresh_status = "idle"  # idle | running | ok | error
refresh_message = ""
CONFIG_FILE = DATA_DIR / "upstream.json"
PERSISTED_FILES = (
    "upstream.json",
    "subscribe.txt",
    "clash.yaml",
    "singbox.json",
    "nbsh.txt",
    "metadata.json",
    "summary.json",
)
webdav_last_error = None
webdav_restored_files = []
webdav_restored_at = None


def _admin_password():
    return (os.getenv("ADMIN_PASSWORD") or os.getenv("ADMIN_TOKEN") or "admin123").strip()


def _is_admin_request():
    password = _admin_password()
    if not password:
        return False
    return session.get("admin_authenticated") is True or secrets.compare_digest(
        request.headers.get("X-Admin-Token", ""), password
    )


def _admin_required():
    if _is_admin_request():
        return None
    return jsonify(ok=False, error="unauthorized"), 401


def get_config():
    provider_default = os.getenv("UPSTREAM_URL", "").strip()
    defaults = {
        "provider_url": provider_default,
        "provider_enabled": True,
        "v2ray_url": os.getenv("DIRECT_V2RAY_URL", "").strip(),
        "clash_url": os.getenv("DIRECT_CLASH_URL", "").strip(),
        "token": os.getenv("DIRECT_TOKEN", ""),
        "sources": [],
    }
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            for k in ("provider_url", "v2ray_url", "clash_url", "token"):
                if k in saved:
                    defaults[k] = str(saved[k])
            if "provider_enabled" in saved:
                defaults["provider_enabled"] = bool(saved.get("provider_enabled"))
            if isinstance(saved.get("sources"), list):
                clean_sources = []
                for item in saved["sources"]:
                    if not isinstance(item, dict):
                        continue
                    entry = dict(item)
                    entry["enabled"] = True if "enabled" not in entry else bool(entry.get("enabled"))
                    clean_sources.append(entry)
                defaults["sources"] = clean_sources
            # Migrate configurations saved before provider_url was introduced.
            if not defaults["provider_url"]:
                candidate = str(saved.get("v2ray_url") or saved.get("clash_url") or "")
                try:
                    derive_provider_urls(candidate)
                    defaults["provider_url"] = candidate
                except ValueError:
                    pass
    except (OSError, ValueError):
        pass
    return defaults


def _is_enabled(value, default=True):
    """Treat missing enabled flag as enabled for backward compatibility."""
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def derive_provider_urls(url):
    """Derive v2ray/clash siblings from a provider endpoint such as /singbox."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("provider_url must be an http(s) URL")
    parts = parsed.path.rstrip("/").split("/")
    if not parts or parts[-1].lower() not in {"clash", "v2ray", "singbox", "nbsh"}:
        raise ValueError("provider_url path must end with clash, v2ray, singbox, or nbsh")
    base = parts[:-1]
    def sibling(name):
        path = "/".join(base + [name])
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
    return sibling("v2ray"), sibling("clash")


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    sync_to_webdav()


def _webdav_base_url():
    # For Cloudreve accounts with "relative root" (e.g. /V2ray), use https://host/dav
    # and do NOT append /V2ray again, or files land in /V2ray/V2ray and restore fails.
    return (os.getenv("WEBDAV_URL") or "").strip().rstrip("/")


def _webdav_file_url(filename, base=None):
    """Join base folder + filename without urllib urljoin surprises."""
    base = (base or _webdav_base_url()).rstrip("/")
    name = Path(str(filename)).name
    return f"{base}/{quote(name)}"


def _webdav_auth():
    return (os.getenv("WEBDAV_USERNAME") or "", os.getenv("WEBDAV_PASSWORD") or "")


def _record_webdav_error(error):
    global webdav_last_error
    webdav_last_error = str(error)[:240] if error else ""


def _webdav_candidate_bases():
    """Return base URLs to try for restore (configured first, then sensible fallbacks)."""
    primary = _webdav_base_url()
    if not primary:
        return []
    bases = [primary]
    # If user set .../dav/V2ray while the WebDAV account root is already /V2ray,
    # also try the parent (.../dav).
    if primary.rstrip("/").lower().endswith("/v2ray"):
        parent = primary.rsplit("/", 1)[0]
        if parent and parent not in bases:
            bases.append(parent)
    # If user set plain .../dav, also try .../dav/V2ray (main-password + folder style).
    if primary.rstrip("/").lower().endswith("/dav"):
        nested = primary.rstrip("/") + "/V2ray"
        if nested not in bases:
            bases.append(nested)
    return bases


def restore_from_webdav():
    """Restore configuration and subscription files on startup.

    Never treat "nothing restored" as success without recording a warning, so the
    admin UI can show why the settings page is empty after a cold start.
    """
    global webdav_restored_files, webdav_restored_at
    webdav_restored_files = []
    webdav_restored_at = None
    if not _webdav_base_url():
        _record_webdav_error("WEBDAV_URL 未配置，重启后无法恢复数据")
        return 0

    import requests

    bases = _webdav_candidate_bases()
    timeout = int(os.getenv("WEBDAV_TIMEOUT_SECONDS", "20"))
    last_exc = None

    for base in bases:
        restored = []
        try:
            # Prefer a base that at least has upstream.json or any persisted file.
            probe = requests.get(
                _webdav_file_url("upstream.json", base=base),
                auth=_webdav_auth(),
                timeout=timeout,
            )
            if probe.status_code == 404:
                # Still try other files on this base in case only outputs exist.
                any_hit = False
                for filename in PERSISTED_FILES:
                    response = requests.get(
                        _webdav_file_url(filename, base=base),
                        auth=_webdav_auth(),
                        timeout=timeout,
                    )
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    (DATA_DIR / filename).write_bytes(response.content)
                    restored.append(filename)
                    any_hit = True
                if not any_hit:
                    continue
            else:
                probe.raise_for_status()
                (DATA_DIR / "upstream.json").write_bytes(probe.content)
                restored.append("upstream.json")
                for filename in PERSISTED_FILES:
                    if filename == "upstream.json":
                        continue
                    response = requests.get(
                        _webdav_file_url(filename, base=base),
                        auth=_webdav_auth(),
                        timeout=timeout,
                    )
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    (DATA_DIR / filename).write_bytes(response.content)
                    restored.append(filename)

            webdav_restored_files = restored
            webdav_restored_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            # Remember the working base for subsequent syncs in this process.
            os.environ["WEBDAV_URL"] = base
            if restored:
                _record_webdav_error("")
            else:
                _record_webdav_error(f"WebDAV 可访问但无文件: {base}")
            return len(restored)
        except requests.RequestException as exc:
            last_exc = exc
            continue

    if last_exc:
        _record_webdav_error(f"WebDAV 恢复失败: {last_exc}")
    else:
        tried = ", ".join(bases)
        _record_webdav_error(
            "WebDAV 未找到可恢复文件。请确认 WEBDAV_URL 与 Cloudreve「相对根目录」匹配："
            "专用密码根目录已是 /V2ray 时，URL 应是 https://host/dav ；"
            f"已尝试: {tried}"
        )
    return 0


def sync_to_webdav(delete_missing=False):
    """Upload local persisted files to WebDAV.

    By default this only PUTs files that exist locally. It does NOT delete remote
    files when local files are missing — that previously wiped Cloudreve after a
    failed restore on free Render restarts.
    """
    if not _webdav_base_url():
        return False
    import requests

    timeout = int(os.getenv("WEBDAV_TIMEOUT_SECONDS", "20"))
    try:
        uploaded = 0
        for filename in PERSISTED_FILES:
            path = DATA_DIR / filename
            target = _webdav_file_url(filename)
            if path.is_file():
                response = requests.put(
                    target, data=path.read_bytes(), auth=_webdav_auth(), timeout=timeout
                )
                response.raise_for_status()
                uploaded += 1
            elif delete_missing:
                response = requests.delete(target, auth=_webdav_auth(), timeout=timeout)
                if response.status_code not in {204, 404}:
                    response.raise_for_status()
        _record_webdav_error("" if uploaded or delete_missing else "本地无可同步文件")
        return True
    except requests.RequestException as exc:
        _record_webdav_error(f"WebDAV 同步失败: {exc}")
        return False


def _converter_url(source_url, target):
    base = os.getenv("SUBCONVERTER_URL", "https://subconverter-jboo.onrender.com/").rstrip("/")
    path = base if base.endswith("/sub") else f"{base}/sub"
    target = os.getenv("SUBCONVERTER_TARGET_V2RAY", "mixed") if target == "v2ray" else os.getenv("SUBCONVERTER_TARGET_CLASH", "clash")
    params = urlencode({"target": target, "url": source_url, "insert": "false", "emoji": "true", "list": "false"})
    return f"{path}?{params}"


def _fetch_converted(source_url, target):
    import requests
    response = requests.get(_converter_url(source_url, target), timeout=int(os.getenv("SUBCONVERTER_TIMEOUT_SECONDS", "45")),
                            headers={"User-Agent": "wv2ray-subscription-service/1.0"})
    response.raise_for_status()
    content = response.text.strip()
    if not content:
        raise ValueError(f"subconverter returned empty {target} content")
    return content


def _fetch_source(source_url):
    import requests
    response = requests.get(source_url, timeout=int(os.getenv("HTTP_TIMEOUT_SECONDS", "25")),
                            headers={"User-Agent": "wv2ray-subscription-service/1.0"})
    response.raise_for_status()
    return response.text.strip()


def _friendly_error(exc):
    text = str(exc)
    if "WinError 10013" in text or "手动访问套接字" in text:
        return "当前运行环境禁止访问外部网络"
    if "Max retries exceeded" in text or "NameResolutionError" in text:
        return "无法连接外部地址，请检查网络或订阅 URL"
    if "empty" in text.lower():
        return "转换服务没有返回可用节点"
    return text[:240]


def _decode_v2ray(content):
    raw = content.strip()
    try:
        decoded = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=False).decode("utf-8", errors="ignore")
        if "://" in decoded:
            return decoded
    except Exception:
        pass
    return raw


def _proxy_to_uri(proxy):
    """Build common v2rayN-compatible URIs when subconverter omits a node."""
    ptype = str(proxy.get("type", "")).lower()
    name = quote(str(proxy.get("name", "node")), safe="")
    server = proxy.get("server")
    port = proxy.get("port")
    if not server or not port:
        return None
    if ptype in {"http", "socks5", "socks"}:
        scheme = "http" if ptype == "http" else "socks"
        user = proxy.get("username") or ""
        password = proxy.get("password") or ""
        auth = f"{quote(str(user), safe='')}:{quote(str(password), safe='')}@" if user or password else ""
        return f"{scheme}://{auth}{server}:{port}#{name}"
    if ptype == "ss":
        method = proxy.get("cipher") or proxy.get("method")
        password = proxy.get("password")
        if not method or password is None:
            return None
        userinfo = base64.urlsafe_b64encode(f"{method}:{password}".encode()).decode().rstrip("=")
        return f"ss://{userinfo}@{server}:{port}#{name}"
    if ptype in {"hysteria2", "hy2"}:
        password = proxy.get("password") or proxy.get("auth")
        if password is None:
            return None
        params = []
        if proxy.get("sni"):
            params.append("sni=" + quote(str(proxy["sni"]), safe=""))
        if proxy.get("obfs"):
            params.append("obfs=" + quote(str(proxy["obfs"]), safe=""))
        if proxy.get("obfs-password") or proxy.get("obfs_password"):
            value = proxy.get("obfs-password") or proxy.get("obfs_password")
            params.append("obfs-password=" + quote(str(value), safe=""))
        query = ("?" + "&".join(params)) if params else ""
        return f"hysteria2://{quote(str(password), safe='')}@{server}:{port}{query}#{name}"
    if ptype == "trojan":
        password = proxy.get("password")
        if password is None:
            return None
        params = []
        sni = proxy.get("sni") or proxy.get("servername")
        if sni:
            params.append("sni=" + quote(str(sni), safe=""))
        if proxy.get("skip-cert-verify") or proxy.get("skip_cert_verify"):
            params.append("allowInsecure=1")
        query = ("?" + "&".join(params)) if params else ""
        return f"trojan://{quote(str(password), safe='')}@{server}:{port}{query}#{name}"
    if ptype == "vmess":
        uuid = proxy.get("uuid") or proxy.get("password")
        if not uuid:
            return None
        network = proxy.get("network") or "tcp"
        tls_flag = "tls" if proxy.get("tls") in (True, "true", "tls") else ""
        payload = {
            "v": "2",
            "ps": str(proxy.get("name", "node")),
            "add": str(server),
            "port": str(port),
            "id": str(uuid),
            "aid": str(proxy.get("alterId") or proxy.get("alter_id") or 0),
            "scy": proxy.get("cipher") or "auto",
            "net": network,
            "type": "none",
            "host": proxy.get("servername") or proxy.get("host") or "",
            "path": proxy.get("path") or "",
            "tls": tls_flag,
            "sni": proxy.get("servername") or proxy.get("sni") or "",
        }
        encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
        return f"vmess://{encoded}"
    if ptype == "vless":
        uuid = proxy.get("uuid") or proxy.get("password")
        if not uuid:
            return None
        params = ["encryption=" + quote(str(proxy.get("encryption") or "none"), safe="")]
        reality = proxy.get("reality-opts") or proxy.get("reality_opts") or {}
        security = "reality" if reality else ("tls" if proxy.get("tls") in (True, "true", "tls") else "none")
        params.append("security=" + security)
        if proxy.get("flow"):
            params.append("flow=" + quote(str(proxy["flow"]), safe=""))
        sni = proxy.get("servername") or proxy.get("sni")
        if sni:
            params.append("sni=" + quote(str(sni), safe=""))
        fp = proxy.get("client-fingerprint") or proxy.get("client_fingerprint")
        if fp:
            params.append("fp=" + quote(str(fp), safe=""))
        if isinstance(reality, dict):
            pbk = reality.get("public-key") or reality.get("public_key")
            sid = reality.get("short-id") or reality.get("short_id")
            if pbk:
                params.append("pbk=" + quote(str(pbk), safe=""))
            if sid is not None and str(sid) != "":
                params.append("sid=" + quote(str(sid), safe=""))
        if proxy.get("network"):
            params.append("type=" + quote(str(proxy["network"]), safe=""))
        query = "?" + "&".join(params)
        return f"vless://{quote(str(uuid), safe='')}@{server}:{port}{query}#{name}"
    return None


def _proxies_to_uris(proxies):
    return [uri for proxy in proxies if isinstance(proxy, dict)
            for uri in [_proxy_to_uri(proxy)] if uri]


def _proxies_to_singbox(proxies):
    outbounds = []
    for proxy in proxies:
        if not isinstance(proxy, dict) or not proxy.get("server") or not proxy.get("port"):
            continue
        ptype = str(proxy.get("type", "")).lower()
        base = {"tag": str(proxy.get("name", f"node-{len(outbounds) + 1}")),
                "server": proxy["server"], "server_port": int(proxy["port"])}
        if ptype == "http":
            base["type"] = "http"
            if proxy.get("username"):
                base["username"] = proxy["username"]
            if proxy.get("password"):
                base["password"] = proxy["password"]
        elif ptype in {"socks", "socks5"}:
            base["type"] = "socks"
            if proxy.get("username"):
                base["username"] = proxy["username"]
            if proxy.get("password"):
                base["password"] = proxy["password"]
        elif ptype == "ss":
            base.update(type="shadowsocks", method=proxy.get("cipher") or proxy.get("method"), password=proxy.get("password", ""))
        elif ptype in {"hysteria2", "hy2"}:
            base.update(type="hysteria2", password=proxy.get("password") or proxy.get("auth", ""))
            if proxy.get("sni"):
                base["tls"] = {"enabled": True, "server_name": proxy["sni"]}
        elif ptype == "trojan":
            base.update(type="trojan", password=proxy.get("password", ""))
            sni = proxy.get("sni") or proxy.get("servername")
            if sni:
                base["tls"] = {"enabled": True, "server_name": sni}
        elif ptype == "vless":
            base.update(type="vless", uuid=proxy.get("uuid") or proxy.get("password", ""))
            if proxy.get("flow"):
                base["flow"] = proxy["flow"]
            sni = proxy.get("servername") or proxy.get("sni")
            reality = proxy.get("reality-opts") or proxy.get("reality_opts") or {}
            if proxy.get("tls") or reality:
                tls = {"enabled": True}
                if sni:
                    tls["server_name"] = sni
                if isinstance(reality, dict) and (reality.get("public-key") or reality.get("public_key")):
                    tls["reality"] = {
                        "enabled": True,
                        "public_key": reality.get("public-key") or reality.get("public_key"),
                        "short_id": str(reality.get("short-id") or reality.get("short_id") or ""),
                    }
                base["tls"] = tls
        elif ptype == "vmess":
            base.update(
                type="vmess",
                uuid=proxy.get("uuid") or proxy.get("password", ""),
                alter_id=int(proxy.get("alterId") or proxy.get("alter_id") or 0),
                security=proxy.get("cipher") or "auto",
            )
        else:
            continue
        outbounds.append(base)
    return outbounds


def _unique_clash_name(name, existing_names, source_name):
    """Return a unique Clash proxy/group name without mutating base references."""
    name = str(name or "").strip()
    if not name:
        name = "node"
    if name not in existing_names:
        return name
    source = str(source_name or "source").strip() or "source"
    candidate = f"{name} [{source}]"
    index = 2
    while candidate in existing_names:
        candidate = f"{name} [{source} {index}]"
        index += 1
    return candidate


def _map_clash_group_ref(ref, proxy_name_map, group_name_map):
    if isinstance(ref, str):
        return proxy_name_map.get(ref, group_name_map.get(ref, ref))
    return ref


def _merge_extra_rules(base_rules, extra_rules, group_name_map, provider_name_map=None):
    """Merge extra-source rules without replacing the primary MATCH fallback."""
    provider_name_map = provider_name_map or {}
    if not isinstance(base_rules, list) or not isinstance(extra_rules, list):
        return base_rules

    def _rewrite_rule(rule):
        if not isinstance(rule, str):
            return rule
        if rule.startswith("RULE-SET,"):
            parts = rule.split(",")
            if len(parts) >= 2 and parts[1] in provider_name_map:
                parts[1] = provider_name_map[parts[1]]
            if len(parts) >= 3 and parts[2] in group_name_map:
                parts[2] = group_name_map[parts[2]]
            return ",".join(parts)
        parts = rule.rsplit(",", 1)
        if len(parts) == 2 and parts[1] in group_name_map:
            return f"{parts[0]},{group_name_map[parts[1]]}"
        return rule

    extra_rules = [rule for rule in extra_rules if isinstance(rule, str)]
    extra_rules = [_rewrite_rule(rule) for rule in extra_rules]
    match_index = next(
        (index for index, rule in enumerate(base_rules)
         if isinstance(rule, str) and rule.startswith("MATCH,")),
        None,
    )
    if match_index is None:
        return base_rules + extra_rules

    insert_rules = [rule for rule in extra_rules if not rule.startswith("MATCH,")]
    return base_rules[:match_index] + insert_rules + base_rules[match_index:]


def _merge_extra_clash_content(base_data, extra_data, source_name):
    """Merge enabled extra Clash sources into the generated Clash config.

    Node, group, and rule-provider names are kept unique because Clash
    proxy-groups, rules, and RULE-SET reference them by name. Extra-source
    groups, rule-providers, and rules are merged as well, while the primary
    subscription's MATCH fallback is preserved.
    """
    if not isinstance(base_data, dict):
        base_data = {"proxies": []}
    if not isinstance(extra_data, dict):
        return base_data

    base_data.setdefault("proxies", [])
    base_data.setdefault("proxy-groups", [])

    existing_proxy_names = {
        proxy.get("name") for proxy in base_data["proxies"] if isinstance(proxy, dict)
    }
    base_proxy_keys = {
        json.dumps({k: v for k, v in proxy.items() if k != "name"},
                   sort_keys=True, ensure_ascii=False)
        for proxy in base_data["proxies"] if isinstance(proxy, dict)
    }

    proxy_name_map = {}
    added_proxy_names = []
    for proxy in extra_data.get("proxies", []):
        if not isinstance(proxy, dict) or not proxy.get("name"):
            continue
        original_name = str(proxy["name"])
        key = json.dumps({k: v for k, v in proxy.items() if k != "name"},
                         sort_keys=True, ensure_ascii=False)
        if original_name in existing_proxy_names and key in base_proxy_keys:
            proxy_name_map[original_name] = original_name
            continue

        final_name = _unique_clash_name(original_name, existing_proxy_names, source_name)
        if final_name != original_name:
            proxy = dict(proxy)
            proxy["name"] = final_name
        base_data["proxies"].append(proxy)
        existing_proxy_names.add(final_name)
        base_proxy_keys.add(key)
        proxy_name_map[original_name] = final_name
        added_proxy_names.append(final_name)

    extra_groups = [
        group for group in extra_data.get("proxy-groups", []) if isinstance(group, dict)
    ]
    existing_group_names = {
        group.get("name") for group in base_data["proxy-groups"] if isinstance(group, dict)
    }
    group_name_map = {}
    for group in extra_groups:
        original_name = str(group.get("name") or "").strip()
        if not original_name:
            continue
        final_name = _unique_clash_name(original_name, existing_group_names, source_name)
        group_name_map[original_name] = final_name
        existing_group_names.add(final_name)

    for group in extra_groups:
        original_name = str(group.get("name") or "").strip()
        if not original_name or original_name not in group_name_map:
            continue
        merged_group = dict(group)
        merged_group["name"] = group_name_map[original_name]
        if isinstance(merged_group.get("proxies"), list):
            merged_group["proxies"] = [
                _map_clash_group_ref(ref, proxy_name_map, group_name_map)
                for ref in merged_group["proxies"]
            ]
        base_data["proxy-groups"].append(merged_group)

    provider_name_map = {}
    extra_providers = extra_data.get("rule-providers")
    if isinstance(extra_providers, dict) and extra_providers:
        base_data.setdefault("rule-providers", {})
        existing_provider_names = {
            str(name) for name in base_data["rule-providers"] if isinstance(name, str)
        }
        for provider_name, provider in extra_providers.items():
            final_name = _unique_clash_name(
                str(provider_name or "provider"), existing_provider_names, source_name
            )
            provider_name_map[provider_name] = final_name
            existing_provider_names.add(final_name)
            base_data["rule-providers"][final_name] = provider

    if extra_data.get("rules"):
        base_data.setdefault("rules", [])
        base_data["rules"] = _merge_extra_rules(
            base_data["rules"],
            extra_data["rules"],
            group_name_map,
            provider_name_map,
        )

    source_label = str(source_name or "extra").strip() or "extra"
    source_group_name = _unique_clash_name(
        source_label, existing_group_names, "source"
    )
    source_group_proxies = ["DIRECT"] + added_proxy_names + list(group_name_map.values())
    source_group_proxies = list(dict.fromkeys(source_group_proxies))
    source_group = {
        "name": source_group_name,
        "type": "select",
        "proxies": source_group_proxies,
    }
    base_data["proxy-groups"].append(source_group)
    existing_group_names.add(source_group_name)

    for group in base_data["proxy-groups"]:
        if isinstance(group, dict) and group.get("name") == "GLOBAL" and isinstance(
            group.get("proxies"), list
        ):
            if source_group_name not in group["proxies"]:
                group["proxies"].append(source_group_name)
            break

    return base_data


def _merge_converted_sources(config):
    """Convert configured sources to Clash and V2Ray, then merge and deduplicate."""
    global source_results
    import yaml

    source_results = []
    clash_file = DATA_DIR / "clash.yaml"
    v2ray_file = DATA_DIR / "subscribe.txt"
    clash_data = yaml.safe_load(clash_file.read_text(encoding="utf-8")) or {}
    if not isinstance(clash_data, dict):
        clash_data = {"proxies": []}
    clash_data.setdefault("proxies", [])
    base_nodes = [line.strip() for line in _decode_v2ray(v2ray_file.read_text(encoding="utf-8")).splitlines()
                  if line.strip() and "://" in line]
    v2_keys = set(base_nodes)

    for source in config.get("sources", []):
        name = source.get("name") or source.get("id") or "source"
        status = {"id": source.get("id"), "name": name, "ok": False,
                  "clash_added": 0, "v2ray_added": 0, "errors": [],
                  "enabled": True, "skipped": False}
        if not _is_enabled(source.get("enabled"), True):
            status["enabled"] = False
            status["skipped"] = True
            status["error"] = "已关闭，跳过聚合"
            source_results.append(status)
            continue
        converted_proxies = []
        try:
            if str(source.get("type", "")).lower() == "clash":
                converted_clash = yaml.safe_load(_fetch_source(source["url"])) or {}
            else:
                converted_clash = yaml.safe_load(_fetch_converted(source["url"], "clash")) or {}
            converted_proxies = converted_clash.get("proxies", []) if isinstance(converted_clash, dict) else []
            before_count = len(clash_data["proxies"])
            before_group_count = len(clash_data.get("proxy-groups", []))
            _merge_extra_clash_content(clash_data, converted_clash, name)
            status["clash_added"] = len(clash_data["proxies"]) - before_count
            status["clash_groups_added"] = len(clash_data.get("proxy-groups", [])) - before_group_count
        except Exception as exc:
            status["errors"].append("Clash: " + _friendly_error(exc))

        try:
            if str(source.get("type", "")).lower() == "clash":
                # Direct local fallback handles HTTP/SOCKS/SS/Hy2 without a converter.
                raise ValueError("Clash source uses local protocol conversion")
            converted_v2ray = _decode_v2ray(_fetch_converted(source["url"], "v2ray"))
            added_v2ray = 0
            for line in converted_v2ray.splitlines():
                line = line.strip()
                if line and "://" in line and line not in v2_keys:
                    base_nodes.append(line)
                    v2_keys.add(line)
                    added_v2ray += 1
            status["v2ray_added"] = added_v2ray
        except Exception as exc:
            if "local protocol conversion" not in str(exc):
                status["errors"].append("V2Ray: " + _friendly_error(exc))
        if status["v2ray_added"] == 0:
            # Some converter deployments omit HTTP/SOCKS/Hy2; use local URI fallback.
            fallback_nodes = _proxies_to_uris(converted_proxies)
            for line in fallback_nodes:
                if line not in v2_keys:
                    base_nodes.append(line)
                    v2_keys.add(line)
                    status["v2ray_added"] += 1
        status["ok"] = status["clash_added"] > 0 or status["v2ray_added"] > 0
        if status["errors"]:
            status["error"] = "; ".join(status["errors"])
        source_results.append(status)

    clash_file.write_text(yaml.safe_dump(clash_data, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    encoded = base64.b64encode("\n".join(base_nodes).encode("utf-8")).decode("ascii")
    v2ray_file.write_text(encoded, encoding="utf-8")
    (DATA_DIR / "nbsh.txt").write_text(encoded, encoding="utf-8")
    (DATA_DIR / "singbox.json").write_text(
        json.dumps({"outbounds": _proxies_to_singbox(clash_data["proxies"])}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _ensure_empty_outputs():
    (DATA_DIR / "subscribe.txt").write_text("", encoding="utf-8")
    (DATA_DIR / "clash.yaml").write_text("proxies: []\n", encoding="utf-8")
    (DATA_DIR / "nbsh.txt").write_text("", encoding="utf-8")
    (DATA_DIR / "singbox.json").write_text(
        json.dumps({"outbounds": []}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def refresh():
    global last_refresh, last_error, source_results, refresh_status, refresh_message
    if not refresh_lock.acquire(blocking=False):
        refresh_message = "刷新进行中，请稍候"
        return False
    refresh_status = "running"
    refresh_message = "刷新中..."
    try:
        # Issue variants are GitHub-dependent and are intentionally disabled.
        os.environ.setdefault("GENERATE_ISSUE_VARIANTS", "false")
        config = get_config()
        provider_enabled = _is_enabled(config.get("provider_enabled"), True)
        active_sources = [
            s for s in (config.get("sources") or [])
            if isinstance(s, dict)
            and _is_enabled(s.get("enabled"), True)
            and str(s.get("url", "")).startswith(("http://", "https://"))
        ]
        if config.get("provider_url") and provider_enabled:
            config["v2ray_url"], config["clash_url"] = derive_provider_urls(config["provider_url"])
        else:
            # Keep URL in saved config, but do not use disabled primary during refresh.
            config["v2ray_url"] = ""
            config["clash_url"] = ""
        if not config["v2ray_url"] and not config["clash_url"] and not active_sources:
            for filename in ("subscribe.txt", "clash.yaml", "nbsh.txt", "singbox.json", "metadata.json", "summary.json"):
                (DATA_DIR / filename).unlink(missing_ok=True)
            source_results = []
            sync_to_webdav(delete_missing=True)
            last_refresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            last_error = None
            refresh_status = "ok"
            refresh_message = "已清空订阅（未配置上游）"
            return True

        primary_error = None
        has_primary = bool(config["v2ray_url"] and config["clash_url"])
        if has_primary:
            os.environ["DIRECT_V2RAY_URL"] = config["v2ray_url"]
            os.environ["DIRECT_CLASH_URL"] = config["clash_url"]
            os.environ["DIRECT_TOKEN"] = config["token"]
            try:
                result = save_subscription_files(str(DATA_DIR))
                if result is not True:
                    primary_error = "主订阅抓取返回失败"
            except Exception as exc:
                primary_error = _friendly_error(exc)
                result = False
        else:
            # Sources-only mode starts clean instead of falling back to built-in URLs.
            _ensure_empty_outputs()
            result = True

        missing = [name for name in ("subscribe.txt", "clash.yaml") if not (DATA_DIR / name).is_file()]
        # Free hosts may block some primary domains; still merge extra sources when present.
        if missing:
            if active_sources:
                _ensure_empty_outputs()
            else:
                raise RuntimeError("上游抓取失败，未生成文件: " + ", ".join(missing))

        if config.get("sources"):
            _merge_converted_sources(config)

        missing = [name for name in ("subscribe.txt", "clash.yaml") if not (DATA_DIR / name).is_file()]
        if missing:
            raise RuntimeError("刷新后仍缺少文件: " + ", ".join(missing))

        sync_to_webdav()
        last_refresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if primary_error and not any(item.get("ok") for item in source_results):
            last_error = primary_error
            refresh_status = "error"
            refresh_message = primary_error
            return False
        last_error = primary_error
        refresh_status = "ok"
        refresh_message = (
            f"已刷新（主订阅警告: {primary_error}）" if primary_error else "刷新完成"
        )
        return True
    except Exception as exc:  # keep the HTTP process alive after upstream errors
        last_error = _friendly_error(exc)
        refresh_status = "error"
        refresh_message = last_error
        return False
    finally:
        refresh_lock.release()


def schedule_refresh():
    """Start refresh in background so free-tier reverse proxies do not emit gateway 502."""
    global refresh_status, refresh_message
    if refresh_lock.locked() or refresh_status == "running":
        return {"ok": True, "started": False, "busy": True, "message": "刷新进行中，请稍候"}
    refresh_status = "running"
    refresh_message = "刷新中..."
    threading.Thread(target=refresh, daemon=True).start()
    return {"ok": True, "started": True, "busy": False, "message": "已开始刷新"}


def refresh_loop():
    interval = max(300, int(os.getenv("REFRESH_INTERVAL_SECONDS", "86400")))
    # Default skip initial refresh on cloud hosts; local can set SKIP_INITIAL_REFRESH=false.
    if os.getenv("SKIP_INITIAL_REFRESH", "true").lower() in {"1", "true", "yes"}:
        time.sleep(interval)
    while True:
        refresh()
        time.sleep(interval)


# Restore first so a cold Render instance can serve the previous successful files.
restore_from_webdav()


@app.get("/")
def index():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin"))
    if not CONFIG_FILE.is_file() and _webdav_base_url():
        restore_from_webdav()
    return render_template("subscription.html")


@app.route("/admin", methods=["GET", "POST"])
def admin():
    password = _admin_password()
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if secrets.compare_digest(supplied, password):
            session.clear()
            session["admin_authenticated"] = True
            return redirect(url_for("index"))
        return render_template("admin_login.html", error="密码错误"), 401
    if not session.get("admin_authenticated"):
        return render_template("admin_login.html")
    return redirect(url_for("index"))


@app.post("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("admin"))


@app.get("/subscriptions")
def subscriptions():
    return redirect(url_for("index"))


@app.get("/health")
def health():
    return jsonify(ok=True, service="wv2ray", last_refresh=last_refresh, error=last_error,
                   refresh_status=refresh_status, webdav_error=webdav_last_error,
                   webdav_restored=len(webdav_restored_files))


@app.get("/api/status")
def status():
    unauthorized = _admin_required()
    if unauthorized:
        return unauthorized
    return jsonify(ok=last_error is None or refresh_status == "ok", last_refresh=last_refresh,
                   error=last_error, refresh_status=refresh_status, message=refresh_message,
                   data_dir=str(DATA_DIR),
                   files=[p.name for p in DATA_DIR.iterdir()] if DATA_DIR.is_dir() else [],
                   webdav_enabled=bool(_webdav_base_url()), webdav_url=_webdav_base_url(),
                   webdav_error=webdav_last_error,
                   webdav_restored_files=webdav_restored_files,
                   webdav_restored_at=webdav_restored_at,
                   sources=source_results)


@app.get("/api/config")
def config():
    unauthorized = _admin_required()
    if unauthorized:
        return unauthorized
    # Cold start may race or miss restore; retry if local config is empty.
    if not CONFIG_FILE.is_file() and _webdav_base_url():
        restore_from_webdav()
    current = get_config()
    return jsonify(
        provider_url=current["provider_url"],
        provider_enabled=_is_enabled(current.get("provider_enabled"), True),
        v2ray_url=current["v2ray_url"],
        clash_url=current["clash_url"],
        token_configured=bool(current["token"]),
        sources=current["sources"],
    )


@app.post("/api/config")
def update_config():
    unauthorized = _admin_required()
    if unauthorized:
        return unauthorized
    payload = request.get_json(silent=True) or {}
    current = get_config()
    for key in ("provider_url", "v2ray_url", "clash_url", "token"):
        if key in payload:
            value = str(payload[key]).strip()
            if key != "token" and value and not value.startswith(("http://", "https://")):
                return jsonify(ok=False, error=f"{key} must be an http(s) URL"), 400
            current[key] = value
    if "provider_enabled" in payload:
        current["provider_enabled"] = _is_enabled(payload.get("provider_enabled"), True)
    if "provider_url" in payload and str(payload.get("provider_url") or "").strip():
        try:
            current["v2ray_url"], current["clash_url"] = derive_provider_urls(current["provider_url"])
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
    elif "provider_url" in payload:
        current["v2ray_url"] = ""
        current["clash_url"] = ""
        current["token"] = ""
    if "sources" in payload:
        if not isinstance(payload["sources"], list) or len(payload["sources"]) > 100:
            return jsonify(ok=False, error="sources must be a list of at most 100 items"), 400
        clean = []
        for item in payload["sources"]:
            if not isinstance(item, dict) or not str(item.get("url", "")).startswith(("http://", "https://")):
                return jsonify(ok=False, error="each source needs an http(s) URL"), 400
            source_id = re.sub(r"[^a-zA-Z0-9_-]", "-", str(item.get("id", "source")))[:48] or "source"
            clean.append({
                "id": source_id,
                "name": str(item.get("name", source_id))[:100],
                "type": str(item.get("type", "other"))[:30],
                "url": str(item["url"]).strip(),
                "enabled": _is_enabled(item.get("enabled"), True),
            })
        current["sources"] = clean
    save_config(current)
    return jsonify(ok=True)


@app.get("/source/<source_id>")
def source_proxy(source_id):
    unauthorized = _admin_required()
    if unauthorized:
        return unauthorized
    import requests
    source = next((x for x in get_config()["sources"] if x.get("id") == source_id), None)
    if not source:
        return jsonify(ok=False, error="source not found"), 404
    try:
        response = requests.get(source["url"], timeout=30, headers={"User-Agent": "wv2ray-subscription-service/1.0"})
        response.raise_for_status()
        content_type = {"clash": "text/yaml; charset=utf-8", "singbox": "application/json; charset=utf-8",
                        "v2ray": "text/plain; charset=utf-8", "nbsh": "text/plain; charset=utf-8"}.get(source.get("type"), "text/plain; charset=utf-8")
        return response.content, 200, {"content-type": content_type, "cache-control": "public, max-age=120"}
    except requests.RequestException as exc:
        return jsonify(ok=False, error=str(exc)), 502



@app.post("/api/refresh")
def manual_refresh():
    unauthorized = _admin_required()
    if unauthorized:
        return unauthorized
    # Background job avoids Render free-tier request/gateway timeouts (true 502).
    return jsonify(schedule_refresh())


@app.get("/<path:filename>")
def file(filename):
    if filename in {"subscribe.txt", "clash.yaml", "nbsh.txt", "singbox.json", "metadata.json", "summary.json"}:
        response = send_from_directory(DATA_DIR, filename)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response
    return redirect("/", code=302)


if __name__ == "__main__":
    threading.Thread(target=refresh_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
else:
    # Gunicorn imports this module without executing __main__.
    threading.Thread(target=refresh_loop, daemon=True).start()
