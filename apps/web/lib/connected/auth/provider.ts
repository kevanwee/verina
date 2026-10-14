/**
 * Provider-neutral authentication contract (INTAKE_PERSISTENCE_STATES.md section 5.1).
 *
 * Everything outside lib/connected/auth/ depends on these types only. The provider binding
 * (`createAuthProvider`) is the single swap point; today it is Supabase via @supabase/ssr,
 * and `supabase.ts` is the only file in the app that imports a Supabase package.
 */

import type { ConnectedConfig } from "../config";
import { createSupabaseAuth } from "./supabase";

/** Normalised cookie options. Auth cookies are always httpOnly, SameSite=Lax, path "/". */
export type AuthCookieOptions = {
  httpOnly: true;
  sameSite: "lax";
  path: "/";
  secure: boolean;
  maxAge?: number;
  expires?: Date;
};

export type AuthCookie = { name: string; value: string; options: AuthCookieOptions };

/** Where the provider reads and writes its session cookies for one request. */
export type CookieJar = {
  getAll(): { name: string; value: string }[];
  /** `headers` are cache headers the provider requires on any response that sets cookies. */
  setAll(cookies: AuthCookie[], headers: Record<string, string>): void;
};

export type SessionState =
  | { state: "signed_in"; subject: string; accessToken: string }
  | { state: "signed_out" }
  /** The provider could not be reached; the session may or may not be valid. */
  | { state: "unavailable" };

export type SendResult = "sent" | "rate_limited" | "unavailable";
export type VerifyResult = "signed_in" | "invalid" | "rate_limited" | "unavailable";

export interface AuthProvider {
  /** Validates (and if needed refreshes) the session held in cookies. */
  getSession(): Promise<SessionState>;
  /**
   * Emails a one-time sign-in link and code. Never creates an account: accounts exist only
   * when an administrator adds a member. Unknown addresses report "sent" (no enumeration).
   */
  sendSignInEmail(email: string, callbackUrl: string): Promise<SendResult>;
  /** Verifies the one-time code from the email. */
  verifyEmailCode(email: string, code: string): Promise<VerifyResult>;
  /** Completes a link sign-in (`code`, or `token_hash` with an allowed `type`). */
  completeCallback(params: URLSearchParams): Promise<boolean>;
  /** Ends this device's session at the provider and clears its cookies. */
  signOut(): Promise<void>;
}

export const createAuthProvider: (config: ConnectedConfig, jar: CookieJar) => AuthProvider =
  createSupabaseAuth;

/** Names of the provider's cookies, so sign-out can clear them even if the provider fails. */
export function isAuthCookieName(name: string) {
  return name.startsWith("sb-");
}
