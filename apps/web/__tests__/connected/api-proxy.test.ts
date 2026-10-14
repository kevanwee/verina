import { describe, expect, it, vi } from "vitest";
import { allowedUpstreamPath, BODY_LIMIT_BYTES } from "@/lib/connected/api/policy";
import { handleApiProxy, type ProxyDeps } from "@/lib/connected/api/proxy-handler";
import { readConnectedConfig, type ConnectedConfig } from "@/lib/connected/config";

const CONFIG = readConnectedConfig({
  VERINA_CONNECTED: "1",
  NEXT_PUBLIC_SUPABASE_URL: "https://example-project.supabase.co",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "sb_publishable_synthetic_key_for_tests_only",
  VERINA_API_BASE_URL: "http://127.0.0.1:8000",
}) as ConnectedConfig;

const TOKEN = "header.payload.signature-synthetic";
const KEY = "0b6f0f43-4bd7-4d7c-9a5e-3c0f6c1f9a11";

type Captured = { url: string; init: RequestInit };

function upstream(response: () => Response = () => Response.json({ ok: true })) {
  const calls: Captured[] = [];
  const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return response();
  });
  return { calls, fetchImpl };
}

function deps(overrides: Partial<ProxyDeps> = {}): ProxyDeps {
  return { config: CONFIG, token: async () => TOKEN, fetchImpl: upstream().fetchImpl, ...overrides };
}

function browserRequest(
  method: string,
  path: string,
  { body, headers = {} }: { body?: BodyInit; headers?: Record<string, string> } = {},
) {
  return new Request(`http://localhost:3000/api/v1/${path}`, {
    method,
    body,
    headers: { "sec-fetch-site": "same-origin", ...headers },
  });
}

const segments = (path: string) => path.split("/");

