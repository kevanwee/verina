/**
 * Client-side validation that mirrors the API's rules, so the server's generic 422 is rare.
 * The server stays the authority.
 */

/** Unicode categories the API refuses in text (control, format, line and paragraph separators). */
const HIDDEN = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u;
const HIDDEN_EXCEPT_NEWLINE_TAB = /[\p{Cf}\p{Zl}\p{Zp}]|(?![\n\t])\p{Cc}/u;

export type TextProblem = "blank" | "long" | "hidden";

/** Code points, as the API counts them (not UTF-16 units). */
export function codePoints(value: string) {
  return Array.from(value).length;
}

export function checkText(
  raw: string,
  max: number,
  { allowNewlines = false }: { allowNewlines?: boolean } = {},
): { value: string; problem: TextProblem | null } {
  const value = raw.normalize("NFC").trim();
  if (value.length === 0) return { value, problem: "blank" };
  if ((allowNewlines ? HIDDEN_EXCEPT_NEWLINE_TAB : HIDDEN).test(value)) {
    return { value, problem: "hidden" };
  }
  if (codePoints(value) > max) return { value, problem: "long" };
  return { value, problem: null };
}

export const NAME_MAX = 120;

/** Accounts contract: ^[a-z0-9](-?[a-z0-9]){1,39}$ */
export const SLUG_PATTERN = /^[a-z0-9](-?[a-z0-9]){1,39}$/;

export function checkSlug(raw: string): { value: string; problem: "blank" | "format" | null } {
  const value = raw.trim();
  if (value.length === 0) return { value, problem: "blank" };
  return { value, problem: SLUG_PATTERN.test(value) ? null : "format" };
}

/** Suggests a short name from an organization name; the user can still edit it. */
export function suggestSlug(name: string) {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/g, "");
}

export function checkEmail(raw: string): { value: string; problem: "blank" | "invalid" | null } {
  const value = raw.trim();
  if (value.length === 0) return { value, problem: "blank" };
  if (value.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
    return { value, problem: "invalid" };
  }
  return { value, problem: null };
}

export function checkCode(raw: string): { value: string; problem: "blank" | "format" | null } {
  const value = raw.replace(/\s+/g, "");
  if (value.length === 0) return { value, problem: "blank" };
  return { value, problem: /^\d{6,10}$/.test(value) ? null : "format" };
}
