import "server-only";
import { createServerClient } from "@supabase/ssr";
import type { ConnectedConfig } from "../config";
import type {
  AuthCookieOptions,
  AuthProvider,
  CookieJar,
  SendResult,
  SessionState,
  VerifyResult,
} from "./provider";

/*
 * Supabase binding of the provider-neutral auth contract. This is the only module that
 * imports a Supabase package. No browser Supabase client exists: tokens live in httpOnly
 * cookies and the browser reaches the API only through the same-origin proxy.
 */

/** Link types accepted on /auth/callback with a token_hash (magic link, invite). */
const CALLBACK_TYPES = new Set(["email", "magiclink", "invite"]);

type RawCookieOptions = {
  maxAge?: number;
  expires?: Date;
};

export function hardenCookieOptions(
  options: RawCookieOptions | undefined,
  config: Pick<ConnectedConfig, "secureCookies">,
): AuthCookieOptions {
  const hardened: AuthCookieOptions = {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: config.secureCookies,
  };
  // Bound browser persistence; server/provider session revocation remains a separate gate.
  const limit = 8 * 60 * 60;
  hardened.maxAge = typeof options?.maxAge === "number" && Number.isFinite(options.maxAge)
    ? Math.max(0, Math.min(options.maxAge, limit)) : limit;
  if (options?.expires instanceof Date) {
    hardened.expires = new Date(Math.min(options.expires.getTime(), Date.now() + limit * 1000));
  }
  return hardened;
}

type ErrorLike = { status?: number; code?: string; name?: string } | null | undefined;

function isUnavailable(error: ErrorLike) {
  if (!error) return false;
  if (error.name === "AuthRetryableFetchError") return true;
  return typeof error.status === "number" ? error.status >= 500 || error.status === 0 : true;
}

function isRateLimited(error: ErrorLike) {
  return !!error && (error.status === 429 || error.code === "over_email_send_rate_limit");
}

export function createSupabaseAuth(config: ConnectedConfig, jar: CookieJar): AuthProvider {
  const client = createServerClient(config.supabaseUrl, config.supabaseAnonKey, {
    cookies: {
      getAll: () => jar.getAll(),
      setAll: (cookies, headers) => {
        jar.setAll(
          cookies.map(({ name, value, options }) => ({
            name,
            value,
            options: hardenCookieOptions(options as RawCookieOptions, config),
          })),
          headers,
        );
      },
    },
    cookieOptions: { httpOnly: true, sameSite: "lax", path: "/", secure: config.secureCookies },
  });

  return {
    async getSession(): Promise<SessionState> {
      try {
        const { data, error } = await client.auth.getClaims();
        if (error) return isUnavailable(error) ? { state: "unavailable" } : { state: "signed_out" };
        const claims = data?.claims;
        if (!claims || typeof claims.sub !== "string" || typeof claims.iss !== "string") {
          return { state: "signed_out" };
        }
        const { data: current } = await client.auth.getSession();
        const accessToken = current.session?.access_token;
        if (!accessToken) return { state: "signed_out" };
        return { state: "signed_in", subject: `${claims.iss}|${claims.sub}`, accessToken };
      } catch {
        return { state: "unavailable" };
      }
    },

    async sendSignInEmail(email: string, callbackUrl: string): Promise<SendResult> {
      try {
        const { error } = await client.auth.signInWithOtp({
          email,
          options: { emailRedirectTo: callbackUrl, shouldCreateUser: false },
        });
        if (!error) return "sent";
        // Per-address throttling must not reveal whether this address has an account.
        if (isRateLimited(error)) return "sent";
        if (isUnavailable(error)) return "unavailable";
        // Unknown address, sign-ups disabled and similar: report "sent" so the page never
        // reveals whether an account exists.
        return "sent";
      } catch {
        return "unavailable";
      }
    },

    async verifyEmailCode(email: string, code: string): Promise<VerifyResult> {
      try {
        const { error } = await client.auth.verifyOtp({ email, token: code, type: "email" });
        if (!error) return "signed_in";
        if (isRateLimited(error)) return "rate_limited";
        if (isUnavailable(error)) return "unavailable";
        return "invalid";
      } catch {
        return "unavailable";
      }
    },

    async completeCallback(params: URLSearchParams): Promise<boolean> {
      try {
        const code = params.get("code");
        if (code) {
          const { error } = await client.auth.exchangeCodeForSession(code);
          return !error;
        }
        const tokenHash = params.get("token_hash");
        const type = params.get("type");
        if (tokenHash && type && CALLBACK_TYPES.has(type)) {
          const { error } = await client.auth.verifyOtp({
            token_hash: tokenHash,
            type: type as "email" | "magiclink" | "invite",
          });
          return !error;
        }
        return false;
      } catch {
        return false;
      }
    },

    async signOut(): Promise<void> {
      try {
        await client.auth.signOut({ scope: "local" });
      } catch {
        // Cookies are cleared by the caller regardless.
      }
    },
  };
}
