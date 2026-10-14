"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowCounterClockwise, LockSimple } from "@phosphor-icons/react/dist/ssr";
import { onIdentityChange } from "@/lib/connected/auth/client";
import { C, TITLES } from "@/lib/connected/copy";
import { useFrozenMutation, useReauthenticate } from "@/lib/connected/hooks";
import {
  checkReason,
  checkTitle,
  choicesCollapsed,
  choicesFor,
  clockTime,
  confirmedAnnouncement,
  COUNTER_WINDOW,
  intakePath,
  matterApiPath,
  parseMatter,
  parseReceipt,
  progressIndexOf,
  STAMP_LABEL,
  TITLE_MAX,
  type LawyerMatter,
  type Matter,
  type RequesterMatter,
  type ResultChoice,
} from "@/lib/connected/matter";
import { apiRead, type Outcome } from "@/lib/connected/request";
import { codePoints } from "@/lib/connected/validation";
import { RequestAlert } from "../_components/RequestAlert";
import { useFocusAfterRender } from "../_components/LiveStatus";
import {
  ConfirmedStamp,
  describedBy,
  FieldShell,
  Gate,
  LeaveConfirm,
  MatterAlert,
  MatterSkeleton,
  MatterUnavailable,
  Progress,
  ReadAlert,
  RequesterStatus,
  ResultChoices,
} from "./IntakeParts";
import styles from "../../workbench/intake/intake.module.css";
import local from "../connected.module.css";

type Screen =
  | { kind: "new" }
  | { kind: "loading"; matterId: string }
  | { kind: "lawyer"; matter: LawyerMatter }
  | { kind: "requester"; matter: RequesterMatter }
  | { kind: "not_available" };

type ConflictNotice =
  | { kind: "still" }
  | { kind: "gone"; stampLabel: string; reason: string | null }
  | { kind: "key_reused" }
  /** A request the client should never have sent (C-63). */
  | { kind: "defect"; code: string };

/** Background refresh happens on focus once the page is at least this old (section 6.5). */
export const BACKGROUND_REFRESH_MS = 60_000;

const ifMatch = (revision: number) => `"${revision}"`;

/** Outcomes the panel explains with an alert; the rest become field or page states. */
function alertable(outcome: Outcome | null): Outcome | null {
  if (!outcome) return null;
  if (outcome.kind === "conflict") return { kind: "defect", code: outcome.code };
  return outcome.kind === "unconfirmed" ||
    outcome.kind === "unavailable" ||
    outcome.kind === "session" ||
    outcome.kind === "defect"
    ? outcome
    : null;
}

/**
 * Connected intake controller (INTAKE_PERSISTENCE_STATES.md): creates a matter, resumes it,
 * edits its title and records the conflict result through /api/v1/matters. A recorded act
 * is shown only after the server confirms it; unknown outcomes are retried with the same
 * Idempotency-Key, body and If-Match; stale revisions are never overwritten silently.
 * Matter content, reasons and keys live in this component's memory only.
 */
