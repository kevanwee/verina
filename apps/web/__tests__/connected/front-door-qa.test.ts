import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { exchange, providerFactory } = vi.hoisted(() => ({ exchange: vi.fn(), providerFactory: vi.fn() }));
vi.mock("@/lib/connected/auth/server", () => ({
  authForResponse: providerFactory.mockImplementation(() => ({ completeCallback: exchange })),
}));
vi.mock("next/server", async (original) => ({
  ...(await original<typeof import("next/server")>()), connection: async () => {},
}));
const { POST } = await import("../../app/(connected)/auth/callback/route");
const ORIGIN = "http://localhost:3000";
const NONCE = "a".repeat(64);

function post(credential: string) {
  return new NextRequest(`${ORIGIN}/auth/callback`, {
    method: "POST",
    headers: {
      origin: ORIGIN, "sec-fetch-site": "same-origin",
      "content-type": "application/x-www-form-urlencoded",
      cookie: `verina-callback-confirm=${NONCE}`,
    },
    body: `${credential}&confirmation=${NONCE}`,
  });
}

describe("independent front-door credential boundary", () => {
  beforeEach(() => {
    vi.stubEnv("VERINA_CONNECTED", "1");
    vi.stubEnv("VERINA_PUBLIC_ORIGIN", ORIGIN);
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example-project.supabase.co");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_synthetic_key_for_tests_only");
    vi.stubEnv("VERINA_API_BASE_URL", "http://127.0.0.1:8000");
    exchange.mockResolvedValue(true);
  });
  afterEach(() => { vi.unstubAllEnvs(); vi.clearAllMocks(); });

  it.each([
    "code=one&code=two", "code=one&token_hash=two&type=invite",
    "token_hash=one&type=invite&type=email", "token_hash=one&type=recovery",
    "code=has%20space", "code=control%00character", `code=${"x".repeat(4097)}`,
  ])("denies ambiguous or invalid credentials despite valid confirmation: %s", async (credential) => {
    const response = await POST(post(credential));
    expect(response.status).toBe(400);
    expect(providerFactory).not.toHaveBeenCalled();
    expect(exchange).not.toHaveBeenCalled();
  });

  it("disabled POST never constructs a provider even with matching origin and confirmation", async () => {
    vi.stubEnv("VERINA_CONNECTED", "0");
    expect((await POST(post("code=valid"))).status).toBe(404);
    expect(providerFactory).not.toHaveBeenCalled();
    expect(exchange).not.toHaveBeenCalled();
  });
});
