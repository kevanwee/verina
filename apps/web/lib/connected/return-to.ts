/**
 * Same-origin return paths after sign-in. Only exact, known application paths are accepted;
 * anything else (absolute URLs, scheme-relative "//host", backslashes, encoded characters,
 * dot segments, query strings, fragments, unknown paths) is refused and the caller falls
 * back to the default landing page. This closes open redirects through returnTo.
 */

const ID = "[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}";

const ALLOWED: readonly RegExp[] = [
  /^\/account$/,
  /^\/admin$/,
  new RegExp(`^/admin/organizations/${ID}$`),
  /^\/settings\/members$/,
  /^\/auth\/signed-in$/,
  /^\/workbench\/intake$/,
  new RegExp(`^/workbench/intake/${ID}$`),
];

const BASE = "https://verina.invalid";

export function safeReturnTo(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  if (raw.length === 0 || raw.length > 300) return null;
  // Must be a rooted path, never scheme-relative or a Windows-style path.
  if (raw[0] !== "/" || raw[1] === "/" || raw.includes("\\")) return null;
  // No control characters, whitespace or percent-encoding of any kind.
  if (/[\s%\u0000-\u001f\u007f]/.test(raw)) return null;
  let url: URL;
  try {
    url = new URL(raw, BASE);
  } catch {
    return null;
  }
  if (url.origin !== BASE || url.search !== "" || url.hash !== "") return null;
  // Reject anything the URL parser normalised (dot segments and the like).
  if (url.pathname !== raw) return null;
  return ALLOWED.some((pattern) => pattern.test(raw)) ? raw : null;
}