export function ConnectedIntake({ matterId: initialId, subject }: { matterId: string | null; subject: string | null }) {
  const [screen, setScreen] = useState<Screen>(initialId ? { kind: "loading", matterId: initialId } : { kind: "new" });
  const [readProblem, setReadProblem] = useState<Outcome | null>(null);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const focusLater = useFocusAfterRender();
  const leaving = useRef(false);

  // Focus targets (section 8).
  const createTitleRef = useRef<HTMLInputElement>(null);
  const createAlertRef = useRef<HTMLHeadingElement>(null);
  const formErrorRef = useRef<HTMLParagraphElement>(null);
  const referenceRef = useRef<HTMLHeadingElement>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const editInputRef = useRef<HTMLInputElement>(null);
  const summaryAlertRef = useRef<HTMLHeadingElement>(null);
  const staleHeadingRef = useRef<HTMLHeadingElement>(null);
  const conflictHeadingRef = useRef<HTMLHeadingElement>(null);
  const firstChoiceRef = useRef<HTMLInputElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const conflictAlertRef = useRef<HTMLHeadingElement>(null);
  const noticeHeadingRef = useRef<HTMLHeadingElement>(null);
  const unavailableRef = useRef<HTMLHeadingElement>(null);
  const requesterRef = useRef<HTMLHeadingElement>(null);
  const readAlertRef = useRef<HTMLHeadingElement>(null);
  const stayRef = useRef<HTMLButtonElement>(null);
  const changeButtonRef = useRef<HTMLButtonElement>(null);

  // New matter
  const [title, setTitle] = useState("");
  const [titleError, setTitleError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const createM = useFrozenMutation();

  // Title edit
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [draftError, setDraftError] = useState<string | null>(null);
  const [stale, setStale] = useState<LawyerMatter | null>(null);
  const [savedRevision, setSavedRevision] = useState<number | null>(null);
  const [titleKeyReused, setTitleKeyReused] = useState(false);
  const titleM = useFrozenMutation();

  // Conflict result
  const [choice, setChoice] = useState<ResultChoice | null>(null);
  const [choiceError, setChoiceError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [notice, setNotice] = useState<ConflictNotice | null>(null);
  const [waiverNote, setWaiverNote] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);
  const [settleKey, setSettleKey] = useState(0);
  const conflictM = useFrozenMutation();

  // Background change and leaving
  const [backgroundLatest, setBackgroundLatest] = useState<LawyerMatter | null>(null);
  const [confirmLeave, setConfirmLeave] = useState(false);

  const lawyer = screen.kind === "lawyer" ? screen.matter : null;
  const shown: Matter | null = screen.kind === "lawyer" || screen.kind === "requester" ? screen.matter : null;
  const paused = readProblem !== null;
  const anyLocked = createM.locked || titleM.locked || conflictM.locked;
  const dirty =
    anyLocked ||
    (screen.kind === "new" && title.trim() !== "") ||
    (editing && lawyer !== null && draft !== lawyer.title) ||
    reason.trim() !== "";

  const announce = (text: string) => setAnnouncement(text);

  /** Clears every matter field, revision, key and input from memory (404, identity change). */
  function purge() {
    createM.reset();
    titleM.reset();
    conflictM.reset();
    setTitle("");
    setEditing(false);
    setDraft("");
    setStale(null);
    setSavedRevision(null);
    setChoice(null);
    setReason("");
    setNotice(null);
    setWaiverNote(null);
    setChanged(false);
    setBackgroundLatest(null);
    setReadProblem(null);
    setLoadedAt(null);
  }

  function applyLoad(outcome: Outcome, after?: (matter: Matter) => void): Matter | null {
    if (outcome.kind === "ok") {
      const matter = parseMatter(outcome.data);
      if (matter === null) {
        setReadProblem({ kind: "unavailable" });
        focusLater(readAlertRef);
        return null;
      }
      setReadProblem(null);
      setLoadedAt(new Date());
      setBackgroundLatest(null);
      setScreen(matter.kind === "lawyer" ? { kind: "lawyer", matter } : { kind: "requester", matter });
      after?.(matter);
      return matter;
    }
    if (outcome.kind === "not_found" || outcome.kind === "forbidden") {
      purge();
      setScreen({ kind: "not_available" });
      focusLater(unavailableRef);
      return null;
    }
    setReadProblem(outcome);
    focusLater(readAlertRef);
    return null;
  }

  async function load(matterId: string, after?: (matter: Matter) => void) {
    return applyLoad(await apiRead(matterApiPath(matterId)), after);
  }

  // Initial read for a resumed matter.
  const applyLoadRef = useRef(applyLoad);
  useEffect(() => {
    applyLoadRef.current = applyLoad;
  });
  useEffect(() => {
    if (!initialId) return;
    let cancelled = false;
    void apiRead(matterApiPath(initialId)).then((outcome) => {
      if (!cancelled) applyLoadRef.current(outcome);
    });
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  // Document title reflects the state, never the matter title.
  useEffect(() => {
    document.title =
      screen.kind === "new"
        ? TITLES.newMatter
        : screen.kind === "not_available"
          ? TITLES.notAvailable
          : screen.kind === "requester"
            ? TITLES.requester
            : TITLES.matter(screen.kind === "loading" ? screen.matterId : screen.matter.matterId);
  }, [screen]);

  // Leave guard: the browser's own prompt for reloads and closing the tab.
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => {
      if (leaving.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);

  // Another account signed in, or this one signed out elsewhere: purge by reloading.
  useEffect(() => {
    if (subject === null) return;
    return onIdentityChange(subject, () => {
      leaving.current = true;
      window.location.reload();
    });
  }, [subject]);

  // Background change detection on focus (section 6.5).
  const backgroundCheck = useRef<() => void>(() => {});
  useEffect(() => {
    backgroundCheck.current = () => {
      if (!shown || !loadedAt || anyLocked || readProblem) return;
      if (Date.now() - loadedAt.getTime() < BACKGROUND_REFRESH_MS) return;
      const before = shown;
      const editingNow = editing || reason.trim() !== "" || choice !== null;
      void apiRead(matterApiPath(before.matterId)).then((outcome) => {
        if (outcome.kind !== "ok") {
          if (outcome.kind === "not_found") applyLoad(outcome);
          return;
        }
        const latest = parseMatter(outcome.data);
        if (!latest) return;
        if (latest.kind === "lawyer" && before.kind === "lawyer" && latest.revision === before.revision) {
          setLoadedAt(new Date());
          return;
        }
        if (editingNow && latest.kind === "lawyer") {
          setBackgroundLatest(latest);
          return;
        }
        applyLoad(outcome, (matter) => {
          if (matter.kind === "lawyer") {
            announce(C.c43(matter.revision));
            if (before.kind === "lawyer" && matter.conflictStatus !== before.conflictStatus) setChanged(true);
          } else {
            announce(C.c83(matter.status === "ready" ? C.C81_LABEL : C.C80_LABEL));
          }
        });
      });
    };
  });
  useEffect(() => {
    const onFocus = () => backgroundCheck.current();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  // ---- New matter ------------------------------------------------------

  async function settleCreate(outcome: Outcome | null) {
    if (outcome === null) return;
    if (outcome.kind === "ok") {
      const receipt = parseReceipt(outcome.data);
      createM.reset();
      if (receipt === null) {
        setFormError(C.c63Body("invalid_response"));
        focusLater(formErrorRef);
        return;
      }
      setTitle("");
      // Replace, not push: Back must not return to a filled create form.
      window.history.replaceState(null, "", intakePath(receipt.matterId));
      setScreen({ kind: "loading", matterId: receipt.matterId });
      await load(receipt.matterId, () => {
        announce(C.c21(receipt.matterId, receipt.revision));
        focusLater(referenceRef);
      });
      return;
    }
    if (outcome.kind === "forbidden") {
      setFormError(C.C10);
      focusLater(formErrorRef);
      return;
    }
    if (outcome.kind === "invalid") {
      setTitleError(C.C13_HIDDEN);
      focusLater(createTitleRef);
      return;
    }
    focusLater(createAlertRef);
  }

  async function openMatter(event: React.FormEvent) {
    event.preventDefault();
    if (createM.locked) return;
    const checked = checkTitle(title);
    setTitleError(checked.error);
    setFormError(null);
    if (checked.error) {
      focusLater(createTitleRef);
      return;
    }
    if (createM.state.phase === "settled") createM.reset();
    await settleCreate(await createM.submit("POST", "/matters", { title: checked.value }));
  }

  const retryCreate = async () => settleCreate(await createM.retry());
  const reauthCreate = useReauthenticate(subject, retryCreate);

  // ---- Title -----------------------------------------------------------

  function startEdit() {
    if (!lawyer || paused || titleM.locked) return;
    setEditing(true);
    setDraft(lawyer.title);
    setDraftError(null);
    setTitleKeyReused(false);
    focusLater(editInputRef);
  }

  function cancelEdit() {
    if (titleM.pending) return;
    titleM.reset();
    setEditing(false);
    setStale(null);
    setDraftError(null);
    focusLater(editButtonRef);
  }

  async function settleTitle(outcome: Outcome | null, matterId: string) {
    if (outcome === null) return;
    if (outcome.kind === "ok") {
      const receipt = parseReceipt(outcome.data);
      titleM.reset();
      setEditing(false);
      setStale(null);
      await load(matterId, () => {
        if (receipt) {
          setSavedRevision(receipt.revision);
          announce(C.c22(receipt.revision));
        }
        focusLater(editButtonRef);
      });
      return;
    }
    if (outcome.kind === "conflict" && outcome.code === "revision_mismatch") {
      await load(matterId, (latest) => {
        if (latest.kind !== "lawyer") return;
        setStale(latest);
        focusLater(staleHeadingRef);
      });
      return;
    }
    if (outcome.kind === "conflict" && outcome.code === "idempotency_key_reused") {
      await load(matterId, () => {
        setTitleKeyReused(true);
        focusLater(summaryAlertRef);
      });
      return;
    }
    if (outcome.kind === "not_found" || outcome.kind === "forbidden") {
      applyLoad({ kind: "not_found" });
      return;
    }
    if (outcome.kind === "invalid") {
      setDraftError(C.C13_HIDDEN);
      focusLater(editInputRef);
      return;
    }
    focusLater(summaryAlertRef);
  }

  async function saveTitle(revision: number) {
    if (!lawyer || paused || titleM.locked) return;
    const checked = checkTitle(draft);
    setDraftError(checked.error);
    if (checked.error) {
      focusLater(editInputRef);
      return;
    }
    setTitleKeyReused(false);
    if (titleM.state.phase === "settled") titleM.reset();
    const matterId = lawyer.matterId;
    await settleTitle(
      await titleM.submit("PATCH", matterApiPath(matterId), { title: checked.value }, ifMatch(revision)),
      matterId,
    );
  }

  const retryTitle = async () => {
    if (lawyer) await settleTitle(await titleM.retry(), lawyer.matterId);
  };
  const reauthTitle = useReauthenticate(subject, retryTitle);

  // ---- Conflict result ---------------------------------------------------

  async function settleConflict(outcome: Outcome | null, matterId: string, recorded: ResultChoice, sentReason: string) {
    if (outcome === null) return;
    if (outcome.kind === "ok") {
      const receipt = parseReceipt(outcome.data);
      conflictM.reset();
      setChoice(null);
      setReason("");
      setExpanded(false);
      setNotice(null);
      setChanged(false);
      await load(matterId, () => {
        const revision = receipt?.revision ?? 0;
        setSettleKey((key) => key + 1);
        setWaiverNote(recorded === "WAIVE" ? C.c25(revision) : null);
        announce(confirmedAnnouncement(recorded, revision));
        focusLater(conflictHeadingRef);
      });
      return;
    }
    if (
      outcome.kind === "conflict" &&
      (outcome.code === "revision_mismatch" ||
        outcome.code === "conflict_changed" ||
        outcome.code === "conflict_not_waivable")
    ) {
      await load(matterId, (latest) => {
        if (latest.kind !== "lawyer") return;
        setChanged(true);
        if (choicesFor(latest.conflictStatus).includes(recorded)) {
          setNotice({ kind: "still" });
          setExpanded(true);
        } else {
          setNotice({
            kind: "gone",
            stampLabel: STAMP_LABEL[latest.conflictStatus],
            reason: recorded === "WAIVE" && sentReason ? sentReason : null,
          });
          setChoice(null);
          setReason("");
          setExpanded(false);
        }
        focusLater(noticeHeadingRef);
      });
      return;
    }
    if (outcome.kind === "conflict" && outcome.code === "idempotency_key_reused") {
      await load(matterId, () => {
        setNotice({ kind: "key_reused" });
        focusLater(noticeHeadingRef);
      });
      return;
    }
    if (outcome.kind === "not_found" || outcome.kind === "forbidden") {
      applyLoad({ kind: "not_found" });
      return;
    }
    if (outcome.kind === "invalid" && recorded === "WAIVE") {
      setReasonError(C.C16_HIDDEN);
      focusLater(reasonRef);
      return;
    }
    if (outcome.kind === "invalid") {
      setNotice({ kind: "defect", code: outcome.code });
      focusLater(noticeHeadingRef);
      return;
    }
    focusLater(conflictAlertRef);
  }

  async function recordResult() {
    if (!lawyer || paused || conflictM.locked) return;
    setWaiverNote(null);
    if (choice === null) {
      setChoiceError("Choose a result to record.");
      focusLater(firstChoiceRef);
      return;
    }
    setChoiceError(null);
    const matterId = lawyer.matterId;
    if (conflictM.state.phase === "settled") conflictM.reset();
    if (choice === "WAIVE") {
      const checked = checkReason(reason);
      setReasonError(checked.error);
      if (checked.error) {
        focusLater(reasonRef);
        return;
      }
      setNotice(null);
      await settleConflict(
        await conflictM.submit(
          "POST",
          `${matterApiPath(matterId)}/conflict-waivers`,
          { reason: checked.value },
          ifMatch(lawyer.revision),
        ),
        matterId,
        "WAIVE",
        checked.value,
      );
      return;
    }
    setNotice(null);
    await settleConflict(
      await conflictM.submit(
        "POST",
        `${matterApiPath(matterId)}/conflict-checks`,
        { result: choice },
        ifMatch(lawyer.revision),
      ),
      matterId,
      choice,
      "",
    );
  }

  const retryConflict = async () => {
    const frozen = conflictM.state.phase === "settled" ? conflictM.state.frozen : null;
    if (!lawyer || !frozen) return;
    const recorded: ResultChoice = frozen.path.endsWith("/conflict-waivers")
      ? "WAIVE"
      : (JSON.parse(frozen.body) as { result: ResultChoice }).result;
    const sentReason = recorded === "WAIVE" ? (JSON.parse(frozen.body) as { reason: string }).reason : "";
    await settleConflict(await conflictM.retry(), lawyer.matterId, recorded, sentReason);
  };
  const reauthConflict = useReauthenticate(subject, retryConflict);

  // ---- Reads -------------------------------------------------------------

  const reloadCurrent = async () => {
    const matterId = shown?.matterId ?? (screen.kind === "loading" ? screen.matterId : null);
    if (matterId) await load(matterId);
  };
  const reauthRead = useReauthenticate(subject, reloadCurrent);

  function showLatest() {
    const latest = backgroundLatest;
    if (!latest) return;
    setBackgroundLatest(null);
    setScreen({ kind: "lawyer", matter: latest });
    setLoadedAt(new Date());
    setChanged(lawyer !== null && latest.conflictStatus !== lawyer.conflictStatus);
    if (editing) {
      setStale(latest);
      focusLater(staleHeadingRef);
      return;
    }
    if (choice !== null && !choicesFor(latest.conflictStatus).includes(choice)) {
      setNotice({ kind: "gone", stampLabel: STAMP_LABEL[latest.conflictStatus], reason: reason.trim() || null });
      setChoice(null);
      setReason("");
    } else if (choice !== null) {
      setNotice({ kind: "still" });
    }
    focusLater(conflictHeadingRef);
  }

  // ---- Leaving -----------------------------------------------------------

  function leaveNow() {
    leaving.current = true;
    window.location.assign(intakePath());
  }

  function openAnother() {
    if (dirty) {
      setConfirmLeave(true);
      focusLater(stayRef);
      return;
    }
    leaveNow();
  }

  // ---- Render ------------------------------------------------------------

  const slow = createM.slow || titleM.slow || conflictM.slow;
  const live = slow ? C.C20 : announcement;
  const left = TITLE_MAX - codePoints(title.trim());
  const counter = left <= COUNTER_WINDOW ? C.c12(Math.max(left, 0)) : null;
  const pausedProps = {
    "aria-disabled": paused ? true : undefined,
    "aria-describedby": paused ? "read-problem" : undefined,
  } as const;

  return (
    <>
      <p className="visually-hidden" role="status" aria-live="polite">
        {live}
      </p>

      {lawyer ? (
        <div className={styles.toolbar}>
          <span />
          <button type="button" className={styles.buttonQuiet} onClick={openAnother}>
            <ArrowCounterClockwise className={styles.buttonIcon} weight="bold" aria-hidden="true" focusable="false" />
            Open another matter
          </button>
        </div>
      ) : null}

      {confirmLeave ? (
        <LeaveConfirm
          pending={anyLocked}
          stayRef={stayRef}
          onStay={() => setConfirmLeave(false)}
          onLeave={leaveNow}
        />
      ) : null}

      {screen.kind === "new" ? <Progress index={0} /> : null}
      {lawyer ? <Progress index={progressIndexOf(lawyer)} /> : null}

      {screen.kind === "new" ? (
        <div className={styles.draftGrid}>
          <section className={styles.panel} aria-labelledby="intake-heading" aria-busy={createM.pending || undefined}>
            <h2 id="intake-heading" className={styles.panelHeading}>
              New matter
            </h2>
            <MatterAlert
              outcome={alertable(createM.outcome)}
              context="create"
              headingRef={createAlertRef}
              onRetry={() => void retryCreate()}
              onReauthenticate={() => void reauthCreate()}
            />
            {formError ? (
              <p ref={formErrorRef} tabIndex={-1} role="alert" className={styles.error}>
                {formError}
              </p>
            ) : null}
            <form noValidate onSubmit={openMatter} className={styles.fields}>
              <FieldShell id="matter-title" label={C.C11_LABEL} hint={C.C11_HINT} error={titleError} counter={counter}>
                <input
                  ref={createTitleRef}
                  id="matter-title"
                  name="title"
                  type="text"
                  autoComplete="off"
                  className={styles.input}
                  value={title}
                  onChange={(event) => {
                    setTitle(event.target.value);
                    setFormError(null);
                  }}
                  readOnly={createM.locked}
                  aria-invalid={titleError ? true : undefined}
                  aria-describedby={describedBy(
                    "matter-title-hint",
                    counter && "matter-title-counter",
                    titleError && "matter-title-error",
                  )}
                />
              </FieldShell>
              <div className={styles.formActions}>
                <button type="submit" className={styles.buttonPrimary} aria-disabled={createM.locked || undefined}>
                  {createM.pending ? "Opening matter" : "Open matter"}
                </button>
              </div>
            </form>
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
      ) : null}

      {screen.kind === "loading" ? (
        readProblem ? (
          <div className={styles.matterGrid}>
            <ReadAlert
              outcome={readProblem}
              headingRef={readAlertRef}
              onRetry={() => void reloadCurrent()}
              onReauthenticate={() => void reauthRead()}
            />
          </div>
        ) : (
          <MatterSkeleton />
        )
      ) : null}

      {screen.kind === "not_available" ? (
        <div className={styles.matterGrid}>
          <MatterUnavailable headingRef={unavailableRef} />
        </div>
      ) : null}

      {shown && readProblem ? (
        <div className={styles.progressNav}>
          <ReadAlert
            outcome={readProblem}
            headingRef={readAlertRef}
            onRetry={() => void reloadCurrent()}
            onReauthenticate={() => void reauthRead()}
          />
          {loadedAt ? <p className={local.metaLine}>{C.c62(clockTime(loadedAt))}</p> : null}
        </div>
      ) : null}

      {screen.kind === "requester" ? (
        <RequesterStatus
          matter={screen.matter}
          headingRef={requesterRef}
          paused={paused}
          onRefresh={() => {
            if (paused) return;
            void load(screen.matter.matterId, (matter) => {
              if (matter.kind === "requester") {
                announce(C.c83(matter.status === "ready" ? C.C81_LABEL : C.C80_LABEL));
              }
            });
          }}
        />
      ) : null}

      {lawyer && backgroundLatest ? (
        <div className={`${local.alert} ${styles.progressNav}`} data-tone="unknown">
          <p>{C.C44_BODY}</p>
          <div className={local.inlineActions}>
            <button type="button" className={styles.buttonQuiet} onClick={showLatest}>
              {C.C44_BUTTON}
            </button>
          </div>
        </div>
      ) : null}

      {lawyer ? (
        <div className={styles.matterGrid}>
          <section className={styles.summary} aria-labelledby="summary-heading" aria-busy={titleM.pending || undefined}>
            <h2 id="summary-heading" ref={referenceRef} tabIndex={-1} className={`${styles.panelHeading} ${local.reference}`}>
              <span className="visually-hidden">Matter reference</span> {lawyer.matterId}
            </h2>
            <MatterAlert
              outcome={alertable(titleM.outcome)}
              context="change"
              headingRef={summaryAlertRef}
              onRetry={() => void retryTitle()}
              onReauthenticate={() => void reauthTitle()}
            />
            {titleKeyReused ? (
              <RequestAlert headingRef={summaryAlertRef} heading={C.C33_HEADING}>
                <p>{C.C33_BODY}</p>
              </RequestAlert>
            ) : null}

            {stale ? (
              <div className={local.comparison}>
                <h3 ref={staleHeadingRef} tabIndex={-1} className={styles.subHeading}>
                  {C.C40_HEADING}
                </h3>
                <p className={local.metaLine}>{C.c40Body(stale.revision)}</p>
                <dl className={styles.facts}>
                  <div>
                    <dt>{C.c40Latest(stale.revision)}</dt>
                    <dd>{stale.title}</dd>
                  </div>
                </dl>
                <FieldShell id="matter-title-mine" label={C.C40_YOURS} error={draftError}>
                  <input
                    ref={editInputRef}
                    id="matter-title-mine"
                    type="text"
                    autoComplete="off"
                    className={styles.input}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    readOnly={titleM.locked}
                    aria-invalid={draftError ? true : undefined}
                    aria-describedby={describedBy(draftError && "matter-title-mine-error")}
                  />
                </FieldShell>
                <div className={local.inlineActions}>
                  <button type="button" className={styles.buttonQuiet} onClick={cancelEdit}>
                    {C.C40_KEEP}
                  </button>
                  <button
                    type="button"
                    className={styles.buttonPrimary}
                    onClick={() => void saveTitle(stale.revision)}
                    aria-disabled={titleM.locked || paused || undefined}
                  >
                    {titleM.pending ? "Saving" : C.C40_SAVE}
                  </button>
                </div>
              </div>
            ) : editing ? (
              <form
                noValidate
                className={local.stack}
                onSubmit={(event) => {
                  event.preventDefault();
                  void saveTitle(lawyer.revision);
                }}
              >
                <FieldShell id="matter-title-edit" label={C.C11_LABEL} hint={C.C11_HINT} error={draftError}>
                  <input
                    ref={editInputRef}
                    id="matter-title-edit"
                    type="text"
                    autoComplete="off"
                    className={styles.input}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    readOnly={titleM.locked}
                    aria-invalid={draftError ? true : undefined}
                    aria-describedby={describedBy("matter-title-edit-hint", draftError && "matter-title-edit-error")}
                  />
                </FieldShell>
                <div className={local.inlineActions}>
                  <button
                    type="submit"
                    className={styles.buttonPrimary}
                    aria-disabled={titleM.locked || paused || undefined}
                    aria-describedby={paused ? "read-problem" : undefined}
                  >
                    {titleM.pending ? "Saving" : "Save title"}
                  </button>
                  <button type="button" className={styles.buttonQuiet} onClick={cancelEdit}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <>
                <dl className={styles.facts}>
                  <div>
                    <dt>Title</dt>
                    <dd>{lawyer.title}</dd>
                  </div>
                </dl>
                {savedRevision !== null ? <p className={local.metaLine}>{C.c22(savedRevision)}</p> : null}
                <div>
                  <button
                    ref={editButtonRef}
                    type="button"
                    className={styles.buttonQuiet}
                    onClick={startEdit}
                    {...pausedProps}
                  >
                    Edit title
                  </button>
                </div>
              </>
            )}
          </section>

          <section
            className={styles.panel}
            aria-labelledby="conflict-heading"
            aria-busy={conflictM.pending || undefined}
            data-privileged=""
          >
            <div className={styles.panelHead}>
              <h2 id="conflict-heading" ref={conflictHeadingRef} tabIndex={-1} className={styles.panelHeading}>
                Conflict check
              </h2>
              <span className={local.stack}>
                <ConfirmedStamp matter={lawyer} settleKey={settleKey} />
                {changed ? <span className={local.changedMarker}>{C.C45}</span> : null}
              </span>
            </div>
            <p className={styles.privileged}>
              <LockSimple className={styles.inlineIcon} weight="bold" aria-hidden="true" focusable="false" />
              Privileged. The requester never sees this panel.
            </p>
            <p className={styles.hint}>{C.C14}</p>

            {notice?.kind === "still" ? (
              <RequestAlert tone="unknown" headingRef={noticeHeadingRef} heading={C.C41_HEADING}>
                <p>{C.C41_BODY}</p>
              </RequestAlert>
            ) : null}
            {notice?.kind === "gone" ? (
              <RequestAlert
                tone="unknown"
                headingRef={noticeHeadingRef}
                heading={C.C42_HEADING}
                actions={
                  notice.reason ? (
                    <button
                      type="button"
                      className={styles.buttonQuiet}
                      onClick={() => {
                        void navigator.clipboard?.writeText(notice.reason ?? "").then(
                          () => announce("Reason copied."),
                          () => undefined,
                        );
                      }}
                    >
                      {C.C42_COPY}
                    </button>
                  ) : null
                }
              >
                <p>{C.c42Body(notice.stampLabel)}</p>
                {notice.reason ? <pre className={local.keptReason}>{notice.reason}</pre> : null}
              </RequestAlert>
            ) : null}
            {notice?.kind === "defect" ? (
              <RequestAlert headingRef={noticeHeadingRef} heading={C.C63_HEADING}>
                <p>{C.c63Body(notice.code)}</p>
              </RequestAlert>
            ) : null}
            {notice?.kind === "key_reused" ? (
              <RequestAlert headingRef={noticeHeadingRef} heading={C.C33_HEADING}>
                <p>{C.C33_BODY}</p>
              </RequestAlert>
            ) : null}
            <MatterAlert
              outcome={alertable(conflictM.outcome)}
              context="change"
              headingRef={conflictAlertRef}
              onRetry={() => void retryConflict()}
              onReauthenticate={() => void reauthConflict()}
            />
            {waiverNote ? <p className={styles.signoffNote}>{waiverNote}</p> : null}

            {choicesCollapsed(lawyer.conflictStatus) && !expanded ? (
              <div>
                <button
                  ref={changeButtonRef}
                  type="button"
                  className={styles.buttonQuiet}
                  onClick={() => {
                    if (paused) return;
                    setExpanded(true);
                    setWaiverNote(null);
                    focusLater(firstChoiceRef);
                  }}
                  {...pausedProps}
                >
                  Change the result
                </button>
              </div>
            ) : (
              <div className={styles.record}>
                <ResultChoices
                  idPrefix="conflict"
                  status={lawyer.conflictStatus}
                  choices={choicesFor(lawyer.conflictStatus)}
                  value={choice}
                  onChange={(next) => {
                    setChoice(next);
                    setChoiceError(null);
                  }}
                  error={choiceError}
                  locked={conflictM.locked}
                  firstRef={firstChoiceRef}
                />
                {choice === "WAIVE" ? (
                  <FieldShell id="waiver-reason" label={C.C16_LABEL} hint={C.C16_HINT} error={reasonError}>
                    <textarea
                      ref={reasonRef}
                      id="waiver-reason"
                      autoComplete="off"
                      rows={3}
                      className={styles.textarea}
                      value={reason}
                      onChange={(event) => {
                        setReason(event.target.value);
                        if (reasonError) setReasonError(null);
                      }}
                      readOnly={conflictM.locked}
                      aria-invalid={reasonError ? true : undefined}
                      aria-describedby={describedBy("waiver-reason-hint", reasonError && "waiver-reason-error")}
                    />
                  </FieldShell>
                ) : null}
                <div className={styles.recordActions}>
                  <button
                    type="button"
                    className={styles.buttonPrimary}
                    onClick={() => void recordResult()}
                    aria-disabled={conflictM.locked || paused || undefined}
                    aria-describedby={paused ? "read-problem" : undefined}
                  >
                    {conflictM.pending ? "Recording" : "Record result"}
                  </button>
                  <p className={styles.recordedAs}>{C.C15}</p>
                </div>
              </div>
            )}

            <Gate matter={lawyer} />
          </section>
        </div>
      ) : null}
    </>
  );
}
