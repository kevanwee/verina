import "server-only";
import { createHash } from "node:crypto";
import { cookies } from "next/headers";
import type { NextRequest, NextResponse } from "next/server";
import type { ConnectedConfig } from "../config";
import {
  createAuthProvider,
  isAuthCookieName,
  type AuthProvider,
  type CookieJar,
  type SessionState,
} from "./provider";

/*
 * Server half of the auth surface (INTAKE_PERSISTENCE_STATES.md section 5.1):
 * getSession and getAccessToken. Tokens never leave the server: the browser half
 * (client.ts) only learns whether it is signed in and an opaque subject tag.
 */

/** Provider bound to the request cookie store (pages, route handlers, server actions). */
export async function authFromCookies(config: ConnectedConfig): Promise<AuthProvider> {
  const store = await cookies();
  const jar: CookieJar = {
    getAll: () => store.getAll().map(({ name, value }) => ({ name, value })),
    setAll: (list) => {
      try {
        for (const { name, value, options } of list) store.set(name, value, options);
      } catch {
        // Server Components cannot set cookies; proxy.ts has already refreshed the session.
      }
    },
  };
  return createAuthProvider(config, jar);
}

/** Provider that writes cookies onto a response the caller will return (route handlers). */
export function authForResponse(
  config: ConnectedConfig,
  request: NextRequest,
  response: () => NextResponse,
): AuthProvider {
  return createAuthProvider(config, {
    getAll: () => request.cookies.getAll().map(({ name, value }) => ({ name, value })),
    setAll: (list, headers) => {
      const target = response();
      for (const { name, value, options } of list) target.cookies.set(name, value, options);
      for (const [key, value] of Object.entries(headers)) target.headers.set(key, value);
    },
  });
}

export async function getSession(config: ConnectedConfig): Promise<SessionState> {
  return (await authFromCookies(config)).getSession();
}

/** A current bearer token for the Verina API, or null. Never put it in a URL or a log. */
export async function getAccessToken(config: ConnectedConfig): Promise<string | null> {
  const session = await getSession(config);
  return session.state === "signed_in" ? session.accessToken : null;
}

/**
 * Opaque, stable tag for "who is signed in", so the browser can notice an identity change
 * without ever seeing the subject id or token.
 */
export function subjectTag(subject: string) {
  return createHash("sha256").update(`verina-subject:${subject}`).digest("base64url").slice(0, 22);
}

/** Removes every provider cookie from a response (sign-out fallback). */
export function clearAuthCookies(request: NextRequest, response: NextResponse, secure: boolean) {
  for (const { name } of request.cookies.getAll()) {
    if (isAuthCookieName(name)) {
      response.cookies.set(name, "", {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure,
        maxAge: 0,
      });
    }
  }
}

/** True when a state-changing request comes from this origin (CSRF defence in depth). */
export function isSameOrigin(request: NextRequest) {
  const site = request.headers.get("sec-fetch-site");
  if (site !== null) return site === "same-origin";
  const origin = request.headers.get("origin");
  return origin !== null && origin === request.nextUrl.origin;
}
