/*
 * Browser half of the auth surface (INTAKE_PERSISTENCE_STATES.md section 5.1):
 * getSession, signIn({ returnTo }), reauthenticate and onIdentityChange.
 *
 * getAccessToken is deliberately server-only (server.ts): tokens sit in httpOnly cookies and
 * the browser calls the API through the same-origin proxy, which attaches the bearer token.
 */

import { PATHS } from "../routes";
import { safeReturnTo } from "../return-to";

export const AUTH_CHANNEL = "verina-auth";

export type AuthMessage = { type: "signed-in" } | { type: "signed-out" };

export type BrowserSession = { signedIn: boolean; subject: string | null };

/** One same-origin request; no token or subject id is returned, only an opaque tag. */
export async function getSession(): Promise<BrowserSession> {
  const response = await fetch(PATHS.session, {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  // 503: the provider is unreachable, so the answer is unknown rather than "signed out".
  if (response.status >= 500) throw new Error("session state unavailable");
  if (!response.ok) return { signedIn: false, subject: null };
  const body: unknown = await response.json().catch(() => null);
  if (body && typeof body === "object" && (body as { signedIn?: unknown }).signedIn === true) {
    const subject = (body as { subject?: unknown }).subject;
    return { signedIn: true, subject: typeof subject === "string" ? subject : null };
  }
  return { signedIn: false, subject: null };
}

export function signInHref(returnTo?: string | null) {
  const safe = safeReturnTo(returnTo);
  return safe ? `${PATHS.signIn}?returnTo=${encodeURIComponent(safe)}` : PATHS.signIn;
}

/** Full-page sign-in. Unsaved page memory is lost (copy C-08 warns first where relevant). */
export function signIn({ returnTo }: { returnTo?: string | null } = {}) {
  window.location.assign(signInHref(returnTo));
}

export function broadcastAuth(message: AuthMessage) {
  if (typeof BroadcastChannel === "undefined") return;
  const channel = new BroadcastChannel(AUTH_CHANNEL);
  channel.postMessage(message);
  channel.close();
}

/**
 * Signs the same person back in without unloading this page: sign-in opens in a separate
 * window, and this resolves when that window reports success. If the window cannot open
 * (blocked), falls back to a full-page sign-in and resolves "redirected".
 */
export function reauthenticate(): Promise<"signed-in" | "redirected"> {
  return new Promise((resolve) => {
    const popup = window.open(signInHref(PATHS.signedIn), "verina-sign-in");
    if (!popup || typeof BroadcastChannel === "undefined") {
      signIn({ returnTo: window.location.pathname });
      resolve("redirected");
      return;
    }
    const channel = new BroadcastChannel(AUTH_CHANNEL);
    channel.onmessage = (event: MessageEvent<AuthMessage>) => {
      if (event.data?.type === "signed-in") {
        channel.close();
        resolve("signed-in");
      }
    };
  });
}

/**
 * Calls `callback` when the signed-in subject differs from `baseline` (sign-out, or another
 * account signed in from another tab). Checks when another tab reports a change and when
 * this window regains focus. Returns an unsubscribe function.
 */
export function onIdentityChange(
  baseline: string | null,
  callback: (next: BrowserSession) => void,
): () => void {
  let stopped = false;
  const check = async () => {
    try {
      const next = await getSession();
      if (!stopped && next.subject !== baseline) callback(next);
    } catch {
      // Offline: nothing to compare; the next API call reports the session state.
    }
  };
  const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(AUTH_CHANNEL);
  if (channel) channel.onmessage = () => void check();
  const onFocus = () => void check();
  window.addEventListener("focus", onFocus);
  return () => {
    stopped = true;
    channel?.close();
    window.removeEventListener("focus", onFocus);
  };
}
