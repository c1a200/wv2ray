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
        "v2ray_url": os.getenv("DIRECT_V2RAY_URL", "https://node.zyfx6.xyz/v2ray"),
        "clash_url": os.getenv("DIRECT_CLASH_URL", "https://node.zyfx6.xyz/clash"),
        "token": os.getenv("DIRECT_TOKEN", ""),
        "sources": [],
    }
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            defaults.update({k: str(saved[k]) for k in defaults if k in saved})
            if isinstance(saved.get("sources"), list):
                defaults["sources"] = saved["sources"]
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
    return (os.getenv("WEBDAV_URL") or "").strip().rstrip("/")


def _webdav_file_url(filename):
    return urljoin(_webdav_base_url() + "/", quote(filename))


def _webdav_auth():
    return (os.getenv("WEBDAV_USERNAME") or "", os.getenv("WEBDAV_PASSWORD") or "")


def _record_webdav_error(error):
    global webdav_last_error
    webdav_last_error = str(error)[:240]


def restore_from_webdav():
    """Restore the last saved configuration and subscription files on startup."""
    if not _webdav_base_url():
        return
    import requests
    try:
        for filename in PERSISTED_FILES:
            response = requests.get(_webdav_file_url(filename), auth=_webdav_auth(), timeout=10)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            (DATA_DIR / filename).write_bytes(response.content)
        _record_webdav_error("")
    except requests.RequestException as exc:
        _record_webdav_error(f"WebDAV restore failed: {exc}")


def sync_to_webdav():
    """Make the WebDAV directory match locally generated state without leaking credentials."""
    if not _webdav_base_url():
        return
    import requests
    try:
        for filename in PERSISTED_FILES:
            path = DATA_DIR / filename
            target = _webdav_file_url(filename)
            if path.is_file():
                response = requests.put(target, data=path.read_bytes(), auth=_webdav_auth(), timeout=20)
                response.raise_for_status()
            else:
                response = requests.delete(target, auth=_webdav_auth(), timeout=10)
                if response.status_code not in {204, 404}:
                    response.raise_for_status()
        _record_webdav_error("")
    except requests.RequestException as exc:
        _record_webdav_error(f"WebDAV sync failed: {exc}")


def _converter_url(source_url, target):
    base = os.getenv("SUBCONVERTER_URL", "https://subconverter-jboo.onrender.com/").rstrip("/")
    path = base if base.endswith("/sub") else f"{base}/sub"
    target = os.getenv("SUBCONVERTER_TARGET_V2RAY", "mixed") if target == "v2ray" else os.getenv("SUBCONVERTER_TARGET_CLASH", "clash")
    params = urlencode({"target": target, "url": source_url, "insert": "false", "emoji": "true", "list": "false"})
    return f"{path}?{params}"


def _fetch_converted(source_url, target):
    import requests
    response = requests.get(_converter_url(source_url, target), timeout=90,
                            headers={"User-Agent": "wv2ray-subscription-service/1.0"})
    response.raise_for_status()
    content = response.text.strip()
    if not content:
        raise ValueError(f"subconverter returned empty {target} content")
    return content


