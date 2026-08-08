import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from update_subscription import (  # noqa: E402
    _apply_token_to_url,
    _dedup_proxies,
    _env_to_bool,
    _fix_short_id_quotes,
    _validate_content,
    save_subscription_files,
)


class UpdateSubscriptionHelpersTest(unittest.TestCase):
    def test_apply_token_preserves_other_query_parameters(self):
        result = _apply_token_to_url(
            'https://example.com/sub?target=clash&token=old',
            'daily-token',
        )
        self.assertIn('target=clash', result)
        self.assertIn('token=daily-token', result)
        self.assertNotIn('token=old', result)

    def test_fix_short_id_quotes_only_numeric_values(self):
        content = "  short-id: 09\n  short-id: abc123\n"
        self.assertEqual(
            _fix_short_id_quotes(content),
            "  short-id: '09'\n  short-id: abc123\n",
        )

    def test_dedup_preserves_group_referenced_duplicate_nodes(self):
        clash_content = """proxies:
  - name: A
    type: http
    server: 1.2.3.4
    port: 8080
    password: same
  - name: B
    type: http
    server: 1.2.3.4
    port: 8080
    password: same
proxy-groups:
  - name: Manual Select
    type: select
    proxies:
      - A
      - B
"""
        result = _dedup_proxies(clash_content)
        data = yaml.safe_load(result)

        self.assertEqual(result, clash_content)
        self.assertEqual(len(data['proxies']), 2)
        self.assertIn('B', data['proxy-groups'][0]['proxies'])

    def test_invalid_subscription_marker_is_rejected(self):
        with self.assertRaises(ValueError):
            _validate_content('\u8ba2\u9605\u5df2\u5931\u6548', is_clash=True)

    def test_env_boolean_parsing(self):
        self.assertTrue(_env_to_bool('YES', default=False))
        self.assertFalse(_env_to_bool('off', default=True))
        self.assertTrue(_env_to_bool(None, default=True))

    def test_failed_source_keeps_old_file_and_reports_stale(self):
        clash_content = "proxies:\n  - name: test\n    type: ss\n"

        def fetch_side_effect(url):
            if 'v2ray' in url:
                raise RuntimeError('temporary upstream failure')
            return clash_content

        env = {
            'DIRECT_V2RAY_URL': 'https://example.com/v2ray',
            'DIRECT_CLASH_URL': 'https://example.com/clash',
            'GENERATE_ISSUE_VARIANTS': 'false',
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            old_content = 'previous-valid-subscription'
            (output / 'subscribe.txt').write_text(old_content, encoding='utf-8')

            with (
                patch.dict(os.environ, env, clear=False),
                patch('update_subscription._fetch_direct_content', side_effect=fetch_side_effect),
                patch('update_subscription._generate_dashboard_html'),
            ):
                self.assertTrue(save_subscription_files(temp_dir))

            metadata = json.loads(
                (output / 'metadata.json').read_text(encoding='utf-8')
            )
            summary = json.loads(
                (output / 'summary.json').read_text(encoding='utf-8')
            )

            self.assertEqual(
                (output / 'subscribe.txt').read_text(encoding='utf-8'),
                old_content,
            )
            self.assertEqual(
                (output / 'clash.yaml').read_text(encoding='utf-8'),
                clash_content,
            )
            self.assertEqual(metadata['source_mode'], 'direct')
            self.assertEqual(summary['clash_nodes_count'], 1)


if __name__ == '__main__':
    unittest.main()
