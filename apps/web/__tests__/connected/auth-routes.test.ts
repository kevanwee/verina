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

const { GET: confirmationPage, POST: callbackPost } = await import("../../app/(connected)/auth/callback/route");
const { POST: signOut } = await import("../../app/(connected)/sign-out/route");

const ORIGIN = "http://localhost:3000";

function stubConnected() {
  vi.stubEnv("VERINA_CONNECTED", "1");
  vi.stubEnv("VERINA_PUBLIC_ORIGIN", "http://localhost:3000");
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

async function callback(request: NextRequest) {
  const page = await confirmationPage(request);
  if (page.status !== 200) return page;
  const html = await page.text();
  const nonce = /name="confirmation" value="([a-f0-9]{64})"/.exec(html)![1];
  const body = new URLSearchParams(request.nextUrl.searchParams);
  body.set("confirmation", nonce);
  return callbackPost(new NextRequest(request.url, {
    method: "POST",
    headers: { origin: ORIGIN, "sec-fetch-site": "same-origin", "content-type": "application/x-www-form-urlencoded", cookie: `${request.headers.get("cookie") ?? ""}; verina-callback-confirm=${nonce}` },
    body: body.toString(),
  }));
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

  it("GET never consumes a credential, including scanner requests", async () => {
    const response = await confirmationPage(callbackRequest("?code=abc"));
    expect(response.status).toBe(200);
    expect(provider.completeCallback).not.toHaveBeenCalled();
    expect(await response.text()).toContain('method="post"');
    expect(response.headers.get("content-security-policy")).toContain("script-src 'none'");
    expect(response.headers.get("set-cookie")).toMatch(/SameSite=strict/i);
  });

  it.each([undefined, "https://evil.example"])("POST requires exact configured Origin (%s)", async (origin) => {
    const response = await callbackPost(new NextRequest(`${ORIGIN}/auth/callback`, {
      method: "POST", headers: { ...(origin ? { origin } : {}), "sec-fetch-site": "same-origin" }, body: "code=abc",
    }));
    expect(response.status).toBe(403);
    expect(provider.completeCallback).not.toHaveBeenCalled();
  });

  it("POST rejects missing confirmation and duplicate credentials", async () => {
    const missing = await callbackPost(new NextRequest(`${ORIGIN}/auth/callback`, {
      method: "POST", headers: { origin: ORIGIN, "content-type": "application/x-www-form-urlencoded" }, body: "code=abc",
    }));
    expect(missing.status).toBe(403);
    const duplicate = await confirmationPage(callbackRequest("?code=abc&code=def"));
    expect(duplicate.status).toBe(303);
    expect(provider.completeCallback).not.toHaveBeenCalled();
  });

  it("confirmation form ignores poisoned request host and escapes credentials", async () => {
    const response = await confirmationPage(new NextRequest('https://evil.example/auth/callback?code=%22%3E%3Cscript%3E'));
    const html = await response.text();
    expect(html).toContain(`action="${ORIGIN}/auth/callback"`);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&quot;&gt;&lt;script&gt;');
  });

  it("POST refuses a mismatched confirmation and a streamed oversized body", async () => {
    const nonce = "a".repeat(64);
    const request = (body: string) => new NextRequest(`${ORIGIN}/auth/callback`, {
      method: "POST", headers: { origin: ORIGIN, "content-type": "application/x-www-form-urlencoded", cookie: `verina-callback-confirm=${nonce}` }, body,
    });
    expect((await callbackPost(request(`code=abc&confirmation=${"b".repeat(64)}`))).status).toBe(403);
    expect((await callbackPost(request(`code=${"x".repeat(17000)}`))).status).toBe(413);
    expect(provider.completeCallback).not.toHaveBeenCalled();
  });

  it("POST redirects to configured origin despite a poisoned URL host", async () => {
    const nonce = "a".repeat(64);
    const response = await callbackPost(new NextRequest("https://evil.example/auth/callback", {
      method: "POST", headers: { origin: ORIGIN, "content-type": "application/x-www-form-urlencoded", cookie: `verina-callback-confirm=${nonce}` }, body: `code=abc&confirmation=${nonce}`,
    }));
    expect(response.headers.get("location")).toBe(`${ORIGIN}/workbench/intake`);
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
    expect(response.headers.get("location")).toBe(`${ORIGIN}/workbench/intake`);
  });

  it("ignores any destination supplied in the query string", async () => {
    for (const param of ["returnTo", "next", "redirect_to"]) {
      const response = await callback(
        callbackRequest(`?code=abc&${param}=${encodeURIComponent("https://evil.example")}`),
      );
      expect(new URL(response.headers.get("location")!).origin).toBe(ORIGIN);
      expect(response.headers.get("location")).toBe(`${ORIGIN}/workbench/intake`);
    }
  });

  it("sends a failed or expired link back to sign-in, keeping a safe returnTo", async () => {
    provider.completeCallback.mockResolvedValue(false);
    const response = await callback(
      callbackRequest("?code=expired", "/admin"),
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
      headers: { origin: ORIGIN, cookie: "sb-test-auth-token=abc; other=keep", ...headers },
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
