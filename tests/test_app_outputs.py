import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SKIP_INITIAL_REFRESH", "true")
os.environ["DATA_DIR"] = str(Path(tempfile.gettempdir()) / "wv2ray-test-outputs")

import app  # noqa: E402


class MergeConvertedSourcesOutputsTest(unittest.TestCase):
    def test_enabled_extra_source_is_merged_into_all_outputs(self):
        extra_yaml = """
proxies:
  - name: extra-http
    type: http
    server: 203.0.113.10
    port: 8080
  - name: extra-vless
    type: vless
    server: 203.0.113.11
    port: 443
    uuid: 11111111-1111-1111-1111-111111111111
proxy-groups:
  - name: "\u9009\u62e9\u51fa\u53e3"
    type: select
    proxies:
      - DIRECT
      - extra-http
      - extra-vless
rules:
  - GEOSITE,CN,DIRECT
  - MATCH,\u9009\u62e9\u51fa\u53e3
"""
        primary_clash = """
proxies:
  - name: primary-node
    type: http
    server: 198.51.100.1
    port: 8080
proxy-groups:
  - name: GLOBAL
    type: select
    proxies:
      - primary-node
rules:
  - DOMAIN-SUFFIX,cn,DIRECT
  - MATCH,primary-node
"""
        primary_v2ray = base64.b64encode(
            "http://user:pass@198.51.100.1:8080#primary-node".encode("utf-8")
        ).decode("ascii")
        config = {
            "sources": [
                {
                    "id": "extra-1",
                    "name": "extra-source",
                    "type": "clash",
                    "url": "https://extra.example/sub",
                    "enabled": True,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "clash.yaml").write_text(primary_clash, encoding="utf-8")
            (data_dir / "subscribe.txt").write_text(primary_v2ray, encoding="utf-8")

            with (
                patch.object(app, "DATA_DIR", data_dir),
                patch.object(app, "_fetch_source", return_value=extra_yaml),
                patch.object(app, "_fetch_converted", side_effect=RuntimeError("not used")),
            ):
                app._merge_converted_sources(config)

            clash = yaml.safe_load(
                (data_dir / "clash.yaml").read_text(encoding="utf-8")
            )
            group_names = {
                group.get("name") for group in clash.get("proxy-groups", [])
            }
            self.assertIn("\u9009\u62e9\u51fa\u53e3", group_names)
            self.assertIn("extra-source", group_names)
            self.assertIn(
                "extra-http",
                {proxy.get("name") for proxy in clash.get("proxies", [])},
            )
            self.assertIn(
                "GEOSITE,CN,DIRECT",
                clash.get("rules", []),
            )

            encoded = (data_dir / "subscribe.txt").read_text(encoding="utf-8").strip()
            decoded = base64.b64decode(encoded).decode("utf-8")
            self.assertIn("203.0.113.10", decoded)
            self.assertIn("203.0.113.11", decoded)
            self.assertEqual(
                (data_dir / "nbsh.txt").read_text(encoding="utf-8").strip(),
                encoded,
            )

            singbox = json.loads(
                (data_dir / "singbox.json").read_text(encoding="utf-8")
            )
            outbound_servers = {
                outbound.get("server") for outbound in singbox.get("outbounds", [])
            }
            self.assertIn("203.0.113.10", outbound_servers)
            self.assertIn("203.0.113.11", outbound_servers)

    def test_disabled_extra_source_is_not_merged_into_outputs(self):
        extra_yaml = """
proxies:
  - name: disabled-extra-node
    type: http
    server: 203.0.113.99
    port: 8080
proxy-groups:
  - name: disabled-extra-group
    type: select
    proxies:
      - DIRECT
      - disabled-extra-node
rules:
  - DOMAIN-SUFFIX,disabled.example,disabled-extra-group
"""
        primary_clash = """
proxies:
  - name: primary-node
    type: http
    server: 198.51.100.1
    port: 8080
proxy-groups:
  - name: GLOBAL
    type: select
    proxies:
      - primary-node
rules:
  - DOMAIN-SUFFIX,cn,DIRECT
  - MATCH,primary-node
"""
        primary_v2ray = base64.b64encode(
            "http://user:pass@198.51.100.1:8080#primary-node".encode("utf-8")
        ).decode("ascii")
        config = {
            "sources": [
                {
                    "id": "extra-disabled",
                    "name": "disabled-source",
                    "type": "clash",
                    "url": "https://extra.example/sub",
                    "enabled": False,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "clash.yaml").write_text(primary_clash, encoding="utf-8")
            (data_dir / "subscribe.txt").write_text(primary_v2ray, encoding="utf-8")

            with (
                patch.object(app, "DATA_DIR", data_dir),
                patch.object(
                    app,
                    "_fetch_source",
                    side_effect=AssertionError("disabled source must not be fetched"),
                ),
                patch.object(app, "_fetch_converted", side_effect=RuntimeError("not used")),
            ):
                app._merge_converted_sources(config)

            clash = yaml.safe_load(
                (data_dir / "clash.yaml").read_text(encoding="utf-8")
            )
            proxy_names = {
                proxy.get("name") for proxy in clash.get("proxies", [])
            }
            group_names = {
                group.get("name") for group in clash.get("proxy-groups", [])
            }
            self.assertNotIn("disabled-extra-node", proxy_names)
            self.assertNotIn("disabled-source", group_names)
            self.assertNotIn(
                "DOMAIN-SUFFIX,disabled.example,disabled-extra-group",
                clash.get("rules", []),
            )

            encoded = (data_dir / "subscribe.txt").read_text(encoding="utf-8").strip()
            decoded = base64.b64decode(encoded).decode("utf-8")
            self.assertNotIn("203.0.113.99", decoded)
            self.assertEqual(
                (data_dir / "nbsh.txt").read_text(encoding="utf-8").strip(),
                encoded,
            )

            singbox = json.loads(
                (data_dir / "singbox.json").read_text(encoding="utf-8")
            )
            outbound_servers = {
                outbound.get("server") for outbound in singbox.get("outbounds", [])
            }
            self.assertNotIn("203.0.113.99", outbound_servers)

    def test_full_clash_profile_keeps_rule_providers_and_rule_set(self):
        extra_yaml = """
proxies:
  - name: extra-http
    type: http
    server: 203.0.113.10
    port: 8080
proxy-groups:
  - name: "\u9009\u62e9\u51fa\u53e3"
    type: select
    proxies:
      - DIRECT
      - extra-http
rule-providers:
  category-ads-all:
    type: http
    behavior: domain
  geolocation-!cn:
    type: http
    behavior: domain
rules:
  - RULE-SET,category-ads-all,REJECT
  - RULE-SET,geolocation-!cn,\u9009\u62e9\u51fa\u53e3,no-resolve
  - MATCH,\u9009\u62e9\u51fa\u53e3
"""
        primary_clash = """
proxies:
  - name: primary-node
    type: http
    server: 198.51.100.1
    port: 8080
proxy-groups:
  - name: GLOBAL
    type: select
    proxies:
      - primary-node
rules:
  - DOMAIN-SUFFIX,cn,DIRECT
  - MATCH,primary-node
"""
        primary_v2ray = base64.b64encode(
            "http://user:pass@198.51.100.1:8080#primary-node".encode("utf-8")
        ).decode("ascii")
        config = {
            "sources": [
                {
                    "id": "extra-1",
                    "name": "extra-source",
                    "type": "clash",
                    "url": "https://extra.example/full.yaml",
                    "enabled": True,
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "clash.yaml").write_text(primary_clash, encoding="utf-8")
            (data_dir / "subscribe.txt").write_text(primary_v2ray, encoding="utf-8")

            with (
                patch.object(app, "DATA_DIR", data_dir),
                patch.object(app, "_fetch_source", return_value=extra_yaml),
                patch.object(app, "_fetch_converted", side_effect=RuntimeError("not used")),
            ):
                app._merge_converted_sources(config)

            clash = yaml.safe_load(
                (data_dir / "clash.yaml").read_text(encoding="utf-8")
            )
            self.assertIn("category-ads-all", clash["rule-providers"])
            self.assertIn("geolocation-!cn", clash["rule-providers"])
            rules = clash.get("rules", [])
            self.assertIn("RULE-SET,category-ads-all,REJECT", rules)
            self.assertIn(
                "RULE-SET,geolocation-!cn,\u9009\u62e9\u51fa\u53e3,no-resolve",
                rules,
            )


if __name__ == "__main__":
    unittest.main()
