"use client";

import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import {
  ArrowCounterClockwise,
  Check,
  FileText,
  LockSimple,
  LockSimpleOpen,
} from "@phosphor-icons/react/dist/ssr";
import { ConflictStamp } from "@/app/components/intake/ConflictStamp";
import {
  CONTRACT_TYPES,
  MATTER_REFERENCE,
  PEOPLE,
  PROGRESS_STEPS,
  RECORDED_AT,
  REGISTER_HITS,
  REQUESTER_STAGE,
  SAMPLE_DETAILS,
  STAGE_LABEL,
  WAIVER_REASON_MAX,
  announce,
  isReadyForReview,
  progressIndex,
  validateDetails,
  validateWaiverReason,
  type ConflictResult,
  type IntakeDetails,
  type IntakeErrors,
  type IntakeStage,
  type Viewer,
} from "@/lib/intake";
import { MOTION_OK_QUERY, duration, ease, gsap, useGSAP } from "@/lib/motion";
import styles from "./intake.module.css";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-24" to "24 Oct 2026" without time-zone drift. */
function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

type Recorded = {
  by: string;
  at: string;
  reason?: string;
};

/**
 * Synthetic, in-memory walkthrough of intake (US-1 web slice) and the conflict
 * check (US-3), with the requester's status view (US-4). All state is local;
 * nothing is uploaded, stored or sent. There is no <form> element on purpose.
 */
