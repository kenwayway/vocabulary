/**
 * Cloudflare Access gate for /api/*.
 *
 * Access already blocks unauthenticated requests at the edge, but this endpoint
 * can commit to the repository, so it verifies the assertion itself rather than
 * trusting that the application's path rules were configured to cover /api.
 * If the Access variables are missing the API refuses to serve at all: an
 * unauthenticated write path is worse than a broken one.
 */

import { json } from "../_lib/notes.js";

const CERTS_TTL = 3600;

function teamDomain(env) {
  return String(env.CF_ACCESS_TEAM_DOMAIN || "")
    .replace(/^https?:\/\//, "")
    .replace(/\/+$/, "");
}

function base64urlToBytes(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function decodeSegment(value) {
  return JSON.parse(new TextDecoder().decode(base64urlToBytes(value)));
}

async function fetchCerts(domain) {
  const response = await fetch(`https://${domain}/cdn-cgi/access/certs`, {
    cf: { cacheTtl: CERTS_TTL, cacheEverything: true },
  });
  if (!response.ok) return null;
  return response.json();
}

/** Verify an Access JWT and return its claims, or null if anything is off. */
async function verify(token, domain, audience) {
  const parts = String(token).split(".");
  if (parts.length !== 3) return null;

  let header;
  let claims;
  try {
    header = decodeSegment(parts[0]);
    claims = decodeSegment(parts[1]);
  } catch {
    return null;
  }

  if (header.alg !== "RS256") return null;

  const now = Math.floor(Date.now() / 1000);
  // 60s of slack for clock drift, in both directions.
  if (typeof claims.exp === "number" && claims.exp + 60 < now) return null;
  if (typeof claims.nbf === "number" && claims.nbf - 60 > now) return null;
  if (claims.iss !== `https://${domain}`) return null;

  const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!audiences.includes(audience)) return null;

  const certs = await fetchCerts(domain);
  if (!certs || !Array.isArray(certs.keys)) return null;
  const jwk = certs.keys.find((k) => k.kid === header.kid);
  if (!jwk) return null;

  const key = await crypto.subtle.importKey(
    "jwk",
    { kty: jwk.kty, n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"]
  );

  const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    base64urlToBytes(parts[2]),
    signed
  );
  return ok ? claims : null;
}

function readToken(request) {
  const header = request.headers.get("Cf-Access-Jwt-Assertion");
  if (header) return header;
  const cookies = request.headers.get("Cookie") || "";
  const match = /(?:^|;\s*)CF_Authorization=([^;]+)/.exec(cookies);
  return match ? match[1] : null;
}

export async function onRequest(context) {
  const { request, env, next, data } = context;

  const domain = teamDomain(env);
  const audience = env.CF_ACCESS_AUD;
  if (!domain || !audience) {
    return json(503, {
      error:
        "This deployment has no Cloudflare Access configuration, so the write API is disabled.",
    });
  }

  const token = readToken(request);
  if (!token) {
    return json(401, { error: "Not signed in." });
  }

  const claims = await verify(token, domain, audience);
  if (!claims) {
    return json(401, { error: "Your session is not valid. Reload the page to sign in again." });
  }

  // A second fence: even inside the Access application, only these addresses
  // may write. Leave ALLOWED_EMAILS unset to accept anyone Access let through.
  const allowed = String(env.ALLOWED_EMAILS || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  const email = String(claims.email || "").toLowerCase();
  if (allowed.length && !allowed.includes(email)) {
    return json(403, { error: "This account is not allowed to edit the notebook." });
  }

  data.identity = { email: claims.email || "" };
  return next();
}
