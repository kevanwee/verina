import { connection, type NextRequest } from "next/server";
import { connectedConfig } from "@/lib/connected/config";
import { getAccessToken } from "@/lib/connected/auth/server";
import { handleApiProxy } from "@/lib/connected/api/proxy-handler";

/*
 * Same-origin proxy to the Verina API (allowlist in lib/connected/api/policy.ts).
 * GET, POST and PATCH only; every other method gets Next's 405.
 */

async function proxy(request: NextRequest, context: RouteContext<"/api/v1/[...path]">) {
  await connection();
  const { path } = await context.params;
  const config = connectedConfig();
  return handleApiProxy(request, path, {
    config,
    token: async () => (config === null ? null : getAccessToken(config)),
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
