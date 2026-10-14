/**
 * Sign-in form logic, separated from the server action so it can be tested without Next.
 * Email one-time link and code only; no passwords, no self-service account creation.
 */

import type { AuthProvider } from "./auth/provider";
import { DEFAULT_SIGNED_IN_PATH, PATHS } from "./routes";
import { safeReturnTo } from "./return-to";
import { checkCode, checkEmail } from "./validation";

export type SignInError =
  | "email_blank"
  | "email_invalid"
  | "code_blank"
  | "code_format"
  | "code_invalid"
  | "rate_limited"
  | "unavailable";

export type SignInState = {
  step: "email" | "code";
  email: string;
  error: SignInError | null;
  /** Increments on every response so the form can move focus and announce again. */
  revision: number;
};

export const INITIAL_SIGN_IN: SignInState = { step: "email", email: "", error: null, revision: 0 };

export const RETURN_TO_COOKIE = "verina-return-to";

export type SignInDeps = {
  provider: () => Promise<AuthProvider>;
  /** Origin of this request, from the Origin header Next has already checked. */
  origin: string | null;
  rememberReturnTo: (path: string | null) => Promise<void>;
};

export type SignInOutcome = { state: SignInState } | { redirectTo: string };

function field(formData: FormData, name: string) {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export function callbackUrl(origin: string | null): string | null {
  if (!origin) return null;
  try {
    const url = new URL(origin);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return `${url.origin}${PATHS.callback}`;
  } catch {
    return null;
  }
}

export async function runSignIn(
  previous: SignInState,
  formData: FormData,
  deps: SignInDeps,
): Promise<SignInOutcome> {
  const revision = previous.revision + 1;
  const intent = field(formData, "intent");
  const returnTo = safeReturnTo(field(formData, "returnTo"));

  if (intent === "restart") {
    return { state: { step: "email", email: previous.email, error: null, revision } };
  }

  if (intent === "verify") {
    const email = checkEmail(field(formData, "email"));
    if (email.problem) {
      return { state: { step: "email", email: email.value, error: `email_${email.problem}`, revision } };
    }
    const code = checkCode(field(formData, "code"));
    if (code.problem) {
      return { state: { step: "code", email: email.value, error: `code_${code.problem}`, revision } };
    }
    const result = await (await deps.provider()).verifyEmailCode(email.value, code.value);
    if (result === "signed_in") return { redirectTo: returnTo ?? DEFAULT_SIGNED_IN_PATH };
    const error: SignInError = result === "invalid" ? "code_invalid" : result;
    return { state: { step: "code", email: email.value, error, revision } };
  }

  const email = checkEmail(field(formData, "email"));
  if (email.problem) {
    return { state: { step: "email", email: email.value, error: `email_${email.problem}`, revision } };
  }
  const target = callbackUrl(deps.origin);
  if (!target) return { state: { step: "email", email: email.value, error: "unavailable", revision } };
  await deps.rememberReturnTo(returnTo);
  const sent = await (await deps.provider()).sendSignInEmail(email.value, target);
  if (sent === "sent") return { state: { step: "code", email: email.value, error: null, revision } };
  return { state: { step: "email", email: email.value, error: sent, revision } };
}
