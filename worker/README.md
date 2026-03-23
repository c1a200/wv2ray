# Cloudflare Worker Subscription Forwarder

This Worker provides stable forwarding URLs for subscription clients:

- `/subscribe.txt` -> upstream `https://node.zyfx6.xyz/v2rayNG/`
- `/clash.yaml` -> upstream `https://node.zyfx6.xyz/clash`
- `/health` -> health check

Flow:

1. Read direct source URL from Worker vars.
2. Request upstream content (`v2rayNG` / `clash`).
3. Validate payload shape.
4. Return content to client.

Fallback mode:

- Set `USE_DIRECT_SOURCE = "false"` to switch back to legacy issue-based extraction flow.

## Why this mode

- Keep client subscription URLs stable.
- Avoid running fetch on GitHub-hosted Actions runner.
- Fetch latest payload in real-time from upstream.

## 1) Deploy in Cloudflare

Run in this directory:

```bash
cd worker
npx wrangler deploy
```

After deployment, Cloudflare will give you a URL similar to:

```text
https://wv2ray-forwarder.<your-subdomain>.workers.dev
```

Your stable subscription URLs are:

```text
https://wv2ray-forwarder.<your-subdomain>.workers.dev/subscribe.txt
https://wv2ray-forwarder.<your-subdomain>.workers.dev/clash.yaml
```

## 2) Optional legacy secret (only for issue mode)

Only needed when `USE_DIRECT_SOURCE = "false"`.
If using issue mode, add a token to improve GitHub API reliability:

```bash
cd worker
npx wrangler secret put GITHUB_TOKEN
```

Input a GitHub token with read access to public API.

## 3) Optional custom cache TTL

Default upstream cache TTL is 120 seconds.
You can change it in `wrangler.toml`:

```toml
[vars]
UPSTREAM_CACHE_TTL = "120"
USE_DIRECT_SOURCE = "true"
DIRECT_V2RAY_URL = "https://node.zyfx6.xyz/v2rayNG/"
DIRECT_CLASH_URL = "https://node.zyfx6.xyz/clash"
```

## 4) Subconverter settings

This project defaults to your converter service:

```toml
SUBCONVERTER_URL = "https://subconverter-jboo.onrender.com/"
```

You can tune conversion parameters in `wrangler.toml`:

```toml
SUBCONVERTER_TARGET_V2RAY = "v2ray"
SUBCONVERTER_TARGET_CLASH = "clash"
SUBCONVERTER_INSERT = "false"
SUBCONVERTER_EMOJI = "true"
SUBCONVERTER_LIST = "false"
```

If your converter API path is `/sub`, keep `SUBCONVERTER_URL` as root URL.
The Worker will auto-append `/sub` when path is empty.

## 5) Optional custom domain

You can bind your own domain in Cloudflare dashboard to keep URL fully under your control.

## Notes

- The Worker validates payload shape and rejects upstream JSON error payloads.
- If upstream blocks Cloudflare egress in the future, forwarding will also fail.
- This mode does not write to GitHub repository files; it returns data directly to clients.
