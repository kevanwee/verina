/**
 * Same-origin API proxy policy (pure). The browser may reach exactly these Verina API routes
 * through /api/v1/..., with exactly these methods. Everything else is a uniform 404 and is
 * never forwarded.
 *
 * Sources: ADR 007 route contract (matters) and the accounts contract v1 (me, admin,
 * members).
 */

import { ID_SEGMENT } from "../routes";

export type Method = "GET" | "POST" | "PATCH";

const ID = Symbol("id");
type Segment = string | typeof ID;

const ROUTES: readonly (readonly [Method, readonly Segment[]])[] = [
  ["GET", ["me"]],
  // ADR 007
  ["POST", ["matters"]],
  ["GET", ["matters", ID]],
  ["PATCH", ["matters", ID]],
  ["POST", ["matters", ID, "conflict-checks"]],
  ["POST", ["matters", ID, "conflict-waivers"]],
  // Accounts contract: platform admin
  ["GET", ["admin", "organizations"]],
  ["POST", ["admin", "organizations"]],
  ["GET", ["admin", "organizations", ID]],
  ["PATCH", ["admin", "organizations", ID]],
  // Accounts contract: members
  ["GET", ["organizations", ID, "members"]],
  ["POST", ["organizations", ID, "members"]],
  ["PATCH", ["organizations", ID, "members", ID]],
  ["POST", ["organizations", ID, "members", ID, "resend-invite"]],
];

/** Returns the upstream path ("/v1/...") for an allowed request, or null. */
export function allowedUpstreamPath(method: string, segments: readonly string[]): string | null {
  for (const [allowedMethod, pattern] of ROUTES) {
    if (allowedMethod !== method || pattern.length !== segments.length) continue;
    const matches = pattern.every((part, index) =>
      part === ID ? ID_SEGMENT.test(segments[index]) : part === segments[index],
    );
    if (matches) return `/v1/${segments.map((segment) => encodeURIComponent(segment)).join("/")}`;
  }
  return null;
}

/** Same cap as the API's streaming body limit. */
export const BODY_LIMIT_BYTES = 16 * 1024;

/** Per-attempt upstream timeout (INTAKE_PERSISTENCE_STATES.md section 4.3; Q12). */
export const UPSTREAM_TIMEOUT_MS = 15_000;

/** Responses are small JSON documents; anything larger is a defect, not data. */
export const RESPONSE_LIMIT_BYTES = 256 * 1024;

const TOKEN_LIKE = /^[\x21-\x7e]{1,128}$/;

/**
 * The only request headers forwarded upstream: Content-Type (JSON only), Idempotency-Key
 * and If-Match. Cookies, Authorization from the browser, forwarding headers and everything
 * else are dropped; the proxy adds Accept and the server-side bearer token itself.
 */
export function forwardRequestHeaders(incoming: Headers, hasBody: boolean): Headers {
  const headers = new Headers({ Accept: "application/json" });
  if (hasBody) headers.set("Content-Type", "application/json");
  for (const name of ["Idempotency-Key", "If-Match"]) {
    const value = incoming.get(name);
    if (value !== null && TOKEN_LIKE.test(value)) headers.set(name, value);
  }
  return headers;
}

/** The only response headers passed back to the browser. */
const RESPONSE_HEADERS = ["Content-Type", "ETag", "Retry-After"] as const;

export function filterResponseHeaders(upstream: Headers): Headers {
  const headers = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.get(name);
    if (value !== null) headers.set(name, value);
  }
  headers.set("Cache-Control", "private, no-store, max-age=0");
  return headers;
}

export function isJsonContentType(value: string | null) {
  if (value === null) return false;
  const [type] = value.split(";");
  return type.trim().toLowerCase() === "application/json";
}
