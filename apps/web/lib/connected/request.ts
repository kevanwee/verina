/**
 * Browser requests through the same-origin proxy (/api/v1/...), classified into the
 * outcomes the interface must explain (INTAKE_PERSISTENCE_STATES.md sections 4.3 and 6).
 *
 * A mutation is frozen: one Idempotency-Key belongs to exactly one (method, path, body,
 * If-Match) tuple. Retrying re-sends the identical request, so the API can replay its stored
 * receipt instead of recording the change twice.
 */

export type Outcome<T = unknown> =
  | { kind: "ok"; status: number; data: T; etag: string | null }
  /** Network failure, client timeout, or the proxy could not reach the API (502, 504). */
  | { kind: "unconfirmed" }
  /** 503: the API failed closed; the outcome of a mutation is still treated as unknown. */
  | { kind: "unavailable" }
  /** 401: session ended or the account was deactivated. */
  | { kind: "session" }
  /** 404: missing, other organization or not permitted (one uniform answer). */
  | { kind: "not_found" }
  /** 403: collection-level refusal (matter create). */
  | { kind: "forbidden" }
  | { kind: "conflict"; code: string }
  | { kind: "invalid"; code: string }
  /** 400, 413, 415, 428, 500 and anything unexpected: a defect, not a user error. */
  | { kind: "defect"; code: string };

/** Keep the frozen request (and its key) after these outcomes, so Retry re-sends it. */
export function keepsKey(outcome: Outcome) {
  return outcome.kind === "unconfirmed" || outcome.kind === "unavailable" || outcome.kind === "session";
}

export type FrozenRequest = {
  readonly method: "POST" | "PATCH";
  /** Path under /v1, for example "/admin/organizations". */
  readonly path: string;
  readonly body: string;
  readonly key: string;
  readonly ifMatch?: string;
};

export type RequestOptions = {
  fetchImpl?: typeof fetch;
  /** Client timeout per attempt; longer than the proxy's 15 s so the proxy answers first. */
  timeoutMs?: number;
  /** Silent retries for network failure only (never for an HTTP status). */
  retryDelaysMs?: readonly number[];
  sleep?: (ms: number) => Promise<void>;
};

export const CLIENT_TIMEOUT_MS = 20_000;
export const RETRY_DELAYS_MS = [1_000, 3_000] as const;

const PROXY_PREFIX = "/api/v1";

function codeOf(json: unknown, fallback: string) {
  if (json && typeof json === "object" && typeof (json as { error?: unknown }).error === "string") {
    const code = (json as { error: string }).error;
    if (/^[a-z0-9_]{1,64}$/.test(code)) return code;
  }
  return fallback;
}

export function classify<T>(status: number, json: unknown, etag: string | null = null): Outcome<T> {
  if (status >= 200 && status < 300) return { kind: "ok", status, data: json as T, etag };
  switch (status) {
    case 401:
      return { kind: "session" };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not_found" };
    case 409:
      return { kind: "conflict", code: codeOf(json, "conflict") };
    case 422:
      return { kind: "invalid", code: codeOf(json, "validation_failed") };
    case 502:
    case 504:
      return { kind: "unconfirmed" };
    case 503:
      return { kind: "unavailable" };
    default:
      return { kind: "defect", code: codeOf(json, `http_${status}`) };
  }
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function attempt<T>(
  path: string,
  init: RequestInit,
  { fetchImpl = fetch, timeoutMs = CLIENT_TIMEOUT_MS }: RequestOptions,
): Promise<Outcome<T> | "network" | "timeout"> {
  let response: Response;
  try {
    response = await fetchImpl(`${PROXY_PREFIX}${path}`, {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    // A timed-out attempt already waited long enough; only fast failures retry silently.
    return (error as { name?: string } | null)?.name === "TimeoutError" ? "timeout" : "network";
  }
  const text = await response.text().catch(() => "");
  let json: unknown = null;
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = null;
    }
  }
  return classify<T>(response.status, json, response.headers.get("etag"));
}

export async function apiRead<T>(path: string, options: RequestOptions = {}): Promise<Outcome<T>> {
  const result = await attempt<T>(path, { method: "GET", headers: { Accept: "application/json" } }, options);
  return result === "network" || result === "timeout" ? { kind: "unconfirmed" } : result;
}

export function newKey() {
  return crypto.randomUUID();
}

export function freeze(
  method: FrozenRequest["method"],
  path: string,
  body: unknown,
  ifMatch?: string,
): FrozenRequest {
  return Object.freeze({ method, path, body: JSON.stringify(body ?? {}), key: newKey(), ifMatch });
}

/** Sends a frozen request; identical bytes and key on every attempt. */
export async function sendFrozen<T>(frozen: FrozenRequest, options: RequestOptions = {}): Promise<Outcome<T>> {
  const { retryDelaysMs = RETRY_DELAYS_MS, sleep = defaultSleep } = options;
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
    "Idempotency-Key": frozen.key,
  };
  if (frozen.ifMatch !== undefined) headers["If-Match"] = frozen.ifMatch;
  for (let index = 0; ; index += 1) {
    const result = await attempt<T>(frozen.path, { method: frozen.method, headers, body: frozen.body }, options);
    if (result === "timeout") return { kind: "unconfirmed" };
    if (result !== "network") return result;
    if (index >= retryDelaysMs.length) return { kind: "unconfirmed" };
    await sleep(retryDelaysMs[index]);
  }
}
