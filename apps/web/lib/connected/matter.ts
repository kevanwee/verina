/**
 * Connected intake model (INTAKE_PERSISTENCE_STATES.md), against the ADR 007 contract.
 * Pure: parsing, validation, labels and announcements. Where the contract and the design
 * spec differ, the contract wins.
 */

import { C } from "./copy";
import { ID_SEGMENT } from "./routes";
import { checkText } from "./validation";

export type ConflictStatus = "pending" | "conflict" | "clear" | "waived";
export type MatterStatus = "ready" | "awaiting_clearance";

export type LawyerMatter = {
  kind: "lawyer";
  matterId: string;
  revision: number;
  title: string;
  conflictStatus: ConflictStatus;
  status: MatterStatus;
};

export type RequesterMatter = { kind: "requester"; matterId: string; status: MatterStatus };

export type Matter = LawyerMatter | RequesterMatter;

const CONFLICT_STATUSES: readonly ConflictStatus[] = ["pending", "conflict", "clear", "waived"];
const isConflictStatus = (value: unknown): value is ConflictStatus =>
  CONFLICT_STATUSES.includes(value as ConflictStatus);
const isMatterStatus = (value: unknown): value is MatterStatus =>
  value === "ready" || value === "awaiting_clearance";

/**
 * The projection decides the view: a body with a revision is the lawyer projection, one
 * without is the requester projection. Nothing is filled in from elsewhere.
 */
export function parseMatter(json: unknown): Matter | null {
  if (!json || typeof json !== "object") return null;
  const raw = json as Record<string, unknown>;
  if (typeof raw.matter_id !== "string" || !ID_SEGMENT.test(raw.matter_id)) return null;
  if (!isMatterStatus(raw.status)) return null;
  if (raw.revision === undefined) {
    return { kind: "requester", matterId: raw.matter_id, status: raw.status };
  }
  if (
    typeof raw.revision !== "number" ||
    !Number.isInteger(raw.revision) ||
    raw.revision < 0 ||
    typeof raw.title !== "string" ||
    !isConflictStatus(raw.conflict_status)
  ) {
    return null;
  }
  return {
    kind: "lawyer",
    matterId: raw.matter_id,
    revision: raw.revision,
    title: raw.title,
    conflictStatus: raw.conflict_status,
    status: raw.status,
  };
}

/** Mutation receipts: {matter_id, revision, ...}. */
export function parseReceipt(json: unknown): { matterId: string; revision: number } | null {
  if (!json || typeof json !== "object") return null;
  const raw = json as Record<string, unknown>;
  if (typeof raw.matter_id !== "string" || !ID_SEGMENT.test(raw.matter_id)) return null;
  if (typeof raw.revision !== "number" || !Number.isInteger(raw.revision)) return null;
  return { matterId: raw.matter_id, revision: raw.revision };
}

export const TITLE_MAX = 200;
export const REASON_MAX = 2000;
/** The counter appears only within this many characters of the limit (C-12). */
export const COUNTER_WINDOW = 20;

export function checkTitle(raw: string): { value: string; error: string | null } {
  const { value, problem } = checkText(raw, TITLE_MAX);
  const error =
    problem === "blank" ? C.C13_BLANK : problem === "long" ? C.C13_LONG : problem === "hidden" ? C.C13_HIDDEN : null;
  return { value, error };
}

export function checkReason(raw: string): { value: string; error: string | null } {
  const { value, problem } = checkText(raw, REASON_MAX, { allowNewlines: true });
  const error =
    problem === "blank" ? C.C16_BLANK : problem === "long" ? C.C16_LONG : problem === "hidden" ? C.C16_HIDDEN : null;
  return { value, error };
}

/** API conflict status to the existing stamp tones (ConflictStamp stages). */
export const STAMP_STAGE = {
  pending: "pending",
  conflict: "conflict",
  clear: "cleared",
  waived: "waived",
} as const satisfies Record<ConflictStatus, string>;

export const STAMP_LABEL: Record<ConflictStatus, string> = {
  pending: "Conflict pending",
  conflict: "Conflict found",
  clear: "Cleared",
  waived: "Waived",
};

/** Progress steps in connected mode: "Submitted" reads "Opened". */
export const CONNECTED_STEPS = ["Draft", "Opened", "Conflict check", "Ready for review"] as const;

/** The gate and the last step follow `status`, never `conflict_status` alone (section 4.2). */
export function progressIndexOf(matter: LawyerMatter) {
  return matter.status === "ready" ? 3 : 2;
}

export function gateCopy(matter: LawyerMatter) {
  if (matter.status === "ready") return C.C27_OPEN;
  return matter.conflictStatus === "conflict" ? C.C27_CONFLICT : C.C27_PENDING;
}

export type ResultChoice = "CLEAR" | "CONFLICT" | "WAIVE";

/** What a lawyer may record from each state, as the API allows it. */
export function choicesFor(status: ConflictStatus): ResultChoice[] {
  switch (status) {
    case "pending":
      return ["CLEAR", "CONFLICT"];
    case "conflict":
      return ["WAIVE", "CLEAR"];
    case "clear":
      return ["CONFLICT"];
    case "waived":
      return ["CLEAR", "CONFLICT"];
  }
}

/** Clear and waived offer "Change the result" behind a quiet button. */
export function choicesCollapsed(status: ConflictStatus) {
  return status === "clear" || status === "waived";
}

export function choiceCopy(choice: ResultChoice, status: ConflictStatus): { label: string; help: string } {
  if (choice === "WAIVE") {
    return { label: "Waive the conflict", help: "You accept the conflict and record why. Needs a reason." };
  }
  const replacing = status !== "pending";
  if (choice === "CLEAR") {
    return { label: "Clear", help: replacing ? C.C18 : "No conflict. Work can start." };
  }
  return {
    label: "Conflict found",
    help: replacing ? C.C18 : "Blocks review until the conflict is waived with a reason.",
  };
}

export function confirmedAnnouncement(choice: ResultChoice, revision: number) {
  if (choice === "WAIVE") return C.c25(revision);
  return choice === "CLEAR" ? C.c23(revision) : C.c24(revision);
}

export const REQUESTER_STATUS: Record<MatterStatus, { label: string; note: string }> = {
  awaiting_clearance: { label: C.C80_LABEL, note: C.C80_NOTE },
  ready: { label: C.C81_LABEL, note: C.C81_NOTE },
};

export function intakePath(matterId?: string | null) {
  return matterId ? `/workbench/intake/${matterId}` : "/workbench/intake";
}

export function matterApiPath(matterId: string) {
  return `/matters/${encodeURIComponent(matterId)}`;
}

/** "hh:mm" in the viewer's local time, for C-62. */
export function clockTime(date: Date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}