def _fetch_source(source_url):
    import requests
    response = requests.get(source_url, timeout=60,
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
        else:
            continue
        outbounds.append(base)
    return outbounds


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
    clash_keys = {json.dumps({k: v for k, v in proxy.items() if k != "name"}, sort_keys=True, ensure_ascii=False)
                  for proxy in clash_data["proxies"] if isinstance(proxy, dict)}
    v2_keys = set(base_nodes)

    for source in config.get("sources", []):
        name = source.get("name") or source.get("id") or "source"
        status = {"id": source.get("id"), "name": name, "ok": False,
                  "clash_added": 0, "v2ray_added": 0, "errors": []}
        converted_proxies = []
        try:
            if str(source.get("type", "")).lower() == "clash":
                converted_clash = yaml.safe_load(_fetch_source(source["url"])) or {}
            else:
                converted_clash = yaml.safe_load(_fetch_converted(source["url"], "clash")) or {}
            converted_proxies = converted_clash.get("proxies", []) if isinstance(converted_clash, dict) else []
            added_clash = 0
            for proxy in converted_proxies:
                if not isinstance(proxy, dict):
                    continue
                key = json.dumps({k: v for k, v in proxy.items() if k != "name"}, sort_keys=True, ensure_ascii=False)
                if key in clash_keys:
                    continue
                if any(item.get("name") == proxy.get("name") for item in clash_data["proxies"] if isinstance(item, dict)):
                    proxy = dict(proxy)
                    proxy["name"] = f"{proxy.get('name', 'node')} [{name}]"
                clash_data["proxies"].append(proxy)
                clash_keys.add(key)
                added_clash += 1
            status["clash_added"] = added_clash
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


def refresh():
    global last_refresh, last_error, source_results
    if not refresh_lock.acquire(blocking=False):
        return False
    try:
        # Issue variants are GitHub-dependent and are intentionally disabled.
        os.environ.setdefault("GENERATE_ISSUE_VARIANTS", "false")
        config = get_config()
        if config["provider_url"]:
            config["v2ray_url"], config["clash_url"] = derive_provider_urls(config["provider_url"])
        if not config["v2ray_url"] and not config["clash_url"] and not config.get("sources"):
            for filename in ("subscribe.txt", "clash.yaml", "nbsh.txt", "singbox.json", "metadata.json", "summary.json"):
                (DATA_DIR / filename).unlink(missing_ok=True)
            source_results = []
            sync_to_webdav()
            last_refresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            last_error = None
            return True
        has_primary = bool(config["v2ray_url"] and config["clash_url"])
        if has_primary:
            os.environ["DIRECT_V2RAY_URL"] = config["v2ray_url"]
            os.environ["DIRECT_CLASH_URL"] = config["clash_url"]
            os.environ["DIRECT_TOKEN"] = config["token"]
            result = save_subscription_files(str(DATA_DIR))
        else:
            # Sources-only mode starts clean instead of falling back to built-in URLs.
            (DATA_DIR / "subscribe.txt").write_text("", encoding="utf-8")
            (DATA_DIR / "clash.yaml").write_text("proxies: []\n", encoding="utf-8")
            result = True
        missing = [name for name in ("subscribe.txt", "clash.yaml") if not (DATA_DIR / name).is_file()]
        if result is not True or missing:
            raise RuntimeError("上游抓取失败，未生成文件: " + ", ".join(missing))
        _merge_converted_sources(config)
        sync_to_webdav()
        last_refresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        last_error = None
        return True
    except Exception as exc:  # keep the HTTP process alive after upstream errors
        last_error = str(exc)
        return False
    finally:
        refresh_lock.release()


def refresh_loop():
    interval = max(300, int(os.getenv("REFRESH_INTERVAL_SECONDS", "86400")))
    if os.getenv("SKIP_INITIAL_REFRESH", "false").lower() in {"1", "true", "yes"}:
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
    return jsonify(ok=True, service="wv2ray", last_refresh=last_refresh, error=last_error)


@app.get("/api/status")
def status():
    unauthorized = _admin_required()
    if unauthorized:
        return unauthorized
    return jsonify(ok=last_error is None, last_refresh=last_refresh, error=last_error,
                   data_dir=str(DATA_DIR), files=[p.name for p in DATA_DIR.iterdir()],
                   webdav_enabled=bool(_webdav_base_url()), webdav_error=webdav_last_error,
                   sources=source_results)


@app.get("/api/config")
def config():
    unauthorized = _admin_required()
    if unauthorized:
        return unauthorized
    current = get_config()
    return jsonify(provider_url=current["provider_url"], v2ray_url=current["v2ray_url"],
                   clash_url=current["clash_url"], token_configured=bool(current["token"]),
                   sources=current["sources"])


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
    if "provider_url" in payload and payload["provider_url"].strip():
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
            clean.append({"id": source_id, "name": str(item.get("name", source_id))[:100],
                          "type": str(item.get("type", "other"))[:30], "url": str(item["url"])})
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
    if refresh():
        return jsonify(ok=True)
    return jsonify(ok=False, error=last_error), 502


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