export function IntakePrototype() {
  const [viewer, setViewer] = useState<Viewer>("lawyer");
  const [stage, setStage] = useState<IntakeStage>("draft");
  const [details, setDetails] = useState<IntakeDetails>(SAMPLE_DETAILS);
  const [errors, setErrors] = useState<IntakeErrors>({});
  const [recorded, setRecorded] = useState<Recorded | null>(null);
  const [conflictRecordedBy, setConflictRecordedBy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const resultHeadingRef = useRef<HTMLHeadingElement>(null);
  const statusHeadingRef = useRef<HTMLHeadingElement>(null);

  // After a state change, move focus to the region that now explains it.
  // Set before the state update; applied once the new region has rendered.
  const focusNext = useRef<RefObject<HTMLElement | null> | null>(null);
  useEffect(() => {
    focusNext.current?.current?.focus();
    focusNext.current = null;
  }, [stage]);

  function focusAfterRender(target: RefObject<HTMLElement | null>) {
    focusNext.current = target;
  }

  function changeViewer(next: Viewer) {
    setViewer(next);
    setMessage(
      next === "requester"
        ? `Showing the requester view. ${announce(stage, "requester")}`
        : "Showing the lawyer view.",
    );
  }

  function submit() {
    const found = validateDetails(details);
    setErrors(found);
    const firstInvalid = (["counterparty", "contractType", "deadline"] as const).find(
      (key) => found[key],
    );
    if (firstInvalid) {
      const count = Object.keys(found).length;
      setMessage(`${count} ${count === 1 ? "field needs" : "fields need"} attention.`);
      document.getElementById(`intake-${firstInvalid}`)?.focus();
      return;
    }
    setStage("pending");
    setMessage(announce("pending", viewer));
    focusAfterRender(viewer === "requester" ? statusHeadingRef : resultHeadingRef);
  }

  function record(result: ConflictResult, reason?: string) {
    const next: IntakeStage =
      result === "clear" ? "cleared" : result === "conflict" ? "conflict" : result;
    if (result === "conflict") {
      setConflictRecordedBy(PEOPLE.lawyer.name);
      setRecorded(null);
    } else {
      setRecorded({ by: PEOPLE.lawyer.name, at: RECORDED_AT, reason });
    }
    setStage(next);
    setMessage(announce(next, viewer));
    focusAfterRender(resultHeadingRef);
  }

  function reset() {
    setStage("draft");
    setDetails(SAMPLE_DETAILS);
    setErrors({});
    setRecorded(null);
    setConflictRecordedBy(null);
    setMessage(announce("draft", viewer));
    // The result region unmounts on reset; return to the first editable field.
    requestAnimationFrame(() => document.getElementById("intake-counterparty")?.focus());
  }

  return (
    <>
      <p className={styles.hint}>
        The view switch demonstrates visibility only; it is not a sign-in or an access control.
      </p>
      <div className={styles.toolbar}>
        <fieldset className={styles.viewToggle}>
          <legend className={styles.viewLegend}>View as</legend>
          <div className={styles.segmented}>
            <ViewOption
              value="lawyer"
              current={viewer}
              onSelect={changeViewer}
              label="Lawyer"
              person={PEOPLE.lawyer.name}
            />
            <ViewOption
              value="requester"
              current={viewer}
              onSelect={changeViewer}
              label="Requester"
              person={PEOPLE.requester.name}
            />
          </div>
        </fieldset>

        {stage !== "draft" ? (
          <button type="button" className={styles.buttonQuiet} onClick={reset}>
            <ArrowCounterClockwise
              className={styles.buttonIcon}
              weight="bold"
              aria-hidden="true"
              focusable="false"
            />
            Start again
          </button>
        ) : null}
      </div>

      <p className="visually-hidden" role="status" aria-live="polite">
        {message}
      </p>

      {viewer === "lawyer" ? <Progress stage={stage} /> : null}

      {stage === "draft" ? (
        <IntakeForm
          viewer={viewer}
          details={details}
          errors={errors}
          onChange={(next) => setDetails(next)}
          onSubmit={submit}
        />
      ) : viewer === "requester" ? (
        <RequesterStatus stage={stage} details={details} headingRef={statusHeadingRef} />
      ) : (
        <div className={styles.matterGrid}>
          <MatterSummary details={details} />
          <ConflictPanel
            stage={stage}
            recorded={recorded}
            conflictRecordedBy={conflictRecordedBy}
            onRecord={record}
            headingRef={resultHeadingRef}
          />
        </div>
      )}
    </>
  );
}

function ViewOption({
  value,
  current,
  onSelect,
  label,
  person,
}: {
  value: Viewer;
  current: Viewer;
  onSelect: (value: Viewer) => void;
  label: string;
  person: string;
}) {
  const id = `viewer-${value}`;
  return (
    <div className={styles.segment}>
      <input
        id={id}
        type="radio"
        name="viewer"
        value={value}
        checked={current === value}
        onChange={() => onSelect(value)}
        className={styles.segmentInput}
      />
      <label htmlFor={id} className={styles.segmentLabel}>
        {label}
        <span className={styles.segmentPerson}>{person}</span>
      </label>
    </div>
  );
}

function Progress({ stage }: { stage: IntakeStage }) {
  const current = progressIndex(stage);
  return (
    <nav aria-label="Matter progress" className={styles.progressNav}>
      <ol className={styles.progress}>
        {PROGRESS_STEPS.map((step, index) => (
          <li
            key={step}
            className={styles.progressStep}
            data-state={index < current ? "done" : index === current ? "current" : "todo"}
            aria-current={index === current ? "step" : undefined}
          >
            {index < current ? (
              <Check
                className={styles.stepIcon}
                weight="bold"
                aria-hidden="true"
                focusable="false"
              />
            ) : null}
            <span className="visually-hidden">
              {index < current ? "Done: " : index === current ? "Current: " : "Not started: "}
            </span>
            {step}
          </li>
        ))}
      </ol>
    </nav>
  );
}

function Field({
  id,
  label,
  required,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  required?: boolean;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.field} data-invalid={error ? "" : undefined}>
      <label htmlFor={id} className={styles.label}>
        {label}
        {required ? <span className={styles.required}> (required)</span> : null}
      </label>
      {hint ? (
        <p id={`${id}-hint`} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {children}
      {error ? (
        <p id={`${id}-error`} className={styles.error}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function describedBy(id: string, hint: boolean, error?: string): string | undefined {
  const ids = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
}

function IntakeForm({
  viewer,
  details,
  errors,
  onChange,
  onSubmit,
}: {
  viewer: Viewer;
  details: IntakeDetails;
  errors: IntakeErrors;
  onChange: (next: IntakeDetails) => void;
  onSubmit: () => void;
}) {
  const set = (key: keyof IntakeDetails) => (value: string) =>
    onChange({ ...details, [key]: value });

  return (
    <div className={styles.draftGrid}>
      <section className={styles.panel} aria-labelledby="intake-heading">
        <h2 id="intake-heading" className={styles.panelHeading}>
          New matter
        </h2>
        <p className={styles.panelLede}>
          {viewer === "requester"
            ? "Tell legal what you need reviewed. Sample answers are filled in."
            : "Open a matter for a requester. Sample answers are filled in."}
        </p>

        <div className={styles.fields}>
          <Field
            id="intake-counterparty"
            label="Counterparty"
            required
            hint="The other party to the contract, as named in it."
            error={errors.counterparty}
          >
            <input
              id="intake-counterparty"
              type="text"
              autoComplete="off"
              className={styles.input}
              value={details.counterparty}
              onChange={(event) => set("counterparty")(event.target.value)}
              aria-invalid={errors.counterparty ? true : undefined}
              aria-describedby={describedBy("intake-counterparty", true, errors.counterparty)}
              required
            />
          </Field>

          <Field
            id="intake-contractType"
            label="Contract type"
            required
            error={errors.contractType}
          >
            <select
              id="intake-contractType"
              autoComplete="off"
              className={styles.input}
              value={details.contractType}
              onChange={(event) => set("contractType")(event.target.value)}
              aria-invalid={errors.contractType ? true : undefined}
              aria-describedby={describedBy("intake-contractType", false, errors.contractType)}
              required
            >
              <option value="">Choose a type</option>
              {CONTRACT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </Field>

          <div className={styles.fieldPair}>
            <Field
              id="intake-value"
              label="Contract value"
              hint="Approximate, with currency. Optional."
            >
              <input
                id="intake-value"
                type="text"
                autoComplete="off"
                inputMode="text"
                className={styles.input}
                value={details.value}
                onChange={(event) => set("value")(event.target.value)}
                aria-describedby="intake-value-hint"
              />
            </Field>

            <Field
              id="intake-deadline"
              label="Needed by"
              required
              hint="The date you need legal's view."
              error={errors.deadline}
            >
              <input
                id="intake-deadline"
                type="date"
                autoComplete="off"
                className={styles.input}
                value={details.deadline}
                onChange={(event) => set("deadline")(event.target.value)}
                aria-invalid={errors.deadline ? true : undefined}
                aria-describedby={describedBy("intake-deadline", true, errors.deadline)}
                required
              />
            </Field>
          </div>

          <div className={styles.field}>
            <p id="intake-document-label" className={styles.label}>
              Document
            </p>
            <p className={styles.documentSlot} aria-labelledby="intake-document-label">
              <FileText
                className={styles.documentIcon}
                weight="regular"
                aria-hidden="true"
                focusable="false"
              />
              <span>
                <span className={styles.documentName}>{details.documentName}</span>
                <span className={styles.hint}>
                  Placeholder. Uploads are switched off in this prototype.
                </span>
              </span>
            </p>
          </div>
        </div>

        <div className={styles.formActions}>
          <button type="button" className={styles.buttonPrimary} onClick={onSubmit}>
            Submit for conflict check
          </button>
        </div>
      </section>

      <aside className={styles.nextSteps} aria-labelledby="next-heading">
        <h2 id="next-heading" className={styles.asideHeading}>
          What happens next
        </h2>
        <ol className={styles.nextList}>
          <li>A lawyer on the matter checks the firm&rsquo;s party register for conflicts.</li>
          <li>They record the result under their own name: clear, conflict found, or waived with a reason.</li>
          <li>Review starts only once a result is recorded. The requester sees status, never the analysis.</li>
        </ol>
      </aside>
    </div>
  );
}

function MatterSummary({ details }: { details: IntakeDetails }) {
  return (
    <section className={styles.summary} aria-labelledby="summary-heading">
      <h2 id="summary-heading" className={styles.panelHeading}>
        {MATTER_REFERENCE}
      </h2>
      <dl className={styles.facts}>
        <div>
          <dt>Counterparty</dt>
          <dd>{details.counterparty}</dd>
        </div>
        <div>
          <dt>Contract</dt>
          <dd>{details.contractType}</dd>
        </div>
        <div>
          <dt>Value</dt>
          <dd>{details.value.trim() || "Not given"}</dd>
        </div>
        <div>
          <dt>Needed by</dt>
          <dd>{formatDate(details.deadline)}</dd>
        </div>
        <div>
          <dt>Document</dt>
          <dd>{details.documentName}</dd>
        </div>
        <div>
          <dt>Requester</dt>
          <dd>{PEOPLE.requester.name}</dd>
        </div>
        <div>
          <dt>Lawyer</dt>
          <dd>{PEOPLE.lawyer.name}</dd>
        </div>
      </dl>
    </section>
  );
}

function ConflictPanel({
  stage,
  recorded,
  conflictRecordedBy,
  onRecord,
  headingRef,
}: {
  stage: Exclude<IntakeStage, "draft">;
  recorded: Recorded | null;
  conflictRecordedBy: string | null;
  onRecord: (result: ConflictResult, reason?: string) => void;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const scope = useRef<HTMLElement>(null);
  const ready = isReadyForReview(stage);

  // One motion moment: the stamp settles when the result changes. <= 200 ms,
  // only under no-preference; the stamp is fully visible by default.
  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MOTION_OK_QUERY, () => {
        gsap.from("[data-animate-result]", {
          autoAlpha: 0,
          y: 4,
          duration: duration.base,
          ease: ease.out,
        });
      });
      return () => mm.revert();
    },
    { scope, dependencies: [stage], revertOnUpdate: true },
  );

  return (
    <section
      ref={scope}
      className={styles.panel}
      aria-labelledby="conflict-heading"
      data-privileged=""
    >
      <div className={styles.panelHead}>
        <h2 id="conflict-heading" ref={headingRef} tabIndex={-1} className={styles.panelHeading}>
          Conflict check
        </h2>
        <span data-animate-result="">
          <ConflictStamp
            stage={stage}
            detail={
              recorded
                ? `${recorded.by}, ${recorded.at}`
                : stage === "conflict" && conflictRecordedBy
                  ? `${conflictRecordedBy}, ${RECORDED_AT}`
                  : undefined
            }
          />
        </span>
      </div>
      <p className={styles.privileged}>
        <LockSimple
          className={styles.inlineIcon}
          weight="bold"
          aria-hidden="true"
          focusable="false"
        />
        Privileged. The requester never sees this panel.
      </p>

      <h3 className={styles.subHeading}>Preset synthetic matches</h3>
      <p className={styles.hint}>These fixed examples are independent of your edits. No register search runs.</p>
      <ul className={styles.hits} aria-label="Possible matches in the party register">
        {REGISTER_HITS.map((hit) => (
          <li key={hit.id} className={styles.hit}>
            <p className={styles.hitParty}>{hit.party}</p>
            <p className={styles.hitRelation}>{hit.relation}</p>
            <p className={styles.hitDetail}>{hit.detail}</p>
          </li>
        ))}
      </ul>

      {stage === "pending" || stage === "conflict" ? (
        <RecordResult key={stage} stage={stage} onRecord={onRecord} />
      ) : (
        <AuditRecord stage={stage} recorded={recorded} conflictRecordedBy={conflictRecordedBy} />
      )}

      <p className={styles.gate} data-ready={ready ? "" : undefined} id="review-gate">
        {ready ? (
          <LockSimpleOpen
            className={styles.inlineIcon}
            weight="bold"
            aria-hidden="true"
            focusable="false"
          />
        ) : (
          <LockSimple
            className={styles.inlineIcon}
            weight="bold"
            aria-hidden="true"
            focusable="false"
          />
        )}
        <span>
          {ready
            ? "Ready for review. A result and a named clearer are on record."
            : stage === "declined"
              ? "Closed. The matter was declined, so no review will start."
              : "Review is blocked until a result is recorded under a lawyer's name."}
        </span>
      </p>
    </section>
  );
}

function RecordResult({
  stage,
  onRecord,
}: {
  stage: "pending" | "conflict";
  onRecord: (result: ConflictResult, reason?: string) => void;
}) {
  const uid = useId();
  const [choice, setChoice] = useState<ConflictResult | null>(null);
  const [reason, setReason] = useState("");
  const [choiceError, setChoiceError] = useState<string | null>(null);
  const [reasonError, setReasonError] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const firstOptionRef = useRef<HTMLInputElement>(null);

  const options: { value: ConflictResult; label: string; help: string }[] =
    stage === "pending"
      ? [
          { value: "clear", label: "Clear", help: "No conflict. Work can start." },
          {
            value: "conflict",
            label: "Conflict found",
            help: "Blocks review until it is waived or the matter is declined.",
          },
          {
            value: "waived",
            label: "Conflict waived",
            help: "You accept the conflict and record why. Needs a reason.",
          },
        ]
      : [
          {
            value: "waived",
            label: "Waive the conflict",
            help: "You accept the conflict and record why. Needs a reason.",
          },
          {
            value: "declined",
            label: "Decline the matter",
            help: "The firm will not act. The requester sees only that it is closed.",
          },
        ];

  function submit() {
    if (!choice) {
      setChoiceError("Choose a result to record.");
      firstOptionRef.current?.focus();
      return;
    }
    if (choice === "waived") {
      const problem = validateWaiverReason(reason);
      if (problem) {
        setReasonError(problem);
        reasonRef.current?.focus();
        return;
      }
      onRecord("waived", reason.trim());
      return;
    }
    onRecord(choice);
  }

  const reasonId = `${uid}-reason`;
  const choiceErrorId = `${uid}-choice-error`;

  return (
    <div className={styles.record}>
      <fieldset
        className={styles.choices}
        aria-describedby={choiceError ? choiceErrorId : undefined}
        aria-invalid={choiceError ? true : undefined}
      >
        <legend className={styles.subHeading}>Record the result</legend>
        {options.map((option, index) => {
          const id = `${uid}-${option.value}`;
          return (
            <div key={option.value} className={styles.choice}>
              <input
                ref={index === 0 ? firstOptionRef : undefined}
                id={id}
                type="radio"
                name={`${uid}-result`}
                value={option.value}
                checked={choice === option.value}
                onChange={() => {
                  setChoice(option.value);
                  setChoiceError(null);
                }}
                aria-describedby={`${id}-help`}
                className={styles.radio}
              />
              <label htmlFor={id} className={styles.choiceLabel}>
                {option.label}
              </label>
              <p id={`${id}-help`} className={styles.choiceHelp}>
                {option.help}
              </p>
            </div>
          );
        })}
        {choiceError ? (
          <p id={choiceErrorId} className={styles.error}>
            {choiceError}
          </p>
        ) : null}
      </fieldset>

      {choice === "waived" ? (
        <div className={styles.field} data-invalid={reasonError ? "" : undefined}>
          <label htmlFor={reasonId} className={styles.label}>
            Reason for waiver<span className={styles.required}> (required)</span>
          </label>
          <p id={`${reasonId}-hint`} className={styles.hint}>
            Explain why, up to {WAIVER_REASON_MAX} characters. This walkthrough shows the
            reason in a simulated audit record for sign-off; it does not save it.
          </p>
          <textarea
            id={reasonId}
            autoComplete="off"
            ref={reasonRef}
            rows={3}
            className={styles.textarea}
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
              if (reasonError) setReasonError(null);
            }}
            aria-invalid={reasonError ? true : undefined}
            aria-describedby={[`${reasonId}-hint`, reasonError ? `${reasonId}-error` : null]
              .filter(Boolean)
              .join(" ")}
            required
          />
          {reasonError ? (
            <p id={`${reasonId}-error`} className={styles.error}>
              {reasonError}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className={styles.recordActions}>
        <button type="button" className={styles.buttonPrimary} onClick={submit}>
          Record result
        </button>
        <p className={styles.recordedAs}>
          Recorded as {PEOPLE.lawyer.name}, {PEOPLE.lawyer.role.toLowerCase()}.
        </p>
      </div>
    </div>
  );
}

function AuditRecord({
  stage,
  recorded,
  conflictRecordedBy,
}: {
  stage: "cleared" | "waived" | "declined";
  recorded: Recorded | null;
  conflictRecordedBy: string | null;
}) {
  if (!recorded) return null;
  return (
    <section className={styles.audit} aria-labelledby="audit-heading">
      <h3 id="audit-heading" className={styles.subHeading}>
        Simulated record
      </h3>
      <dl className={styles.facts}>
        <div>
          <dt>Result</dt>
          <dd>{STAGE_LABEL[stage]}</dd>
        </div>
        {conflictRecordedBy ? (
          <div>
            <dt>Conflict found by</dt>
            <dd>{conflictRecordedBy}</dd>
          </div>
        ) : null}
        <div>
          <dt>{stage === "waived" ? "Waived by" : "Recorded by"}</dt>
          <dd>
            {recorded.by}, {PEOPLE.lawyer.role.toLowerCase()}
          </dd>
        </div>
        <div>
          <dt>When</dt>
          <dd>{recorded.at}</dd>
        </div>
        {recorded.reason ? (
          <div>
            <dt>Reason</dt>
            <dd className={styles.reason}>{recorded.reason}</dd>
          </div>
        ) : null}
      </dl>
      {stage === "waived" ? (
        <p className={styles.signoffNote}>
          In a completed workflow, this waiver would be listed for {PEOPLE.partner.name} at sign-off.
          {conflictRecordedBy === recorded.by
            ? " The same lawyer found and waived the conflict, which sign-off will also show."
            : null}
        </p>
      ) : null}
    </section>
  );
}

function RequesterStatus({
  stage,
  details,
  headingRef,
}: {
  stage: Exclude<IntakeStage, "draft">;
  details: IntakeDetails;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const { label, note } = REQUESTER_STAGE[stage];
  return (
    <section className={styles.requester} aria-labelledby="requester-heading">
      <h2
        id="requester-heading"
        ref={headingRef}
        tabIndex={-1}
        className={styles.panelHeading}
      >
        Your request {MATTER_REFERENCE}
      </h2>
      <dl className={styles.facts}>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={styles.requesterStage}>{label}</span>
            <span className={styles.requesterNote}>{note}</span>
          </dd>
        </div>
        <div>
          <dt>Lawyer</dt>
          <dd>{stage === "declined" ? "Legal team" : PEOPLE.lawyer.name}</dd>
        </div>
        <div>
          <dt>Target date</dt>
          <dd>{stage === "declined" ? "None" : formatDate(details.deadline)}</dd>
        </div>
      </dl>
      <p className={styles.requesterFoot}>
        This page shows status only. Your lawyer shares advice with you directly.
      </p>
    </section>
  );
}
