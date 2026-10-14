"use client";

import { useActionState, useEffect, useRef } from "react";
import { CheckCircle } from "@phosphor-icons/react/dist/ssr";
import { AUTH } from "@/lib/connected/copy-accounts";
import { INITIAL_SIGN_IN, type SignInError, type SignInState } from "@/lib/connected/sign-in-flow";
import { AuthBroadcast } from "../_components/AuthBroadcast";
import { RequestAlert } from "../_components/RequestAlert";
import form from "../../workbench/intake/intake.module.css";
import styles from "../connected.module.css";

export type SignInNotice = "link" | "signed_out" | null;

type Action = (previous: SignInState, formData: FormData) => Promise<SignInState>;

const FIELD_ERRORS: Partial<Record<SignInError, string>> = {
  email_blank: AUTH.EMAIL_BLANK,
  email_invalid: AUTH.EMAIL_INVALID,
  code_blank: AUTH.CODE_BLANK,
  code_format: AUTH.CODE_FORMAT,
  code_invalid: AUTH.CODE_INVALID,
};

export function SignInForm({
  action,
  returnTo,
  notice,
}: {
  action: Action;
  returnTo: string | null;
  notice: SignInNotice;
}) {
  const [state, formAction, pending] = useActionState(action, INITIAL_SIGN_IN);
  const emailRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const checkRef = useRef<HTMLHeadingElement>(null);
  const alertRef = useRef<HTMLHeadingElement>(null);

  const error = state.error;
  const blocking = error === "rate_limited" || error === "unavailable";
  const emailError = error?.startsWith("email_") ? FIELD_ERRORS[error] : undefined;
  const codeError = error?.startsWith("code_") ? FIELD_ERRORS[error] : undefined;

  // One focus target per response (INTAKE_PERSISTENCE_STATES.md section 8).
  useEffect(() => {
    if (state.revision === 0) return;
    if (blocking) alertRef.current?.focus();
    else if (emailError) emailRef.current?.focus();
    else if (codeError) codeRef.current?.focus();
    else if (state.step === "code") checkRef.current?.focus();
    else emailRef.current?.focus();
  }, [state.revision, state.step, blocking, emailError, codeError]);

  const guard = (event: React.FormEvent) => {
    if (pending) event.preventDefault();
  };

  const alert = blocking ? (
    <RequestAlert headingRef={alertRef} heading={AUTH.SIGN_IN_TITLE}>
      <p>{error === "rate_limited" ? AUTH.RATE_LIMITED : AUTH.UNAVAILABLE}</p>
    </RequestAlert>
  ) : null;

  return (
    <div className={styles.narrow}>
      <div className={styles.pageHead}>
        <h1 id="sign-in-title" className={styles.pageTitle}>
          {AUTH.SIGN_IN_TITLE}
        </h1>
        <p className={styles.lede}>{AUTH.SIGN_IN_LEDE}</p>
      </div>

      {notice === "signed_out" ? (
        <>
          <AuthBroadcast message="signed-out" />
          <p className={styles.status} role="status">
            <CheckCircle weight="bold" aria-hidden="true" focusable="false" />
            {AUTH.SIGNED_OUT}
          </p>
        </>
      ) : null}

      {notice === "link" && state.revision === 0 ? (
        <RequestAlert heading={AUTH.SIGN_IN_TITLE}>
          <p>{AUTH.LINK_FAILED}</p>
        </RequestAlert>
      ) : null}

      <section className={form.panel} aria-busy={pending || undefined} aria-labelledby={state.step === "code" ? "check-heading" : "sign-in-title"}>
        {state.step === "email" ? (
          <>
            {alert}
            <form action={formAction} onSubmit={guard} noValidate className={styles.stack}>
              <input type="hidden" name="returnTo" value={returnTo ?? ""} />
              <div className={form.field} data-invalid={emailError ? "" : undefined}>
                <label htmlFor="sign-in-email" className={form.label}>
                  {AUTH.EMAIL_LABEL}
                </label>
                <input
                  ref={emailRef}
                  id="sign-in-email"
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  spellCheck={false}
                  defaultValue={state.email}
                  readOnly={pending}
                  aria-invalid={emailError ? true : undefined}
                  aria-describedby={emailError ? "sign-in-email-error" : undefined}
                  className={form.input}
                />
                {emailError ? (
                  <p id="sign-in-email-error" className={form.error}>
                    {emailError}
                  </p>
                ) : null}
              </div>
              <div className={styles.inlineActions}>
                <button
                  type="submit"
                  name="intent"
                  value="send"
                  className={form.buttonPrimary}
                  aria-disabled={pending || undefined}
                >
                  {pending ? AUTH.SENDING : AUTH.SEND}
                </button>
              </div>
            </form>
          </>
        ) : (
          <>
            <h2 id="check-heading" ref={checkRef} tabIndex={-1} className={styles.sectionTitle}>
              {AUTH.CHECK_HEADING}
            </h2>
            <p className={styles.note}>{AUTH.checkBody(state.email)}</p>
            {alert}
            <form action={formAction} onSubmit={guard} noValidate className={styles.stack}>
              <input type="hidden" name="returnTo" value={returnTo ?? ""} />
              <input type="hidden" name="email" value={state.email} />
              <div className={form.field} data-invalid={codeError ? "" : undefined}>
                <label htmlFor="sign-in-code" className={form.label}>
                  {AUTH.CODE_LABEL}
                </label>
                <span id="sign-in-code-hint" className={form.hint}>
                  {AUTH.CODE_HINT}
                </span>
                <input
                  ref={codeRef}
                  id="sign-in-code"
                  name="code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={16}
                  spellCheck={false}
                  readOnly={pending}
                  aria-invalid={codeError ? true : undefined}
                  aria-describedby={
                    codeError ? "sign-in-code-hint sign-in-code-error" : "sign-in-code-hint"
                  }
                  className={form.input}
                />
                {codeError ? (
                  <p id="sign-in-code-error" className={form.error}>
                    {codeError}
                  </p>
                ) : null}
              </div>
              <div className={styles.inlineActions}>
                <button
                  type="submit"
                  name="intent"
                  value="verify"
                  className={form.buttonPrimary}
                  aria-disabled={pending || undefined}
                >
                  {pending ? AUTH.VERIFYING : AUTH.VERIFY}
                </button>
                <button
                  type="submit"
                  name="intent"
                  value="restart"
                  formNoValidate
                  className={form.buttonQuiet}
                  aria-disabled={pending || undefined}
                >
                  {AUTH.RESTART}
                </button>
              </div>
            </form>
          </>
        )}
      </section>

      <p className={styles.note}>{AUTH.NO_ACCOUNT_NOTE}</p>
    </div>
  );
}
