import { NextResponse, type NextRequest } from "next/server";
import { connectedConfig } from "@/lib/connected/config";
import { authForResponse, clearAuthCookies } from "@/lib/connected/auth/server";
import { PATHS } from "@/lib/connected/routes";

/**
 * Ends this device's session (POST only, same-origin only), clears every auth cookie even
 * if the provider cannot be reached, then shows the sign-in page with a signed-out notice.
 */
export async function POST(request: NextRequest) {
  const config = connectedConfig();
  if (config === null) return new NextResponse(null, { status: 404 });
  if (request.headers.get("origin") !== config.publicOrigin ||
      (request.headers.get("sec-fetch-site") !== null && request.headers.get("sec-fetch-site") !== "same-origin")) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  const target = new URL(PATHS.signIn, config.publicOrigin);
  target.searchParams.set("signedOut", "1");
  const response = NextResponse.redirect(target, 303);
  await authForResponse(config, request, () => response).signOut();
  clearAuthCookies(request, response, config.secureCookies);
  response.headers.set("Cache-Control", "private, no-store, max-age=0");
  return response;
}
