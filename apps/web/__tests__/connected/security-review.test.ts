import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { handleApiProxy } from "@/lib/connected/api/proxy-handler";
import { readConnectedConfig } from "@/lib/connected/config";

const createProvider = vi.fn(() => { throw new Error("unexpected auth effect"); });
vi.mock("@/lib/connected/auth/provider", () => ({ createAuthProvider: () => createProvider() }));
vi.mock("next/server", async (original) => ({
  ...(await original<typeof import("next/server")>()), connection: async () => {},
}));
const { GET, POST } = await import("../../app/(connected)/auth/callback/route");
const origin = "http://localhost:3000";
const env = {
  VERINA_CONNECTED: "1", VERINA_PUBLIC_ORIGIN: origin,
  NEXT_PUBLIC_SUPABASE_URL: "https://security-project.supabase.co",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "sb_publishable_synthetic_security_fixture",
  VERINA_API_BASE_URL: "http://127.0.0.1:8000",
};
beforeEach(() => { for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value); });
afterEach(() => { vi.unstubAllEnvs(); vi.clearAllMocks(); });

it.each(["code=a&token_hash=b&type=invite", "code=a&code=b", "token_hash=a&type=invite&type=email"])(
  "callback scanner rejects ambiguous credentials without provider construction: %s", async (query) => {
    const response = await GET(new NextRequest(`${origin}/auth/callback?${query}`));
    expect(response.status).toBe(303);
    expect(createProvider).not.toHaveBeenCalled();
  },
);
it("duplicate confirmation and cross-site metadata cannot consume a credential", async () => {
  const nonce = "a".repeat(64);
  for (const [site, fields] of [
    ["same-origin", `code=a&confirmation=${nonce}&confirmation=${nonce}`],
    ["cross-site", `code=a&confirmation=${nonce}`],
  ]) {
    const response = await POST(new NextRequest(`${origin}/auth/callback`, {
      method: "POST", headers: { origin, "sec-fetch-site": site,
        "content-type": "application/x-www-form-urlencoded", cookie: `verina-callback-confirm=${nonce}` },
      body: fields,
    }));
    expect(response.status).toBe(403);
  }
  expect(createProvider).not.toHaveBeenCalled();
});
it("proxy denies unknown path and cross-site request before session refresh", async () => {
  const token = vi.fn(async () => "synthetic-token");
  const config = readConnectedConfig(env);
  const unknown = await handleApiProxy(new Request(`${origin}/api/v1/admin/users`), ["admin", "users"], { config, token });
  const cross = await handleApiProxy(new Request(`${origin}/api/v1/me`, {
    headers: { "sec-fetch-site": "cross-site" },
  }), ["me"], { config, token });
  expect(unknown.status).toBe(404);
  expect(cross.status).toBe(403);
  expect(token).not.toHaveBeenCalled();
});
it("upstream mislabeled HTML cannot become executable under application origin", async () => {
  const response = await handleApiProxy(new Request(`${origin}/api/v1/me`), ["me"], {
    config: readConnectedConfig(env), token: async () => "synthetic-token",
    fetchImpl: async () => new Response("<script>document.cookie</script>", {
      headers: { "content-type": "application/json", "set-cookie": "evil=value" },
    }),
  });
  expect(response.headers.get("content-type")).toBe("application/json");
  expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  expect(response.headers.get("content-security-policy")).toContain("sandbox");
  expect(response.headers.get("set-cookie")).toBeNull();
});
