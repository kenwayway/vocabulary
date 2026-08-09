/**
 * Keep every Cloudflare-provided Pages hostname as a redirect-only entrypoint.
 *
 * Cloudflare Access protects the custom hostname, not the production
 * `*.pages.dev` hostname. Running this middleware for every route prevents the
 * generated Pages URL (including immutable deployment URLs) from becoming an
 * unauthenticated side door to the vocabulary data.
 */

const CANONICAL_HOST = "english.sopoi.com";

export async function onRequest(context) {
  const url = new URL(context.request.url);

  if (url.hostname.endsWith(".pages.dev")) {
    url.protocol = "https:";
    url.hostname = CANONICAL_HOST;
    url.port = "";
    return Response.redirect(url.toString(), 308);
  }

  return context.next();
}
