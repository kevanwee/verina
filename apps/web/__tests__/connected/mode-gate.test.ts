import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { describe, expect, it, vi } from "vitest";
import { readConnectedConfig, type ConnectedConfig } from "@/lib/connected/config";
import { NOT_FOUND_REWRITE, runGate, type SessionRefresh } from "@/lib/connected/gate";
import { classifyConnectedPath } from "@/lib/connected/routes";
import { config as proxyConfig } from "../../proxy";

const CONNECTED_ENV = {
  VERINA_CONNECTED: "1",
  NEXT_PUBLIC_SUPABASE_URL: "https://example-project.supabase.co",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "sb_publishable_synthetic_key_for_tests_only",
  VERINA_API_BASE_URL: "http://127.0.0.1:8000",
  NODE_ENV: "test",
};

const CONFIG = readConnectedConfig(CONNECTED_ENV) as ConnectedConfig;

function request(path: string) {
  return new NextRequest(new URL(path, "http://localhost:3000"));
}

function refreshWith(signedIn: boolean) {
  return vi.fn<SessionRefresh>(async () => ({ response: NextResponse.next(), signedIn }));
}

const PREVIEW_PATHS = ["/", "/workbench", "/workbench/intake", "/robots.txt"];
const CONNECTED_PAGES = [
  "/sign-in",
  "/sign-out",
  "/auth/callback",
  "/account",
  "/not-linked",
  "/admin",
  "/admin/organizations/org-1",
  "/settings/members",
];

describe("connected configuration", () => {
  it("is off unless VERINA_CONNECTED is exactly 1", () => {
    expect(readConnectedConfig({})).toBeNull();
    expect(readConnectedConfig({ ...CONNECTED_ENV, VERINA_CONNECTED: "true" })).toBeNull();
    expect(readConnectedConfig({ ...CONNECTED_ENV, VERINA_CONNECTED: "0" })).toBeNull();
    expect(CONFIG).toMatchObject({
      supabaseUrl: "https://example-project.supabase.co",
      apiBaseUrl: "http://127.0.0.1:8000",
      secureCookies: true,
    });
  });

  it("fails closed when any required variable is missing or unsafe", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const key of [
      "NEXT_PUBLIC_SUPABASE_URL",
      "NEXT_PUBLIC_SUPABASE_ANON_KEY",
      "VERINA_API_BASE_URL",
    ] as const) {
      expect(readConnectedConfig({ ...CONNECTED_ENV, [key]: undefined })).toBeNull();
      expect(readConnectedConfig({ ...CONNECTED_ENV, [key]: "" })).toBeNull();
    }
    // Plain http is only allowed for loopback; credentials and queries are refused.
    expect(
      readConnectedConfig({ ...CONNECTED_ENV, VERINA_API_BASE_URL: "http://api.example.com" }),
    ).toBeNull();
    expect(
      readConnectedConfig({ ...CONNECTED_ENV, VERINA_API_BASE_URL: "https://u:p@api.example.com" }),
    ).toBeNull();
    expect(
      readConnectedConfig({ ...CONNECTED_ENV, NEXT_PUBLIC_SUPABASE_URL: "javascript:alert(1)" }),
    ).toBeNull();
    // The warning names variables but never prints a value.
    for (const [message] of warn.mock.calls) {
      expect(String(message)).not.toContain(CONNECTED_ENV.NEXT_PUBLIC_SUPABASE_ANON_KEY);
      expect(String(message)).not.toContain("supabase.co");
    }
    warn.mockRestore();
  });

  it("keeps Secure cookies off only for the development server", () => {
    expect(readConnectedConfig({ ...CONNECTED_ENV, NODE_ENV: "development" })?.secureCookies).toBe(
      false,
    );
    expect(readConnectedConfig({ ...CONNECTED_ENV, NODE_ENV: "production" })?.secureCookies).toBe(
      true,
    );
  });
});

describe("connected route handlers", () => {
  it("are never prerendered: every GET handler waits for the request first", () => {
    const root = join(__dirname, "..", "..", "app", "(connected)");
    const handlers: string[] = [];
    const walk = (path: string) => {
      for (const entry of readdirSync(path)) {
        const full = join(path, entry);
        if (statSync(full).isDirectory()) walk(full);
        else if (entry === "route.ts") handlers.push(full);
      }
    };
    walk(root);
    expect(handlers.length).toBeGreaterThan(0);
    for (const file of handlers) {
      const source = readFileSync(file, "utf8");
      if (/export (async function|const) GET\b/.test(source)) {
        expect(source, file).toMatch(/await connection\(\);/);
      }
    }
  });
});

describe("mode gate (proxy.ts)", () => {
  it("never matches the public preview routes", () => {
    for (const path of PREVIEW_PATHS) expect(classifyConnectedPath(path)).toBeNull();
    const matchers = proxyConfig.matcher;
    for (const path of PREVIEW_PATHS) {
      for (const pattern of matchers) {
        const prefix = pattern.replace("/:path*", "");
        expect(path === prefix || path.startsWith(`${prefix}/`)).toBe(false);
      }
    }
  });

  it("passes preview routes through without reading config or touching the session", async () => {
    const readConfig = vi.fn(() => CONFIG);
    const refresh = refreshWith(true);
    for (const path of PREVIEW_PATHS) {
      const response = await runGate(request(path), readConfig, refresh);
      expect(response.headers.get("x-middleware-next")).toBe("1");
    }
    expect(readConfig).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("answers 404 for every connected page when connected mode is off", async () => {
    const refresh = refreshWith(true);
    for (const path of CONNECTED_PAGES) {
      const response = await runGate(request(path), () => null, refresh);
      expect(response.headers.get("x-middleware-rewrite")).toContain(NOT_FOUND_REWRITE);
    }
    expect(refresh).not.toHaveBeenCalled();
  });

  it("answers a JSON 404 for the API proxy when connected mode is off", async () => {
    const response = await runGate(request("/api/v1/me"), () => null, refreshWith(true));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
    expect(response.headers.get("cache-control")).toContain("no-store");
  });

  it("sends a signed-out visitor to sign-in with a validated returnTo", async () => {
    const response = await runGate(request("/settings/members"), () => CONFIG, refreshWith(false));
    expect(response.status).toBe(303);
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/sign-in");
    expect(location.searchParams.get("returnTo")).toBe("/settings/members");
  });

  it("drops an unknown path from returnTo instead of echoing it", async () => {
    const response = await runGate(request("/admin/unknown/x"), () => CONFIG, refreshWith(false));
    const location = new URL(response.headers.get("location")!);
    expect(location.searchParams.has("returnTo")).toBe(false);
  });

  it("lets a signed-in visitor through with no-store caching", async () => {
    const response = await runGate(request("/account"), () => CONFIG, refreshWith(true));
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.headers.get("cache-control")).toContain("no-store");
  });

  it("does not redirect API calls or public auth routes", async () => {
    const api = await runGate(request("/api/v1/me"), () => CONFIG, refreshWith(false));
    expect(api.headers.get("x-middleware-next")).toBe("1");
    const refresh = refreshWith(false);
    const signIn = await runGate(request("/sign-in"), () => CONFIG, refresh);
    expect(signIn.headers.get("x-middleware-next")).toBe("1");
    expect(refresh).not.toHaveBeenCalled();
  });
});
