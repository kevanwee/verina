import { randomBytes, timingSafeEqual } from "node:crypto";
import { connection, NextResponse, type NextRequest } from "next/server";
import { connectedConfig } from "@/lib/connected/config";
import { authForResponse } from "@/lib/connected/auth/server";
import { safeReturnTo } from "@/lib/connected/return-to";
import { DEFAULT_SIGNED_IN_PATH, PATHS } from "@/lib/connected/routes";
import { RETURN_TO_COOKIE } from "@/lib/connected/sign-in-flow";

const CONFIRM_COOKIE = "verina-callback-confirm";
const NO_STORE = "private, no-store, max-age=0";

function privateResponse(response: NextResponse) {
  response.headers.set("Cache-Control", NO_STORE);
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

function credential(params: URLSearchParams): URLSearchParams | null {
  const code = params.getAll("code");
  const hash = params.getAll("token_hash");
  const type = params.getAll("type");
  const valid = (value: string) => value.length > 0 && value.length <= 4096 && !/[\x00-\x20\x7f]/.test(value);
  if (code.length === 1 && hash.length === 0 && valid(code[0])) {
    return new URLSearchParams({ code: code[0] });
  }
  if (hash.length === 1 && code.length === 0 && type.length === 1 && valid(hash[0]) &&
      ["email", "magiclink", "invite"].includes(type[0])) {
    return new URLSearchParams({ token_hash: hash[0], type: type[0] });
  }
  return null;
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!);
}

/** GET is deliberately non-consuming: link scanners cannot establish a session. */
export async function GET(request: NextRequest) {
  await connection();
  const config = connectedConfig();
  if (config === null) return new NextResponse(null, { status: 404 });
  const params = credential(request.nextUrl.searchParams);
  if (params === null) {
    return privateResponse(NextResponse.redirect(new URL(`${PATHS.signIn}?error=link`, config.publicOrigin), 303));
  }
  const confirmation = randomBytes(32).toString("hex");
  const fields = [...params, ["confirmation", confirmation]].map(([name, value]) =>
    `<input type="hidden" name="${escapeHtml(name)}" value="${escapeHtml(value)}">`,
  ).join("");
  const response = new NextResponse(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Confirm sign-in | Verina</title></head><body><main><h1>Confirm sign-in</h1><p>Continue only if you requested this sign-in link or expected this account invitation.</p><form method="post" action="${escapeHtml(new URL(PATHS.callback, config.publicOrigin).href)}">${fields}<button type="submit">Continue to Verina</button></form><p><a href="${escapeHtml(new URL(PATHS.signIn, config.publicOrigin).href)}">Use an email code instead</a></p></main></body></html>`, {
    headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'; script-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'" },
  });
  response.cookies.set(CONFIRM_COOKIE, confirmation, { httpOnly: true, sameSite: "strict", secure: config.secureCookies, path: "/auth/callback", maxAge: 600 });
  return privateResponse(response);
}

/** A user-confirmed same-origin POST is the only path that consumes credentials. */
export async function POST(request: NextRequest) {
  await connection();
  const config = connectedConfig();
  if (config === null) return new NextResponse(null, { status: 404 });
  const site = request.headers.get("sec-fetch-site");
  if (request.headers.get("origin") !== config.publicOrigin || (site !== null && site !== "same-origin")) {
    return privateResponse(new NextResponse(null, { status: 403 }));
  }
  if (request.headers.get("content-type")?.split(";", 1)[0] !== "application/x-www-form-urlencoded") {
    return privateResponse(new NextResponse(null, { status: 415 }));
  }
  // Bound the stream, including requests without a declared Content-Length.
  const reader = request.body?.getReader();
  if (!reader) return privateResponse(new NextResponse(null, { status: 400 }));
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16 * 1024) {
        await reader.cancel();
        return privateResponse(new NextResponse(null, { status: 413 }));
      }
      chunks.push(value);
    }
  } catch {
    return privateResponse(new NextResponse(null, { status: 400 }));
  }
  const fields = new URLSearchParams(Buffer.concat(chunks).toString("utf8"));
  const confirmation = fields.getAll("confirmation");
  const cookie = request.cookies.get(CONFIRM_COOKIE)?.value;
  if (confirmation.length !== 1 || !cookie || !/^[a-f0-9]{64}$/.test(cookie) ||
      !/^[a-f0-9]{64}$/.test(confirmation[0]) ||
      !timingSafeEqual(Buffer.from(cookie), Buffer.from(confirmation[0]))) {
    return privateResponse(new NextResponse(null, { status: 403 }));
  }
  const params = credential(fields);
  if (!params) return privateResponse(new NextResponse(null, { status: 400 }));
  const returnTo = safeReturnTo(request.cookies.get(RETURN_TO_COOKIE)?.value);
  let response = NextResponse.redirect(new URL(returnTo ?? DEFAULT_SIGNED_IN_PATH, config.publicOrigin), 303);
  const completed = await authForResponse(config, request, () => response).completeCallback(params);
  if (!completed) {
    const target = new URL(PATHS.signIn, config.publicOrigin);
    target.searchParams.set("error", "link");
    if (returnTo) target.searchParams.set("returnTo", returnTo);
    const failed = NextResponse.redirect(target, 303);
    for (const cookie of response.cookies.getAll()) failed.cookies.set(cookie);
    response = failed;
  }
  response.cookies.set(CONFIRM_COOKIE, "", { httpOnly: true, sameSite: "strict", secure: config.secureCookies, path: "/auth/callback", maxAge: 0 });
  for (const path of ["/"]) {
    response.cookies.set(RETURN_TO_COOKIE, "", { httpOnly: true, sameSite: "lax", secure: config.secureCookies, path, maxAge: 0 });
  }
  return privateResponse(response);
}
