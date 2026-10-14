"use client";

import { useEffect, useRef } from "react";
import { REQUEST } from "@/lib/connected/copy-accounts";
import type { Outcome } from "@/lib/connected/request";
import { RequestAlert } from "./RequestAlert";
import form from "../../workbench/intake/intake.module.css";

/**
 * Explains a request outcome that is not a field error, inside the panel that owns the
 * action, and moves focus to its heading. Returns null for "ok"; callers pass null for
 * outcomes they show as field errors instead.
 */
export function OutcomeAlert({
  id,
  outcome,
  read = false,
  conflictMessage,
  onRetry,
  onReauthenticate,
}: {
  id?: string;
  outcome: Outcome | null;
  /** A failed load rather than a failed save. */
  read?: boolean;
  /** Plain copy for a 409 the caller understands (null: not handled here). */
  conflictMessage?: (code: string) => string | null;
  onRetry?: () => void;
  onReauthenticate?: () => void;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const visible = outcome !== null && outcome.kind !== "ok";
  useEffect(() => {
    if (visible) headingRef.current?.focus();
  }, [visible, outcome]);

  if (!outcome || outcome.kind === "ok") return null;

  const retryButton = (label: string) =>
    onRetry ? (
      <button type="button" className={form.buttonPrimary} onClick={onRetry}>
        {label}
      </button>
    ) : null;

  switch (outcome.kind) {
    case "unconfirmed":
      if (read) {
        return (
          <RequestAlert id={id} headingRef={headingRef} heading={REQUEST.LOAD_FAILED_HEADING} actions={retryButton(REQUEST.TRY_AGAIN)}>
            <p>{REQUEST.LOAD_FAILED_BODY}</p>
          </RequestAlert>
        );
      }
      return (
        <RequestAlert id={id} tone="unknown" headingRef={headingRef} heading={REQUEST.UNCONFIRMED_HEADING} actions={retryButton(REQUEST.RETRY)}>
          <p>{REQUEST.UNCONFIRMED_BODY}</p>
        </RequestAlert>
      );
    case "unavailable":
      return read ? (
        <RequestAlert id={id} headingRef={headingRef} heading={REQUEST.LOAD_FAILED_HEADING} actions={retryButton(REQUEST.TRY_AGAIN)}>
          <p>{REQUEST.LOAD_FAILED_BODY}</p>
        </RequestAlert>
      ) : (
        <RequestAlert id={id} tone="unknown" headingRef={headingRef} heading={REQUEST.UNAVAILABLE_HEADING} actions={retryButton(REQUEST.TRY_AGAIN)}>
          <p>{REQUEST.UNAVAILABLE_BODY}</p>
        </RequestAlert>
      );
    case "session":
      return (
        <RequestAlert
          id={id}
          tone={read ? "error" : "unknown"}
          headingRef={headingRef}
          heading={REQUEST.SESSION_HEADING}
          actions={
            onReauthenticate ? (
              <button type="button" className={form.buttonPrimary} onClick={onReauthenticate}>
                {REQUEST.SIGN_IN_AGAIN}
              </button>
            ) : null
          }
        >
          <p>{read ? REQUEST.SESSION_READ_BODY : REQUEST.SESSION_BODY}</p>
        </RequestAlert>
      );
    case "not_found":
    case "forbidden":
      return (
        <RequestAlert id={id} headingRef={headingRef} heading={REQUEST.NOT_AVAILABLE_HEADING}>
          <p>{REQUEST.NOT_AVAILABLE_BODY}</p>
        </RequestAlert>
      );
    case "invalid":
      return (
        <RequestAlert id={id} headingRef={headingRef} heading={REQUEST.INVALID_HEADING}>
          <p>{REQUEST.INVALID_BODY}</p>
        </RequestAlert>
      );
    case "conflict": {
      const message = conflictMessage?.(outcome.code) ?? null;
      if (message !== null) {
        return (
          <RequestAlert id={id} headingRef={headingRef} heading={REQUEST.NOT_SAVED_HEADING}>
            <p>{message}</p>
          </RequestAlert>
        );
      }
      return (
        <RequestAlert id={id} headingRef={headingRef} heading={REQUEST.DEFECT_HEADING}>
          <p>{REQUEST.defectBody(outcome.code)}</p>
        </RequestAlert>
      );
    }
    case "defect":
      return (
        <RequestAlert id={id} headingRef={headingRef} heading={REQUEST.DEFECT_HEADING}>
          <p>{REQUEST.defectBody(outcome.code)}</p>
        </RequestAlert>
      );
  }
}
