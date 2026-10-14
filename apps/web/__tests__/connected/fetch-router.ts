import { vi } from "vitest";

/** A recorded browser request to the same-origin proxy. */
export type Call = { method: string; url: string; headers: Headers; body: string | null };

type Reply = Response | (() => Response | Promise<Response>) | "network-error";

/**
 * Fake fetch keyed by "METHOD /path". Each key takes a queue of replies; the last reply
 * repeats. Unknown requests fail the test loudly.
 */
export function fetchRouter(routes: Record<string, Reply | Reply[]>) {
  const queues = new Map(Object.entries(routes).map(([key, value]) => [key, Array.isArray(value) ? [...value] : [value]]));
  const calls: Call[] = [];
  const impl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const method = (init.method ?? "GET").toUpperCase();
    calls.push({
      method,
      url,
      headers: new Headers(init.headers),
      body: typeof init.body === "string" ? init.body : null,
    });
    const queue = queues.get(`${method} ${url}`);
    if (!queue || queue.length === 0) throw new Error(`Unexpected request ${method} ${url}`);
    const reply = queue.length > 1 ? queue.shift()! : queue[0];
    if (reply === "network-error") throw new TypeError("Failed to fetch");
    const response = typeof reply === "function" ? await reply() : reply.clone();
    return response;
  });
  return { impl, calls, of: (method: string, url: string) => calls.filter((c) => c.method === method && c.url === url) };
}

export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
