const ISSUE_URL = "https://github.com/wzdnzd/aggregator/issues/91";
const ISSUE_API_URL = "https://api.github.com/repos/wzdnzd/aggregator/issues/91";
const COMMENTS_API_URL = "https://api.github.com/repos/wzdnzd/aggregator/issues/91/comments?per_page=100";
const DEFAULT_SUBCONVERTER_URL = "https://subconverter-jboo.onrender.com/";
const DEFAULT_DIRECT_V2RAY_URL = "https://node.zyfx6.xyz/v2ray";
const DEFAULT_DIRECT_CLASH_URL = "https://node.zyfx6.xyz/clash";

const SUPPORTED_TARGETS = new Set(["v2ray", "clash"]);

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);

      if (url.pathname === "/" || url.pathname === "/health") {
        return jsonResponse({ ok: true, service: "subscription-forwarder" });
      }

      if (url.pathname === "/subscribe.txt") {
        return await handleForward("v2ray", env);
      }

      if (url.pathname === "/clash.yaml") {
        return await handleForward("clash", env);
      }

      return new Response("Not Found", { status: 404 });
    } catch (error) {
      return jsonResponse(
        {
          ok: false,
          error: String(error?.message || error),
        },
        500,
      );
    }
  },
};

async function handleForward(target, env) {
  if (!SUPPORTED_TARGETS.has(target)) {
    return new Response("Unsupported target", { status: 400 });
  }

  const useDirect = toBool(env.USE_DIRECT_SOURCE, true);

  let upstreamUrl;
  let convertedUrl;
  let content;

  if (useDirect) {
    upstreamUrl =
      target === "v2ray"
        ? env.DIRECT_V2RAY_URL || DEFAULT_DIRECT_V2RAY_URL
        : env.DIRECT_CLASH_URL || DEFAULT_DIRECT_CLASH_URL;
    convertedUrl = upstreamUrl;
    content = await fetchSubscriptionContent(upstreamUrl, target, env);
  } else {
    const info = await getSubscriptionInfo(env);
    upstreamUrl = buildSubscribeUrl(info.token, info.apiUrl, target);
    convertedUrl = buildConvertedUrl(upstreamUrl, target, env);
    content = await fetchSubscriptionContent(convertedUrl, target, env);
  }

  const headers = new Headers();
  headers.set("cache-control", "public, max-age=120");
  headers.set("x-upstream-url", upstreamUrl);
  headers.set("x-converted-url", convertedUrl);

  if (target === "v2ray") {
    headers.set("content-type", "text/plain; charset=utf-8");
    return new Response(content, { status: 200, headers });
  }

  headers.set("content-type", "application/yaml; charset=utf-8");
  return new Response(content, { status: 200, headers });
}

function toBool(value, defaultValue) {
  if (value === undefined || value === null || value === "") {
    return defaultValue;
  }
  const normalized = String(value).trim().toLowerCase();
  return ["1", "true", "yes", "y", "on"].includes(normalized);
}