describe("API proxy allowlist", () => {
  it.each([
    ["GET", "me"],
    ["POST", "matters"],
    ["GET", "matters/mtr-1"],
    ["PATCH", "matters/mtr-1"],
    ["POST", "matters/mtr-1/conflict-checks"],
    ["POST", "matters/mtr-1/conflict-waivers"],
    ["GET", "admin/organizations"],
    ["POST", "admin/organizations"],
    ["GET", "admin/organizations/org-1"],
    ["PATCH", "admin/organizations/org-1"],
    ["GET", "organizations/org-1/members"],
    ["POST", "organizations/org-1/members"],
    ["PATCH", "organizations/org-1/members/act-1"],
    ["POST", "organizations/org-1/members/act-1/resend-invite"],
  ])("allows %s /v1/%s", (method, path) => {
    expect(allowedUpstreamPath(method, segments(path))).toBe(`/v1/${path}`);
  });

  it.each([
    ["DELETE", "matters/mtr-1"],
    ["PUT", "matters/mtr-1"],
    ["GET", "matters"],
    ["PATCH", "me"],
    ["GET", "matters/mtr-1/conflict-checks"],
    ["POST", "matters/mtr-1/conflict-checks/extra"],
    ["GET", "health"],
    ["GET", "admin/organizations/org-1/members"],
    ["DELETE", "organizations/org-1/members/act-1"],
    ["GET", "matters/.."],
    ["GET", "matters/..%2Fadmin"],
    ["GET", "matters/%2e%2e"],
    ["GET", "matters/a b"],
    ["GET", "matters/"],
    ["GET", `matters/${"a".repeat(129)}`],
    ["GET", "organizations/../admin/members"],
  ])("refuses %s /v1/%s", (method, path) => {
    expect(allowedUpstreamPath(method, segments(path))).toBeNull();
  });

  it("answers a uniform 404 without calling upstream for anything else", async () => {
    const { fetchImpl } = upstream();
    const response = await handleApiProxy(
      browserRequest("POST", "matters/mtr-1/delete", { body: "{}", headers: { "content-type": "application/json" } }),
      segments("matters/mtr-1/delete"),
      deps({ fetchImpl }),
    );
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("is 404 when connected mode is off", async () => {
    const { fetchImpl } = upstream();
    const response = await handleApiProxy(browserRequest("GET", "me"), ["me"], deps({ config: null, fetchImpl }));
    expect(response.status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("API proxy forwarding", () => {
  it("attaches the session token server-side and forwards only the three allowed headers", async () => {
    const { calls, fetchImpl } = upstream();
    await handleApiProxy(
      browserRequest("PATCH", "matters/mtr-1", {
        body: JSON.stringify({ title: "Synthetic supply agreement" }),
        headers: {
          "content-type": "application/json; charset=utf-8",
          "idempotency-key": KEY,
          "if-match": '"3"',
          cookie: "sb-test-auth-token=secret-cookie",
          authorization: "Bearer browser-supplied",
          "x-forwarded-for": "203.0.113.9",
          "user-agent": "synthetic",
          "x-custom": "1",
        },
      }),
      segments("matters/mtr-1"),
      deps({ fetchImpl }),
    );
    expect(calls).toHaveLength(1);
    const { url, init } = calls[0];
    expect(url).toBe("http://127.0.0.1:8000/v1/matters/mtr-1");
    expect(init.method).toBe("PATCH");
    expect(init.redirect).toBe("manual");
    const sent = Object.fromEntries(new Headers(init.headers).entries());
    expect(sent).toEqual({
      accept: "application/json",
      authorization: `Bearer ${TOKEN}`,
      "content-type": "application/json",
      "idempotency-key": KEY,
      "if-match": '"3"',
    });
    expect(new TextDecoder().decode(init.body as Uint8Array)).toBe(
      JSON.stringify({ title: "Synthetic supply agreement" }),
    );
  });

  it("passes status and only safe response headers back, with no-store and no CORS", async () => {
    const { fetchImpl } = upstream(
      () =>
        new Response(JSON.stringify({ matter_id: "mtr-1", revision: 4 }), {
          status: 200,
          headers: {
            "content-type": "application/json",
            etag: '"4"',
            "set-cookie": "upstream=1",
            "access-control-allow-origin": "*",
            "x-internal": "1",
            "cache-control": "public, max-age=600",
          },
        }),
    );
    const response = await handleApiProxy(browserRequest("GET", "matters/mtr-1"), segments("matters/mtr-1"), deps({ fetchImpl }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ matter_id: "mtr-1", revision: 4 });
    expect(response.headers.get("etag")).toBe('"4"');
    expect(response.headers.get("cache-control")).toBe("private, no-store, max-age=0");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(response.headers.get("access-control-allow-origin")).toBeNull();
    expect(response.headers.get("x-internal")).toBeNull();
  });

  it.each([401, 404, 409, 422, 428, 503])("relays upstream %i unchanged", async (status) => {
    const { fetchImpl } = upstream(() => Response.json({ error: "code" }, { status }));
    const response = await handleApiProxy(browserRequest("GET", "me"), ["me"], deps({ fetchImpl }));
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ error: "code" });
  });
});

describe("API proxy limits and refusals", () => {
  it("refuses a body over 16 KiB without forwarding it", async () => {
    const { fetchImpl } = upstream();
    const big = JSON.stringify({ title: "x".repeat(BODY_LIMIT_BYTES) });
    const response = await handleApiProxy(
      browserRequest("POST", "matters", { body: big, headers: { "content-type": "application/json" } }),
      ["matters"],
      deps({ fetchImpl }),
    );
    expect(response.status).toBe(413);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("accepts a body of exactly 16 KiB", async () => {
    const { fetchImpl } = upstream();
    const body = new Uint8Array(BODY_LIMIT_BYTES).fill(0x20);
    const response = await handleApiProxy(
      browserRequest("POST", "matters", { body, headers: { "content-type": "application/json" } }),
      ["matters"],
      deps({ fetchImpl }),
    );
    expect(response.status).toBe(200);
  });

  it("refuses a declared Content-Length over the cap before reading", async () => {
    const { fetchImpl } = upstream();
    const request = browserRequest("POST", "matters", {
      body: "{}",
      headers: { "content-type": "application/json", "content-length": String(BODY_LIMIT_BYTES + 1) },
    });
    const response = await handleApiProxy(request, ["matters"], deps({ fetchImpl }));
    expect(response.status).toBe(413);
  });

  it("refuses non-JSON bodies", async () => {
    const { fetchImpl } = upstream();
    const response = await handleApiProxy(
      browserRequest("POST", "matters", { body: "title=x", headers: { "content-type": "application/x-www-form-urlencoded" } }),
      ["matters"],
      deps({ fetchImpl }),
    );
    expect(response.status).toBe(415);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("answers 401 without calling upstream when there is no session", async () => {
    const { fetchImpl } = upstream();
    const response = await handleApiProxy(browserRequest("GET", "me"), ["me"], deps({ token: async () => null, fetchImpl }));
    expect(response.status).toBe(401);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses cross-site requests", async () => {
    const { fetchImpl } = upstream();
    const crossSite = await handleApiProxy(
      browserRequest("POST", "matters", { body: "{}", headers: { "content-type": "application/json", "sec-fetch-site": "cross-site" } }),
      ["matters"],
      deps({ fetchImpl }),
    );
    expect(crossSite.status).toBe(403);
    const foreignOrigin = new Request("http://localhost:3000/api/v1/matters", {
      method: "POST",
      body: "{}",
      headers: { "content-type": "application/json", origin: "https://evil.example" },
    });
    expect((await handleApiProxy(foreignOrigin, ["matters"], deps({ fetchImpl }))).status).toBe(403);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reports a timeout as 504 and a network failure as 502", async () => {
    const hanging = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        }),
    );
    const timedOut = await handleApiProxy(browserRequest("GET", "me"), ["me"], deps({ fetchImpl: hanging, timeoutMs: 10 }));
    expect(timedOut.status).toBe(504);
    expect(await timedOut.json()).toEqual({ error: "upstream_timeout" });

    const failing = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const unreachable = await handleApiProxy(browserRequest("GET", "me"), ["me"], deps({ fetchImpl: failing }));
    expect(unreachable.status).toBe(502);
  });

  it("never follows an upstream redirect", async () => {
    const { fetchImpl } = upstream(
      () => new Response(null, { status: 302, headers: { location: "https://elsewhere.example/" } }),
    );
    const response = await handleApiProxy(browserRequest("GET", "me"), ["me"], deps({ fetchImpl }));
    expect(response.status).toBe(502);
    expect(response.headers.get("location")).toBeNull();
  });

  it("never logs", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((level) =>
      vi.spyOn(console, level).mockImplementation(() => {}),
    );
    const { fetchImpl } = upstream(() => Response.json({ error: "validation_failed" }, { status: 422 }));
    await handleApiProxy(
      browserRequest("POST", "matters", { body: '{"title":"x"}', headers: { "content-type": "application/json", "idempotency-key": KEY } }),
      ["matters"],
      deps({ fetchImpl }),
    );
    for (const spy of spies) {
      expect(spy).not.toHaveBeenCalled();
      spy.mockRestore();
    }
  });
});
