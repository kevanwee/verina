import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthProvider, CookieJar } from "@/lib/connected/auth/provider";

const provider = {
  getSession: vi.fn<AuthProvider["getSession"]>(),
  sendSignInEmail: vi.fn<AuthProvider["sendSignInEmail"]>(),
  verifyEmailCode: vi.fn<AuthProvider["verifyEmailCode"]>(),
  completeCallback: vi.fn<AuthProvider["completeCallback"]>(),
  signOut: vi.fn<AuthProvider["signOut"]>(),
};
let lastJar: CookieJar | null = null;

vi.mock("@/lib/connected/auth/provider", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/connected/auth/provider")>();
  return {
    ...actual,
    createAuthProvider: (_config: unknown, jar: CookieJar) => {
      lastJar = jar;
      return provider;
    },
  };
});

// Outside Next there is no request scope; connection() only marks the handler dynamic.
vi.mock("next/server", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/server")>()),
  connection: async () => {},
}));

const { GET: callback } = await import("../../app/(connected)/auth/callback/route");
const { POST: signOut } = await import("../../app/(connected)/sign-out/route");

const ORIGIN = "http://localhost:3000";

function stubConnected() {
  vi.stubEnv("VERINA_CONNECTED", "1");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://example-project.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "sb_publishable_synthetic_key_for_tests_only");
  vi.stubEnv("VERINA_API_BASE_URL", "http://127.0.0.1:8000");
}

function callbackRequest(query: string, returnToCookie?: string) {
  const headers = new Headers();
  if (returnToCookie !== undefined) {
    headers.set("cookie", `verina-return-to=${encodeURIComponent(returnToCookie)}`);
  }
  return new NextRequest(new URL(`/auth/callback${query}`, ORIGIN), { headers });
}

describe("/auth/callback", () => {
  beforeEach(() => {
    stubConnected();
    provider.completeCallback.mockResolvedValue(true);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  it("is 404 when connected mode is off", async () => {
    vi.stubEnv("VERINA_CONNECTED", "");
    const response = await callback(callbackRequest("?code=abc"));
    expect(response.status).toBe(404);
    expect(provider.completeCallback).not.toHaveBeenCalled();
  });

  it("exchanges the code and returns to the validated, server-set path", async () => {
    const response = await callback(callbackRequest("?code=abc", "/settings/members"));
    expect(provider.completeCallback.mock.calls[0][0].get("code")).toBe("abc");
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(`${ORIGIN}/settings/members`);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(response.headers.get("referrer-policy")).toBe("no-referrer");
    // The one-shot returnTo cookie is cleared.
    expect(response.headers.get("set-cookie")).toMatch(/verina-return-to=;.*Max-Age=0/i);
  });

  it.each([
    ["absolute URL", "https://evil.example/account"],
    ["scheme-relative", "//evil.example"],
    ["backslash", "/\\evil.example"],
    ["unknown path", "/api/v1/me"],
  ])("rejects an open redirect via the cookie (%s)", async (_label, target) => {
    const response = await callback(callbackRequest("?code=abc", target));
    expect(response.headers.get("location")).toBe(`${ORIGIN}/account`);
  });

  it("ignores any destination supplied in the query string", async () => {
    for (const param of ["returnTo", "next", "redirect_to"]) {
      const response = await callback(
        callbackRequest(`?code=abc&${param}=${encodeURIComponent("https://evil.example")}`),
      );
      expect(new URL(response.headers.get("location")!).origin).toBe(ORIGIN);
      expect(response.headers.get("location")).toBe(`${ORIGIN}/account`);
    }
  });

  it("sends a failed or expired link back to sign-in, keeping a safe returnTo", async () => {
    provider.completeCallback.mockResolvedValue(false);
    const response = await callback(
      callbackRequest("?error=access_denied&error_code=otp_expired", "/admin"),
    );
    const location = new URL(response.headers.get("location")!);
    expect(location.origin).toBe(ORIGIN);
    expect(location.pathname).toBe("/sign-in");
    expect(location.searchParams.get("error")).toBe("link");
    expect(location.searchParams.get("returnTo")).toBe("/admin");
  });

  it("keeps cookies the provider wrote while failing", async () => {
    provider.completeCallback.mockImplementation(async () => {
      lastJar!.setAll(
        [
          {
            name: "sb-test-auth-token-code-verifier",
            value: "",
            options: { httpOnly: true, sameSite: "lax", path: "/", secure: true, maxAge: 0 },
          },
        ],
        {},
      );
      return false;
    });
    const response = await callback(callbackRequest("?code=bad"));
    expect(response.headers.get("set-cookie")).toContain("sb-test-auth-token-code-verifier=");
  });
});

describe("/sign-out", () => {
  beforeEach(stubConnected);
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  function signOutRequest(headers: Record<string, string>) {
    return new NextRequest(new URL("/sign-out", ORIGIN), {
      method: "POST",
      headers: { cookie: "sb-test-auth-token=abc; other=keep", ...headers },
    });
  }

  it("refuses a cross-site request", async () => {
    const response = await signOut(signOutRequest({ "sec-fetch-site": "cross-site" }));
    expect(response.status).toBe(403);
    expect(provider.signOut).not.toHaveBeenCalled();
    const noFetchMeta = await signOut(signOutRequest({ origin: "https://evil.example" }));
    expect(noFetchMeta.status).toBe(403);
  });

  it("ends the session, clears auth cookies and shows the signed-out notice", async () => {
    const response = await signOut(signOutRequest({ "sec-fetch-site": "same-origin" }));
    expect(provider.signOut).toHaveBeenCalledOnce();
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(`${ORIGIN}/sign-in?signedOut=1`);
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toMatch(/sb-test-auth-token=;/);
    expect(setCookie).toMatch(/HttpOnly/i);
    expect(setCookie).not.toContain("other=");
  });
});
