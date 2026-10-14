import { connection, NextResponse, type NextRequest } from "next/server";
import { connectedConfig } from "@/lib/connected/config";
import { authForResponse } from "@/lib/connected/auth/server";
import { safeReturnTo } from "@/lib/connected/return-to";
import { DEFAULT_SIGNED_IN_PATH, PATHS } from "@/lib/connected/routes";
import { RETURN_TO_COOKIE } from "@/lib/connected/sign-in-flow";

/**
 * Completes an emailed sign-in link (PKCE `code`, or `token_hash` with type email,
 * magiclink or invite), then redirects to a validated same-origin path. The destination
 * comes only from the server-set returnTo cookie, checked against the allowlist; query
 * parameters can never choose where the browser goes next.
 */
export async function GET(request: NextRequest) {
  // Request-time only: never prerender a sign-in response at build time.
  await connection();
  const config = connectedConfig();
  if (config === null) return new NextResponse(null, { status: 404 });

  const returnTo = safeReturnTo(request.cookies.get(RETURN_TO_COOKIE)?.value);
  let response = NextResponse.redirect(new URL(returnTo ?? DEFAULT_SIGNED_IN_PATH, request.url), 303);
  const provider = authForResponse(config, request, () => response);
  const completed = await provider.completeCallback(request.nextUrl.searchParams);

  if (!completed) {
    const target = new URL(PATHS.signIn, request.url);
    target.searchParams.set("error", "link");
    if (returnTo) target.searchParams.set("returnTo", returnTo);
    const failed = NextResponse.redirect(target, 303);
    for (const cookie of response.cookies.getAll()) failed.cookies.set(cookie);
    response = failed;
  }

  response.cookies.set(RETURN_TO_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    secure: config.secureCookies,
    path: "/auth",
    maxAge: 0,
  });
  response.headers.set("Cache-Control", "private, no-store, max-age=0");
  // The callback URL carried a one-time credential; never send it on as a referrer.
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}
