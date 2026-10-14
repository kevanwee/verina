import { NextResponse } from "next/server";
import type { SessionRefresh } from "../gate";
import { createAuthProvider } from "./provider";

/**
 * Validates the session for a connected request and writes any refreshed cookies to both
 * the forwarded request (so the page or handler sees them) and the response.
 */
export const refreshSession: SessionRefresh = async (request, config, respond) => {
  const build = () => (respond ? respond(request) : NextResponse.next({ request }));
  let response = build();
  const provider = createAuthProvider(config, {
    getAll: () => request.cookies.getAll().map(({ name, value }) => ({ name, value })),
    setAll: (cookies, headers) => {
      for (const { name, value } of cookies) request.cookies.set(name, value);
      response = build();
      for (const { name, value, options } of cookies) response.cookies.set(name, value, options);
      for (const [key, value] of Object.entries(headers)) response.headers.set(key, value);
    },
  });
  const session = await provider.getSession();
  // "unavailable": let the page render its own "cannot reach Verina" state instead of
  // sending a possibly signed-in person back to a sign-in form that would fail as well.
  return { response, signedIn: session.state !== "signed_out" };
};
