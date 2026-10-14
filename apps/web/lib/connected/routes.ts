/**
 * Route map for connected mode. Pure, shared by proxy.ts, pages and tests.
 *
 * The public preview routes (/ and /workbench) are never seen by the proxy. /workbench/intake
 * is shared: with connected mode off it passes through untouched to the preview page; with it
 * on, the proxy rewrites it to the connected intake (an internal path nobody can request
 * directly).
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
  intake: "/workbench/intake",
  /** Internal rewrite target for connected intake; direct requests always get 404. */
  internalIntake: "/intake-connected",
  apiPrefix: "/api/v1/",
} as const;

/** Where a linked account lands after signing in when no valid returnTo was given. */
export const DEFAULT_SIGNED_IN_PATH: string = PATHS.intake;

export function adminOrganizationPath(orgId: string) {
  return `/admin/organizations/${encodeURIComponent(orgId)}`;
}

export type ConnectedRouteKind =
  /** Route handler for the same-origin API proxy: JSON 404 when off, no redirects. */
  | "api"
  /** Sign-in, sign-out, callback and session probe: reachable without a session. */
  | "public"
  /** Pages that need a signed-in session; the proxy sends anyone else to sign-in. */
  | "protected"
  /** /workbench/intake[/id]: the preview when off, rewritten to connected intake when on. */
  | "intake"
  /** The rewrite target itself: never reachable directly. */
  | "internal";

/**
 * Classifies a pathname. Returns null for every route that is not part of connected mode,
 * including / and /workbench.
 */
export function classifyConnectedPath(pathname: string): ConnectedRouteKind | null {
  if (pathname === "/api/v1" || pathname.startsWith(PATHS.apiPrefix)) return "api";
  if (pathname === PATHS.internalIntake || pathname.startsWith(`${PATHS.internalIntake}/`)) {
    return "internal";
  }
  if (pathname === PATHS.intake || pathname.startsWith(`${PATHS.intake}/`)) return "intake";
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

/**
 * Connected intake rewrite target for /workbench/intake[/id], or null when the path is not a
 * valid intake route.
 */
export function intakeRewriteTarget(pathname: string): string | null {
  if (pathname === PATHS.intake) return PATHS.internalIntake;
  const rest = pathname.slice(PATHS.intake.length + 1);
  if (pathname.startsWith(`${PATHS.intake}/`) && ID_SEGMENT.test(rest)) {
    return `${PATHS.internalIntake}/${rest}`;
  }
  return null;
}
