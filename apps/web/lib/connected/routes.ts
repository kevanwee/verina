/**
 * Route map for connected mode. Pure, shared by proxy.ts, pages and tests.
 *
 * The public preview routes (/, /workbench, /workbench/intake) are not listed here and are
 * never gated, redirected or given a session by the proxy.
 */

/** Same pattern as the API's opaque identifiers (verina.access.domain._ID_PATTERN). */
export const ID_SEGMENT = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

export const PATHS = {
  signIn: "/sign-in",
  signOut: "/sign-out",
  callback: "/auth/callback",
  session: "/auth/session",
  signedIn: "/auth/signed-in",
  notLinked: "/not-linked",
  account: "/account",
  admin: "/admin",
  members: "/settings/members",
  apiPrefix: "/api/v1/",
} as const;

/** Where a linked account lands after signing in when no valid returnTo was given. */
export const DEFAULT_SIGNED_IN_PATH: string = PATHS.account;

export function adminOrganizationPath(orgId: string) {
  return `/admin/organizations/${encodeURIComponent(orgId)}`;
}

export type ConnectedRouteKind =
  /** Route handler for the same-origin API proxy: JSON 404 when off, no redirects. */
  | "api"
  /** Sign-in, sign-out, callback and session probe: reachable without a session. */
  | "public"
  /** Pages that need a signed-in session; the proxy sends anyone else to sign-in. */
  | "protected";

/**
 * Classifies a pathname. Returns null for every route that is not part of connected mode,
 * including the whole public preview.
 */
export function classifyConnectedPath(pathname: string): ConnectedRouteKind | null {
  if (pathname === "/api/v1" || pathname.startsWith(PATHS.apiPrefix)) return "api";
  if (
    pathname === PATHS.signIn ||
    pathname === PATHS.signOut ||
    pathname === PATHS.callback ||
    pathname === PATHS.session
  ) {
    return "public";
  }
  if (
    pathname === PATHS.notLinked ||
    pathname === PATHS.account ||
    pathname === PATHS.admin ||
    pathname.startsWith(`${PATHS.admin}/`) ||
    pathname === "/settings" ||
    pathname.startsWith("/settings/") ||
    pathname === "/auth" ||
    pathname.startsWith("/auth/")
  ) {
    return "protected";
  }
  return null;
}