async function getSubscriptionInfo(env) {
  const token = env.GITHUB_TOKEN || "";
  const headers = {
    "User-Agent": "Cloudflare-Worker-Subscription-Forwarder",
    Accept: "application/vnd.github+json",
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let combined = "";

  try {
    const issueResp = await fetch(ISSUE_API_URL, { headers });
    if (issueResp.ok) {
      const issue = await issueResp.json();
      combined += `${issue?.title || ""}\n${issue?.body || ""}`;
    }

    let page = 1;
    while (page <= 10) {
      const pagedUrl = `${COMMENTS_API_URL}&page=${page}`;
      const commentsResp = await fetch(pagedUrl, { headers });
      if (!commentsResp.ok) {
        break;
      }
      const comments = await commentsResp.json();
      if (!Array.isArray(comments) || comments.length === 0) {
        break;
      }
      combined += `\n${comments.map((c) => c?.body || "").join("\n")}`;
      if (comments.length < 100) {
        break;
      }
      page += 1;
    }
  } catch {
    // ignore and fallback to HTML
  }

  if (!containsToken(combined)) {
    const htmlResp = await fetch(ISSUE_URL, {
      headers: { "User-Agent": "Cloudflare-Worker-Subscription-Forwarder" },
    });
    if (htmlResp.ok) {
      const html = await htmlResp.text();
      combined += `\n${html}`;
    }
  }

  const tokenValue = extractToken(combined);
  const apiUrl = extractApiUrl(combined);

  if (!tokenValue || !apiUrl) {
    throw new Error("Failed to extract token/api_url from aggregator issue #91");
  }

  return { token: tokenValue, apiUrl };
}

function containsToken(text) {
  return /token/i.test(text) || /[A-Za-z0-9_\-+.*]{8,128}/.test(text);
}

function extractToken(content) {
  const tablePattern = /<td>\s*token\s*<\/td>.*?<code[^>]*>([A-Za-z0-9_\-+.*]{8,128})<\/code>/is;
  const tableMatch = content.match(tablePattern);
  if (tableMatch) {
    return tableMatch[1];
  }

  const mdPattern = /\|\s*token\s*\|.*?\|\s*`?([A-Za-z0-9_\-+.*]{8,128})`?\s*\|/is;
  const mdMatch = content.match(mdPattern);
  if (mdMatch) {
    return mdMatch[1];
  }

  const generic = content.match(/[?&]token=([A-Za-z0-9_\-+.*]{8,128})/i);
  if (generic) {
    return generic[1];
  }

  return null;
}

function extractApiUrl(content) {
  const fromContext = content.match(/在线服务接口地址.*?(https:\/\/[^\s<>"']+\/api\/v1\/subscribe[^\s<>"']*)/is);
  if (fromContext) {
    return fromContext[1];
  }

  const generic = content.match(/(https:\/\/[^\s<>"']+\/api\/v1\/subscribe[^\s<>"']*)/i);
  if (generic) {
    return generic[1];
  }

  return null;
}

function buildSubscribeUrl(token, apiUrl, target) {
  const u = new URL(apiUrl);
  u.searchParams.set("token", token);
  u.searchParams.set("target", target);
  u.searchParams.set("list", "false");
  return u.toString();
}

function buildConvertedUrl(upstreamUrl, target, env) {
  const converterBase = env.SUBCONVERTER_URL || DEFAULT_SUBCONVERTER_URL;
  const converter = new URL(converterBase);

  // Subconverter common path.
  if (!converter.pathname || converter.pathname === "/") {
    converter.pathname = "/sub";
  }

  const targetMap = {
    v2ray: env.SUBCONVERTER_TARGET_V2RAY || "v2ray",
    clash: env.SUBCONVERTER_TARGET_CLASH || "clash",
  };

  converter.searchParams.set("target", targetMap[target] || target);
  converter.searchParams.set("url", upstreamUrl);
  converter.searchParams.set("insert", env.SUBCONVERTER_INSERT || "false");
  converter.searchParams.set("emoji", env.SUBCONVERTER_EMOJI || "true");
  converter.searchParams.set("list", env.SUBCONVERTER_LIST || "false");

  return converter.toString();
}

async function fetchSubscriptionContent(url, target, env) {
  const headers = {
    "User-Agent": "Cloudflare-Worker-Subscription-Forwarder",
    Accept: "*/*",
  };

  const resp = await fetch(url, {
    headers,
    cf: {
      cacheTtl: Number(env.UPSTREAM_CACHE_TTL || 120),
      cacheEverything: true,
    },
  });

  if (!resp.ok) {
    throw new Error(`Upstream request failed: ${resp.status} ${resp.statusText}`);
  }

  const content = await resp.text();
  validateContent(content, target, url);
  return content;
}

function validateContent(content, target, url) {
  const stripped = content.trim();
  if (!stripped) {
    throw new Error(`Upstream returned empty payload: ${url}`);
  }

  if (stripped.startsWith("{")) {
    let payload;
    try {
      payload = JSON.parse(stripped);
    } catch {
      payload = null;
    }

    if (payload && (payload.success === false || payload.code)) {
      throw new Error(
        `Upstream returned JSON error payload: code=${payload.code}, message=${payload.message}`,
      );
    }
  }

  // Check for expired/mock subscription indicators
  const invalidKeywords = ["订阅已失效", "请重新获取", "xmsubbot", "txwl666"];
  let checkText = stripped;
  if (target === "v2ray") {
    try {
      checkText = atob(stripped);
    } catch {
      // ignore, use original
    }
  }
  for (const kw of invalidKeywords) {
    if (checkText.includes(kw)) {
      throw new Error(`Upstream content contains expiration marker "${kw}": ${url}`);
    }
  }

  if (target === "v2ray") {
    let decoded;
    try {
      decoded = atob(stripped);
    } catch {
      throw new Error("v2ray payload is not valid base64");
    }

    const lines = decoded
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#"));

    const prefixes = [
      "vmess://",
      "vless://",
      "trojan://",
      "ss://",
      "ssr://",
      "hysteria://",
      "hysteria2://",
      "tuic://",
    ];

    const hasNode = lines.some((line) => prefixes.some((prefix) => line.startsWith(prefix)));
    if (!hasNode) {
      throw new Error("v2ray payload validation failed: no valid node prefixes found");
    }
  }

  if (target === "clash") {
    const markers = ["proxies:", "proxy-groups:", "mixed-port:", "port:"];
    const hasYamlMarkers = markers.some((marker) => stripped.includes(marker));
    if (!hasYamlMarkers) {
      throw new Error("clash payload validation failed: yaml markers missing");
    }
  }
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
