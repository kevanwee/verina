import { connection, NextResponse } from "next/server";
import { connectedConfig } from "@/lib/connected/config";
import { getSession, subjectTag } from "@/lib/connected/auth/server";

const HEADERS = { "Cache-Control": "private, no-store, max-age=0" };

/**
 * Session probe for the browser auth surface: signed in or not, plus an opaque subject tag
 * for identity-change checks. Never returns a token, subject id, email or name.
 */
export async function GET() {
  await connection();
  const config = connectedConfig();
  if (config === null) return NextResponse.json({ error: "not_found" }, { status: 404, headers: HEADERS });
  const session = await getSession(config);
  if (session.state === "unavailable") {
    return NextResponse.json({ error: "unavailable" }, { status: 503, headers: HEADERS });
  }
  if (session.state === "signed_out") return NextResponse.json({ signedIn: false }, { headers: HEADERS });
  return NextResponse.json(
    { signedIn: true, subject: subjectTag(session.subject) },
    { headers: HEADERS },
  );
}
