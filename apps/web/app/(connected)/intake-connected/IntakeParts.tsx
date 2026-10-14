"use client";

import { useRef, type ReactNode, type Ref, type RefObject } from "react";
import { Check, LockSimple, LockSimpleOpen } from "@phosphor-icons/react/dist/ssr";
import { ConflictStamp } from "@/app/components/intake/ConflictStamp";
import { C } from "@/lib/connected/copy";
import {
  CONNECTED_STEPS,
  choiceCopy,
  gateCopy,
  REQUESTER_STATUS,
  STAMP_STAGE,
  type LawyerMatter,
  type RequesterMatter,
  type ResultChoice,
} from "@/lib/connected/matter";
import type { Outcome } from "@/lib/connected/request";
import { MOTION_OK_QUERY, duration, ease, gsap, useGSAP } from "@/lib/motion";
import { RequestAlert } from "../_components/RequestAlert";
import styles from "../../workbench/intake/intake.module.css";
import local from "../connected.module.css";

export function describedBy(...ids: (string | null | undefined | false)[]) {
  const list = ids.filter(Boolean);
  return list.length ? list.join(" ") : undefined;
}

/** Progress from the server's projection; "Submitted" reads "Opened" in connected mode. */
export function Progress({ index }: { index: number }) {
  return (
    <nav aria-label="Matter progress" className={styles.progressNav}>
      <ol className={styles.progress}>
        {CONNECTED_STEPS.map((step, position) => (
          <li
            key={step}
            className={styles.progressStep}
            data-state={position < index ? "done" : position === index ? "current" : "todo"}
            aria-current={position === index ? "step" : undefined}
          >
            {position < index ? (
              <Check className={styles.stepIcon} weight="bold" aria-hidden="true" focusable="false" />
            ) : null}
            <span className="visually-hidden">
              {position < index ? "Done: " : position === index ? "Current: " : "Not started: "}
            </span>
            {step}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/**
 * Blocking problems for a matter request (C-05/C-07, C-30 to C-32, C-61, C-63), inside the
 * panel that owns the action. The heading takes focus.
 */
export function MatterAlert({
  outcome,
  context,
  headingRef,
  onRetry,
  onReauthenticate,
}: {
  outcome: Outcome | null;
  context: "create" | "change";
  headingRef: Ref<HTMLHeadingElement>;
  onRetry: () => void;
  onReauthenticate: () => void;
}) {
  if (!outcome) return null;
  const primary = (label: string, onClick: () => void) => (
    <button type="button" className={styles.buttonPrimary} onClick={onClick}>
      {label}
    </button>
  );
  switch (outcome.kind) {
    case "unconfirmed":
      return (
        <RequestAlert tone="unknown" headingRef={headingRef} heading={C.C30_HEADING} actions={primary(C.RETRY, onRetry)}>
          <p>{context === "create" ? C.C31_BODY : C.C32_BODY}</p>
        </RequestAlert>
      );
    case "unavailable":
      return (
        <RequestAlert tone="unknown" headingRef={headingRef} heading={C.C61_HEADING} actions={primary(C.TRY_AGAIN, onRetry)}>
          <p>{C.C61_BODY}</p>
        </RequestAlert>
      );
    case "session":
      return (
        <RequestAlert
          tone="unknown"
          headingRef={headingRef}
          heading={C.C05_HEADING}
          actions={primary(C.C06_BUTTON, onReauthenticate)}
        >
          <p>{C.C07_BODY}</p>
        </RequestAlert>
      );
    case "defect":
      return (
        <RequestAlert headingRef={headingRef} heading={C.C63_HEADING}>
          <p>{C.c63Body(outcome.code)}</p>
        </RequestAlert>
      );
    default:
      return null;
  }
}

/** A failed read (C-60) or an expired session while reading (C-05, C-06). */
export function ReadAlert({
  outcome,
  headingRef,
  onRetry,
  onReauthenticate,
}: {
  outcome: Outcome;
  headingRef: Ref<HTMLHeadingElement>;
  onRetry: () => void;
  onReauthenticate: () => void;
}) {
  if (outcome.kind === "session") {
    return (
      <div id="read-problem">
        <RequestAlert
          headingRef={headingRef}
          heading={C.C05_HEADING}
          actions={
            <button type="button" className={styles.buttonPrimary} onClick={onReauthenticate}>
              {C.C06_BUTTON}
            </button>
          }
        >
          <p>{C.C06_BODY}</p>
        </RequestAlert>
      </div>
    );
  }
  return (
    <div id="read-problem">
      <RequestAlert
        headingRef={headingRef}
        heading={C.C60_HEADING}
        actions={
          <button type="button" className={styles.buttonPrimary} onClick={onRetry}>
            {C.TRY_AGAIN}
          </button>
        }
      >
        <p>{C.C60_BODY}</p>
      </RequestAlert>
    </div>
  );
}

/** One answer for every reason a matter cannot be shown (C-50, C-51). */
export function MatterUnavailable({ headingRef }: { headingRef: Ref<HTMLHeadingElement> }) {
  return (
    <section className={styles.requester} aria-labelledby="unavailable-heading">
      <h2 id="unavailable-heading" ref={headingRef} tabIndex={-1} className={styles.panelHeading}>
        {C.C50_HEADING}
      </h2>
      <p>{C.C51_BODY}</p>
      <p>
        <a href="/workbench/intake">{C.C51_LINK}</a>
      </p>
    </section>
  );
}

/** Static blocks shaped like the summary and conflict panels. No shimmer. */
export function MatterSkeleton() {
  return (
    <div className={styles.matterGrid} aria-busy="true">
      <div className={local.skeleton}>
        <span />
        <span />
        <span />
      </div>
      <div className={local.skeleton}>
        <span />
        <span />
        <span />
      </div>
      <p className="visually-hidden" role="status">
        Loading matter.
      </p>
    </div>
  );
}

/** Requester projection: reference and status only (section 7). */
export function RequesterStatus({
  matter,
  headingRef,
  onRefresh,
  paused,
}: {
  matter: RequesterMatter;
  headingRef: Ref<HTMLHeadingElement>;
  onRefresh: () => void;
  paused: boolean;
}) {
  const { label, note } = REQUESTER_STATUS[matter.status];
  return (
    <section className={styles.requester} aria-labelledby="requester-heading">
      <h2 id="requester-heading" ref={headingRef} tabIndex={-1} className={styles.panelHeading}>
        Request status
      </h2>
      <dl className={styles.facts}>
        <div>
          <dt>Reference</dt>
          <dd className={local.reference}>{matter.matterId}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={styles.requesterStage}>{label}</span>
            <span className={styles.requesterNote}>{note}</span>
          </dd>
        </div>
      </dl>
      <div>
        <button
          type="button"
          className={styles.buttonQuiet}
          onClick={onRefresh}
          aria-disabled={paused || undefined}
          aria-describedby={paused ? "read-problem" : undefined}
        >
          Refresh status
        </button>
      </div>
      <p className={styles.requesterFoot}>{C.C82}</p>
    </section>
  );
}

/** The confirmed stamp, with the 200 ms settle only after a confirmed change. */
export function ConfirmedStamp({ matter, settleKey }: { matter: LawyerMatter; settleKey: number }) {
  const scope = useRef<HTMLSpanElement>(null);
  useGSAP(
    () => {
      if (settleKey === 0) return;
      const mm = gsap.matchMedia();
      mm.add(MOTION_OK_QUERY, () => {
        gsap.from("[data-animate-result]", { autoAlpha: 0, y: 4, duration: duration.base, ease: ease.out });
      });
      return () => mm.revert();
    },
    { scope, dependencies: [settleKey], revertOnUpdate: true },
  );
  return (
    <span ref={scope}>
      <span data-animate-result="">
        <ConflictStamp
          stage={STAMP_STAGE[matter.conflictStatus]}
          detail={C.c26(matter.revision)}
          detailPrefix=", "
        />
      </span>
    </span>
  );
}

export function Gate({ matter }: { matter: LawyerMatter }) {
  const ready = matter.status === "ready";
  return (
    <p className={styles.gate} data-ready={ready ? "" : undefined} id="review-gate">
      {ready ? (
        <LockSimpleOpen className={styles.inlineIcon} weight="bold" aria-hidden="true" focusable="false" />
      ) : (
        <LockSimple className={styles.inlineIcon} weight="bold" aria-hidden="true" focusable="false" />
      )}
      <span>{gateCopy(matter)}</span>
    </p>
  );
}

export function ResultChoices({
  idPrefix,
  status,
  choices,
  value,
  onChange,
  error,
  locked,
  firstRef,
}: {
  idPrefix: string;
  status: LawyerMatter["conflictStatus"];
  choices: ResultChoice[];
  value: ResultChoice | null;
  onChange: (choice: ResultChoice) => void;
  error: string | null;
  locked: boolean;
  firstRef: Ref<HTMLInputElement>;
}) {
  const errorId = `${idPrefix}-choice-error`;
  return (
    <fieldset className={styles.choices} aria-describedby={error ? errorId : undefined}>
      <legend className={styles.subHeading}>Record the result</legend>
      {choices.map((choice, index) => {
        const id = `${idPrefix}-${choice}`;
        const { label, help } = choiceCopy(choice, status);
        return (
          <div key={choice} className={styles.choice}>
            <input
              ref={index === 0 ? firstRef : undefined}
              id={id}
              type="radio"
              name={`${idPrefix}-result`}
              value={choice}
              checked={value === choice}
              onChange={() => {
                if (!locked) onChange(choice);
              }}
              aria-disabled={locked || undefined}
              aria-describedby={`${id}-help`}
              className={styles.radio}
            />
            <label htmlFor={id} className={styles.choiceLabel}>
              {label}
            </label>
            <p id={`${id}-help`} className={styles.choiceHelp}>
              {help}
            </p>
          </div>
        );
      })}
      {error ? (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}

export function FieldShell({
  id,
  label,
  hint,
  error,
  counter,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string | null;
  counter?: string | null;
  children: ReactNode;
}) {
  return (
    <div className={styles.field} data-invalid={error ? "" : undefined}>
      <label htmlFor={id} className={styles.label}>
        {label.replace(" (required)", "")}
        <span className={styles.required}> (required)</span>
      </label>
      {hint ? (
        <p id={`${id}-hint`} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {children}
      {counter ? (
        <p id={`${id}-counter`} className={styles.hint}>
          {counter}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} className={styles.error}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** In-app confirmation before leaving with unsaved input or an unconfirmed request (C-70). */
export function LeaveConfirm({
  pending,
  stayRef,
  onStay,
  onLeave,
}: {
  pending: boolean;
  stayRef: RefObject<HTMLButtonElement | null>;
  onStay: () => void;
  onLeave: () => void;
}) {
  return (
    <div role="alertdialog" aria-labelledby="leave-heading" aria-describedby="leave-body" className={local.alert} data-tone="unknown">
      <h3 id="leave-heading" className={local.alertHeading}>
        {C.C70_HEADING}
      </h3>
      <p id="leave-body">{pending ? C.C70_BODY_PENDING : C.C70_BODY}</p>
      <div className={local.inlineActions}>
        <button ref={stayRef} type="button" className={styles.buttonPrimary} onClick={onStay}>
          {C.C70_STAY}
        </button>
        <button type="button" className={styles.buttonQuiet} onClick={onLeave}>
          {C.C70_LEAVE}
        </button>
      </div>
    </div>
  );
}
