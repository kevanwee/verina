import "server-only";
import { cache } from "react";
import { redirect } from "next/navigation";
import type { ConnectedConfig } from "./config";
import { getSession, subjectTag } from "./auth/server";
import { callUpstream, jsonOf, type FetchLike } from "./api/upstream";
import { parseMe, type LinkedMe } from "./me";
import { PATHS } from "./routes";
import { safeReturnTo } from "./return-to";

/** Who is looking at a connected page, from the session and GET /v1/me. */
export type Viewer =
  | { kind: "signed_out" }
  | { kind: "unlinked" }
  /** `subject` is the opaque tag the browser compares for identity changes. */
  | { kind: "linked"; me: LinkedMe; subject?: string }
  /** Signed in at the provider, but the API refused the token (401). */
  | { kind: "rejected" }
  /** The provider or the API could not be reached, or answered unexpectedly. */
  | { kind: "unavailable" };

export async function resolveViewer(
  config: ConnectedConfig,
  token: string | null | "unavailable",
  fetchImpl?: FetchLike,
): Promise<Viewer> {
  if (token === "unavailable") return { kind: "unavailable" };
  if (token === null) return { kind: "signed_out" };
  const result = await callUpstream(config, { method: "GET", path: "/v1/me", token }, fetchImpl);
  if (result.kind !== "response") return { kind: "unavailable" };
  if (result.status === 401) return { kind: "rejected" };
  if (result.status !== 200) return { kind: "unavailable" };
  const me = parseMe(jsonOf(result.body));
  if (me === null) return { kind: "unavailable" };
  return me.linked ? { kind: "linked", me } : { kind: "unlinked" };
}

/** One /v1/me call per request, however many components ask. */
export const loadViewer = cache(async (config: ConnectedConfig): Promise<Viewer> => {
  const session = await getSession(config);
  if (session.state !== "signed_in") {
    return resolveViewer(config, session.state === "unavailable" ? "unavailable" : null);
  }
  const viewer = await resolveViewer(config, session.accessToken);
  return viewer.kind === "linked" ? { ...viewer, subject: subjectTag(session.subject) } : viewer;
});

/**
 * For pages that need a linked account: signed-out visitors go to sign-in (returning here),
 * unlinked accounts go to the neutral not-linked page. Problems are returned for the page
 * to explain in place.
 */
export async function requireLinked(
  config: ConnectedConfig,
  currentPath: string,
): Promise<Exclude<Viewer, { kind: "signed_out" } | { kind: "unlinked" }>> {
  const viewer = await loadViewer(config);
  if (viewer.kind === "signed_out") {
    const returnTo = safeReturnTo(currentPath);
    redirect(returnTo ? `${PATHS.signIn}?returnTo=${encodeURIComponent(returnTo)}` : PATHS.signIn);
  }
  if (viewer.kind === "unlinked") redirect(PATHS.notLinked);
  return viewer;
}
