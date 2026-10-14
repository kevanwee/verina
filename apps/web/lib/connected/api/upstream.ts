import "server-only";
import type { ConnectedConfig } from "../config";
import { isJsonContentType, RESPONSE_LIMIT_BYTES, UPSTREAM_TIMEOUT_MS } from "./policy";

/*
 * Server-to-server calls to the Verina API. The bearer token is attached here and only
 * here. Nothing in this module logs a token, a body or a header value.
 */

export type UpstreamRequest = {
  method: "GET" | "POST" | "PATCH";
  /** "/v1/..." already validated against the route allowlist. */
  path: string;
  token: string;
  headers?: Headers;
  body?: Uint8Array | null;
};

export type UpstreamResult =
  | { kind: "response"; status: number; headers: Headers; body: Uint8Array }
  | { kind: "timeout" }
  | { kind: "unreachable" };

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

async function readCapped(response: Response, limit: number): Promise<Uint8Array | null> {
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

export async function callUpstream(
  config: ConnectedConfig,
  request: UpstreamRequest,
  fetchImpl: FetchLike = fetch,
  timeoutMs: number = UPSTREAM_TIMEOUT_MS,
): Promise<UpstreamResult> {
  const headers = new Headers(request.headers);
  headers.set("Authorization", `Bearer ${request.token}`);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  let response: Response;
  try {
    response = await fetchImpl(`${config.apiBaseUrl}${request.path}`, {
      method: request.method,
      headers,
      body: request.body && request.body.byteLength > 0 ? (request.body as BodyInit) : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    const name = (error as { name?: string } | null)?.name;
    return name === "TimeoutError" || name === "AbortError" ? { kind: "timeout" } : { kind: "unreachable" };
  }
  // The API never redirects; following one could send the bearer token elsewhere.
  if (response.status >= 300 && response.status < 400) return { kind: "unreachable" };
  // Never relay an upstream HTML error page under the application's trusted origin.
  if (![204, 205, 304].includes(response.status) &&
      !isJsonContentType(response.headers.get("content-type"))) {
    await response.body?.cancel();
    return { kind: "unreachable" };
  }
  try {
    const body = await readCapped(response, RESPONSE_LIMIT_BYTES);
    if (body === null) return { kind: "unreachable" };
    return { kind: "response", status: response.status, headers: response.headers, body };
  } catch (error) {
    const name = (error as { name?: string } | null)?.name;
    return name === "TimeoutError" || name === "AbortError" ? { kind: "timeout" } : { kind: "unreachable" };
  }
}

/** Parses a JSON body, or null when it is not JSON. */
export function jsonOf(body: Uint8Array): unknown {
  try {
    return JSON.parse(new TextDecoder().decode(body));
  } catch {
    return null;
  }
}
