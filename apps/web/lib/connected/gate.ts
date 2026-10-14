import { NextResponse, type NextRequest } from "next/server";
import type { ConnectedConfig } from "./config";
import { classifyConnectedPath, intakeRewriteTarget, PATHS } from "./routes";
import { safeReturnTo } from "./return-to";
import { allowedUpstreamPath } from "./api/policy";

/**
 * Result of refreshing the provider session for one request. The proxy copies refreshed
 * cookies onto `response`; `signedIn` is false when there is no usable session.
 */
export type SessionRefresh = (
  request: NextRequest,
  config: ConnectedConfig,
  /** Builds the response to continue with (default: NextResponse.next). */
  respond?: (request: NextRequest) => NextResponse,
) => Promise<{ response: NextResponse; signedIn: boolean }>;

/** Path Next has no route for, so the rewrite renders the app's own 404 page with status 404. */
export const NOT_FOUND_REWRITE = "/__verina-not-found";

const NO_STORE = "private, no-store, max-age=0";

export function apiNotFound() {
  return NextResponse.json(
    { error: "not_found" },
    { status: 404, headers: { "Cache-Control": NO_STORE } },
  );
}

/**
 * The request-time mode gate and session step behind proxy.ts.
 *
 * - Not a connected route (/ and /workbench): passes through untouched. No config is read for
 *   it, no Supabase client is created and nothing is fetched.
 * - /workbench/intake with connected mode off: passes through untouched to the preview page,
 *   again without a session or any fetch. With it on: rewritten to the connected intake.
 * - Connected mode off or incomplete: every other connected route answers 404.
 * - Protected page without a session: redirect to sign-in with a validated returnTo.
 */
export async function runGate(
  request: NextRequest,
  readConfig: () => ConnectedConfig | null,
  refresh: SessionRefresh,
): Promise<NextResponse> {
  const pathname = request.nextUrl.pathname;
  const kind = classifyConnectedPath(pathname);
  if (kind === null) return NextResponse.next();

  const notFound = () => NextResponse.rewrite(new URL(NOT_FOUND_REWRITE, request.url), { status: 404 });
  if (kind === "internal") return notFound();

  const config = readConfig();
  if (config === null) {
    if (kind === "intake") return NextResponse.next();
    if (kind === "api") return apiNotFound();
    return notFound();
  }

  // Reject unknown/cross-site API requests before session refresh can contact the IdP.
  if (kind === "api") {
    const segments = pathname.slice("/api/v1/".length).split("/");
    if (allowedUpstreamPath(request.method, segments) === null) return apiNotFound();
    const site = request.headers.get("sec-fetch-site");
    const mutating = request.method !== "GET";
    if ((site !== null && site !== "same-origin") ||
        (site === null && mutating && request.headers.get("origin") !== config.publicOrigin)) {
      return NextResponse.json({ error: "forbidden" }, {
        status: 403, headers: { "Cache-Control": NO_STORE },
      });
    }
  }

  if (kind === "intake") {
    const target = intakeRewriteTarget(pathname);
    if (target === null) return notFound();
    // Signed out is a state of the intake page (sign-in panel), not a redirect.
    const { response } = await refresh(request, config, (forwarded) =>
      NextResponse.rewrite(new URL(target, request.url), { request: forwarded }),
    );
    response.headers.set("Cache-Control", NO_STORE);
    return response;
  }

  if (kind === "public") {
    const response = NextResponse.next();
    response.headers.set("Cache-Control", NO_STORE);
    return response;
  }

  // "api" and "protected": refresh the session cookie before the handler or page runs, so
  // a refreshed token is written to the response before anything streams.
  const { response, signedIn } = await refresh(request, config);
  response.headers.set("Cache-Control", NO_STORE);
  if (kind === "api" || signedIn) return response;

  const target = new URL(PATHS.signIn, config.publicOrigin);
  const returnTo = safeReturnTo(pathname);
  if (returnTo) target.searchParams.set("returnTo", returnTo);
  const redirect = NextResponse.redirect(target, 303);
  // Keep any cookie the provider cleared or rotated while finding there was no session.
  for (const cookie of response.cookies.getAll()) redirect.cookies.set(cookie);
  redirect.headers.set("Cache-Control", NO_STORE);
  return redirect;
}
