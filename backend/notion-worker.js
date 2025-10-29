// notion-worker.js
const API_VERSION = "2022-06-28";
const DEFAULT_FIELDS = {
  word: { name: "Word", type: "title" },
  pron: { name: "Pron", type: "rich_text" },
  senses: { name: "Senses", type: "rich_text" },
  ety: { name: "Etymology", type: "rich_text" },
  same: { name: "Same", type: "multi_select" },
  coll: { name: "Collocations", type: "multi_select" },
  conf: { name: "Confusions", type: "multi_select" },
  beans: { name: "Beans", type: "multi_select" }
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const originAllowList = parseAllowList(env.CORS_ALLOW_ORIGIN);
    const requestOrigin = request.headers.get("Origin") || "";
    const withCors = (res) => applyCors(res, originAllowList, requestOrigin);

    if (request.method === "OPTIONS") {
      if (!isOriginAllowed(requestOrigin, originAllowList)) {
        return withCors(new Response("Forbidden", { status: 403 }));
      }
      return withCors(null);
    }

    if (!isOriginAllowed(requestOrigin, originAllowList)) {
      return withCors(new Response("Forbidden", { status: 403 }));
    }

    const path = normalizePath(url.pathname);
    if (!["/", "/sync"].includes(path)) {
      return withCors(new Response("Not Found", { status: 404 }));
    }
    if (request.method !== "GET") {
      return withCors(new Response("Method Not Allowed", { status: 405 }));
    }

    const dbAllowList = parseAllowList(env.NOTION_DB_ALLOWLIST);
    const configuredDb = (env.NOTION_DB || "").trim();
    if (configuredDb) dbAllowList.add(configuredDb);
    const queryDb = (url.searchParams.get("db") || "").trim();
    let dbId = configuredDb || queryDb;

    if (!dbId) {
      return withCors(json({ error: "missing db" }, 400));
    }
    if (dbAllowList.size && !dbAllowList.has("*") && !dbAllowList.has(dbId)) {
      return withCors(json({ error: "db not allowed" }, 403));
    }

    try {
      const fieldsConfig = parseFieldsConfig(env.NOTION_FIELDS_JSON);
      const items = await pullDatabase({ dbId, token: env.NOTION_TOKEN, fieldsConfig });
      return withCors(json(items));
    } catch (err) {
      console.error(err);
      const status = Number.isInteger(err.statusCode) ? err.statusCode : 500;
      return withCors(json({ error: err.message }, status));
    }
  }
};

async function pullDatabase({ dbId, token, fieldsConfig }) {
  if (!token) {
    const err = new Error("Missing NOTION_TOKEN");
    err.statusCode = 500;
    throw err;
  }

  const items = [];
  let hasMore = true;
  let cursor = null;

  while (hasMore) {
    const body = { page_size: 100 };
    if (cursor) body.start_cursor = cursor;

    const res = await fetch(`https://api.notion.com/v1/databases/${dbId}/query`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Notion-Version": API_VERSION
      },
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const text = await res.text();
      const err = new Error(`Notion responded with ${res.status}: ${text}`);
      err.statusCode = res.status;
      throw err;
    }

    const payload = await res.json();
    for (const page of payload.results) {
      const properties = page.properties || {};
      items.push(mapPageToRecord(page, properties, fieldsConfig));
    }

    hasMore = payload.has_more;
    cursor = payload.next_cursor;
  }

  return items;
}

function mapPageToRecord(page, props, fieldsConfig) {
  const getField = (key) => {
    const config = fieldsConfig[key];
    if (!config) return null;

    const property = props[config.name];
    if (!property) return config.default ?? (config.type === "multi_select" ? [] : "");

    switch (config.type) {
      case "title":
        return (property.title || []).map(toPlainText).join("").trim();
      case "rich_text":
        return (property.rich_text || []).map(toPlainText).join("\n").trim();
      case "multi_select":
        return (property.multi_select || []).map((x) => x.name);
      default:
        return config.default ?? "";
    }
  };

  return {
    notionId: page.id,
    edited: page.last_edited_time,
    word: getField("word") || "",
    pron: ensureArray(getField("pron")),
    senses: ensureArray(getField("senses")),
    ety: getField("ety") || "",
    same: ensureArray(getField("same")),
    coll: ensureArray(getField("coll")),
    conf: ensureArray(getField("conf")),
    beans: ensureArray(getField("beans"))
  };
}

function ensureArray(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  if (typeof value === "string") {
    return value
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return [];
}

function toPlainText(block) {
  return block?.plain_text ?? "";
}

function normalizePath(pathname) {
  return pathname.replace(/\/+$/, "") || "/";
}

function parseFieldsConfig(jsonText) {
  if (!jsonText) return DEFAULT_FIELDS;
  try {
    const parsed = JSON.parse(jsonText);
    return { ...DEFAULT_FIELDS, ...parsed };
  } catch (err) {
    console.warn("Failed to parse NOTION_FIELDS_JSON, using default mapping.", err);
    return DEFAULT_FIELDS;
  }
}

function parseAllowList(raw) {
  if (!raw) return new Set();
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  );
}

function isOriginAllowed(origin, allowList) {
  if (!origin || allowList.size === 0 || allowList.has("*")) return true;
  return allowList.has(origin);
}

function resolveCorsOrigin(allowList, origin) {
  if (allowList.size === 0 || allowList.has("*")) return "*";
  if (origin && allowList.has(origin)) return origin;
  return allowList.values().next().value;
}

function applyCors(res, allowList, origin) {
  const headers = {
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type"
  };
  const allowOrigin = resolveCorsOrigin(allowList, origin);
  headers["Access-Control-Allow-Origin"] = allowOrigin;
  if (allowList.size && !allowList.has("*")) {
    headers["Vary"] = "Origin";
  }
  const response = res ?? new Response(null, { status: 204 });
  Object.entries(headers).forEach(([key, value]) => response.headers.set(key, value));
  return response;
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
