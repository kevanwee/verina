import type { NextRequest } from "next/server";
import { connectedConfig } from "@/lib/connected/config";
import { runGate } from "@/lib/connected/gate";
import { refreshSession } from "@/lib/connected/auth/proxy-session";

/*
 * Request-time gate for connected mode (sign-in, account, admin, settings, API proxy and
 * connected intake). / and /workbench never reach this function. /workbench/intake does,
 * and passes straight through to the unchanged preview when connected mode is off.
 */
export async function proxy(request: NextRequest) {
  return runGate(request, connectedConfig, refreshSession);
}

export const config = {
  matcher: [
    "/sign-in",
    "/sign-out",
    "/auth/:path*",
    "/not-linked",
    "/account",
    "/admin/:path*",
    "/settings/:path*",
    "/api/v1/:path*",
    "/workbench/intake/:path*",
    "/intake-connected/:path*",
  ],
};
