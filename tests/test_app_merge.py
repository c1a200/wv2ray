import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SKIP_INITIAL_REFRESH", "true")
os.environ["DATA_DIR"] = str(Path(tempfile.gettempdir()) / "wv2ray-test-data")

from app import (  # noqa: E402
    _merge_extra_clash_content,
    _merge_extra_rules,
    _unique_clash_name,
)


class MergeExtraClashContentTest(unittest.TestCase):
    def test_unique_clash_name_appends_source_suffix(self):
        existing = {"GLOBAL"}
        self.assertEqual(
            _unique_clash_name("GLOBAL", existing, "source-a"),
            "GLOBAL [source-a]",
        )
        existing.add("GLOBAL [source-a]")
        self.assertEqual(
            _unique_clash_name("GLOBAL", existing, "source-a"),
            "GLOBAL [source-a 2]",
        )

    def test_merges_proxies_groups_rules_and_source_group(self):
        base = {
            "proxies": [{"name": "A", "type": "ss"}],
            "proxy-groups": [
                {"name": "GLOBAL", "type": "select", "proxies": ["A"]}
            ],
            "rules": ["DOMAIN-SUFFIX,cn,DIRECT", "MATCH,\u6f0f\u7f51\u4e4b\u9c7c"],
        }
        extra = {
            "proxies": [
                {"name": "B", "type": "http"},
                {"name": "C", "type": "http"},
            ],
            "proxy-groups": [
                {
                    "name": "\u9009\u62e9\u51fa\u53e3",
                    "type": "select",
                    "proxies": ["DIRECT", "B", "C"],
                }
            ],
            "rules": ["GEOSITE,CN,DIRECT", "MATCH,\u9009\u62e9\u51fa\u53e3"],
        }

        result = _merge_extra_clash_content(base, extra, "test-source")

        self.assertEqual(
            {proxy["name"] for proxy in result["proxies"]}, {"A", "B", "C"}
        )
        groups = {group["name"]: group for group in result["proxy-groups"]}
        self.assertIn("\u9009\u62e9\u51fa\u53e3", groups)
        self.assertEqual(
            groups["\u9009\u62e9\u51fa\u53e3"]["proxies"],
            ["DIRECT", "B", "C"],
        )
        self.assertIn("test-source", groups)
        self.assertIn("test-source", groups["GLOBAL"]["proxies"])
        rules = result["rules"]
        self.assertLess(
            rules.index("GEOSITE,CN,DIRECT"),
            rules.index("MATCH,\u6f0f\u7f51\u4e4b\u9c7c"),
        )
        self.assertNotIn("MATCH,\u9009\u62e9\u51fa\u53e3", rules)

    def test_renames_colliding_proxy_names_in_extra_group(self):
        base = {
            "proxies": [{"name": "X", "type": "http", "server": "1.2.3.4"}],
            "proxy-groups": [],
        }
        extra = {
            "proxies": [{"name": "X", "type": "http", "server": "5.6.7.8"}],
            "proxy-groups": [
                {"name": "\u9009\u62e9\u51fa\u53e3", "type": "select", "proxies": ["X"]}
            ],
        }

        result = _merge_extra_clash_content(base, extra, "source-a")

        extra_proxy = [proxy for proxy in result["proxies"] if proxy.get("name") != "X"]
        self.assertEqual(len(extra_proxy), 1)
        self.assertEqual(extra_proxy[0]["name"], "X [source-a]")
        group = next(
            group for group in result["proxy-groups"]
            if group.get("name") == "\u9009\u62e9\u51fa\u53e3"
        )
        self.assertEqual(group["proxies"], ["X [source-a]"])

    def test_renames_colliding_group_names_in_extra_rules(self):
        base = {
            "proxies": [{"name": "A", "type": "http"}],
            "proxy-groups": [
                {"name": "\u9009\u62e9\u51fa\u53e3", "type": "select", "proxies": ["A"]}
            ],
            "rules": ["MATCH,\u9009\u62e9\u51fa\u53e3"],
        }
        extra = {
            "proxies": [{"name": "B", "type": "http"}],
            "proxy-groups": [
                {"name": "\u9009\u62e9\u51fa\u53e3", "type": "select", "proxies": ["B"]}
            ],
            "rules": [
                "DOMAIN-SUFFIX,example.com,\u9009\u62e9\u51fa\u53e3",
                "MATCH,\u9009\u62e9\u51fa\u53e3",
            ],
        }

        result = _merge_extra_clash_content(base, extra, "source-a")

        renamed = "\u9009\u62e9\u51fa\u53e3 [source-a]"
        group_names = {
            group["name"] for group in result["proxy-groups"]
            if isinstance(group, dict)
        }
        self.assertIn(renamed, group_names)
        self.assertIn(f"DOMAIN-SUFFIX,example.com,{renamed}", result["rules"])

    def test_merge_rules_appends_match_when_base_has_no_match(self):
        self.assertEqual(
            _merge_extra_rules(
                ["DOMAIN-SUFFIX,cn,DIRECT"],
                ["MATCH,\u9009\u62e9\u51fa\u53e3"],
                {},
            ),
            ["DOMAIN-SUFFIX,cn,DIRECT", "MATCH,\u9009\u62e9\u51fa\u53e3"],
        )

    def test_merges_rule_providers_and_keeps_rule_set_references(self):
        base = {
            "proxies": [{"name": "A", "type": "http"}],
            "proxy-groups": [],
        }
        extra = {
            "proxies": [{"name": "B", "type": "http"}],
            "proxy-groups": [
                {
                    "name": "\u9009\u62e9\u51fa\u53e3",
                    "type": "select",
                    "proxies": ["DIRECT", "B"],
                }
            ],
            "rule-providers": {
                "category-ads-all": {"type": "http", "behavior": "domain"},
                "geolocation-!cn": {"type": "http", "behavior": "domain"},
            },
            "rules": [
                "RULE-SET,category-ads-all,REJECT",
                f"RULE-SET,geolocation-!cn,\u9009\u62e9\u51fa\u53e3",
            ],
        }

        result = _merge_extra_clash_content(base, extra, "test-source")

        providers = result["rule-providers"]
        self.assertIn("category-ads-all", providers)
        self.assertIn("geolocation-!cn", providers)
        self.assertIn("RULE-SET,category-ads-all,REJECT", result["rules"])
        self.assertIn(
            f"RULE-SET,geolocation-!cn,\u9009\u62e9\u51fa\u53e3",
            result["rules"],
        )

    def test_renames_colliding_rule_provider_in_rule_set(self):
        base = {
            "proxies": [{"name": "A", "type": "http"}],
            "proxy-groups": [
                {"name": "\u56fd\u5185", "type": "select", "proxies": ["A"]}
            ],
            "rule-providers": {
                "cn": {"type": "http", "behavior": "domain"}
            },
        }
        extra = {
            "proxies": [{"name": "B", "type": "http"}],
            "proxy-groups": [
                {"name": "\u56fd\u5185", "type": "select", "proxies": ["B"]}
            ],
            "rule-providers": {
                "cn": {"type": "http", "behavior": "domain"}
            },
            "rules": ["RULE-SET,cn,\u56fd\u5185,no-resolve"],
        }

        result = _merge_extra_clash_content(base, extra, "source-a")

        providers = result["rule-providers"]
        self.assertIn("cn", providers)
        self.assertIn("cn [source-a]", providers)
        self.assertIn(
            "RULE-SET,cn [source-a],\u56fd\u5185 [source-a],no-resolve",
            result["rules"],
        )


if __name__ == "__main__":
    unittest.main()
