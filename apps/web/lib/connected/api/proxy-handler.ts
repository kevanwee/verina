import "server-only";
import type { ConnectedConfig } from "../config";
import {
  allowedUpstreamPath,
  BODY_LIMIT_BYTES,
  filterResponseHeaders,
  forwardRequestHeaders,
  isJsonContentType,
} from "./policy";
import { callUpstream, type FetchLike } from "./upstream";

/*
 * Same-origin proxy: /api/v1/<allowed route> -> VERINA_API_BASE_URL/v1/<route>.
 * The browser never holds the bearer token; this handler reads it from the session and
 * attaches it server-side. No CORS headers are ever added. Bodies, tokens and header values
 * are never logged.
 */

export type ProxyDeps = {
  config: ConnectedConfig | null;
  /** Current access token from the session, or null when signed out. */
  token: () => Promise<string | null>;
  fetchImpl?: FetchLike;
  timeoutMs?: number;
};

const NO_STORE = "private, no-store, max-age=0";

function error(status: number, code: string, extra: Record<string, string> = {}) {
  return Response.json({ error: code }, { status, headers: {
    "Cache-Control": NO_STORE,
    "Content-Security-Policy": "default-src 'none'; sandbox; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff", ...extra,
  } });
}

/** Reads at most BODY_LIMIT_BYTES; null when the body is larger. */
async function readBody(request: Request): Promise<Uint8Array | null> {
  const declared = request.headers.get("content-length");
  if (declared !== null && Number(declared) > BODY_LIMIT_BYTES) return null;
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > BODY_LIMIT_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

/** Browsers send Sec-Fetch-Site; older ones send Origin on POST and PATCH. */
function crossSite(request: Request, mutating: boolean) {
  const site = request.headers.get("sec-fetch-site");
  if (site !== null) return site !== "same-origin";
  if (!mutating) return false;
  const origin = request.headers.get("origin");
  return origin === null || origin !== new URL(request.url).origin;
}

export async function handleApiProxy(
  request: Request,
  segments: readonly string[],
  deps: ProxyDeps,
): Promise<Response> {
  if (deps.config === null) return error(404, "not_found");

  const method = request.method.toUpperCase();
  const path = allowedUpstreamPath(method, segments);
  if (path === null) return error(404, "not_found");

  const mutating = method !== "GET";
  if (crossSite(request, mutating)) return error(403, "forbidden");

  let body: Uint8Array | null = null;
  if (mutating) {
    body = await readBody(request);
    if (body === null) return error(413, "payload_too_large");
    if (body.byteLength > 0 && !isJsonContentType(request.headers.get("content-type"))) {
      return error(415, "unsupported_media_type");
    }
  }

  const token = await deps.token();
  if (token === null) {
    return error(401, "unauthenticated", { "WWW-Authenticate": 'Bearer realm="verina"' });
  }

  const result = await callUpstream(
    deps.config,
    {
      method: method as "GET" | "POST" | "PATCH",
      path,
      token,
      headers: forwardRequestHeaders(request.headers, (body?.byteLength ?? 0) > 0),
      body,
    },
    deps.fetchImpl,
    deps.timeoutMs,
  );

  // The outcome of a mutation is unknown in both cases; clients treat these as "unconfirmed"
  // and retry with the same Idempotency-Key.
  if (result.kind === "timeout") return error(504, "upstream_timeout");
  if (result.kind === "unreachable") return error(502, "upstream_unavailable");

  const noBody = result.status === 204 || result.status === 205 || result.status === 304;
  const headers = filterResponseHeaders(result.headers);
  headers.set("Content-Security-Policy", "default-src 'none'; sandbox; frame-ancestors 'none'");
  headers.set("X-Content-Type-Options", "nosniff");
  return new Response(noBody ? null : (result.body as BodyInit), {
    status: result.status,
    headers,
  });
}
