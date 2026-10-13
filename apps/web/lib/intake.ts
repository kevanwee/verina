/**
 * Intake and conflict-check vocabulary for the synthetic prototype at
 * /workbench/intake. Flow: docs/design/flows/US-1-US-3-intake-and-conflict.md.
 *
 * SYNTHETIC: every party, person, matter number and time below is invented.
 * Nothing here is persisted, sent or checked against a real register.
 */

/** Matter states. "Submitted" is the transition into "pending". */
export type IntakeStage =
  | "draft"
  | "pending"
  | "conflict"
  | "cleared"
  | "waived"
  | "declined";

/** What a lawyer can record on the conflict check. */
export type ConflictResult = "clear" | "conflict" | "waived" | "declined";

export type Viewer = "lawyer" | "requester";

export const CONTRACT_TYPES = [
  "Non-disclosure agreement",
  "Master services agreement",
  "SaaS or vendor agreement",
  "Data processing agreement",
] as const;

export type IntakeDetails = {
  counterparty: string;
  contractType: string;
  value: string;
  deadline: string;
  documentName: string;
};

export type IntakeErrors = Partial<Record<"counterparty" | "contractType" | "deadline", string>>;

/** Synthetic prefill so the prototype can be walked through in seconds. */
export const SAMPLE_DETAILS: IntakeDetails = {
  counterparty: "Harbourline Systems Pte Ltd",
  contractType: "Master services agreement",
  value: "SGD 180,000 a year",
  deadline: "2026-10-24",
  documentName: "Harbourline MSA, supplier draft v3.docx",
};

export const PEOPLE = {
  requester: { name: "Ong Hui Min", role: "Procurement, requester" },
  lawyer: { name: "Nadia Lim", role: "Associate, on this matter" },
  partner: { name: "Daniel Koh", role: "Partner, signs off" },
} as const;

export const MATTER_REFERENCE = "VR-2026-0147";
/** Fixed synthetic timestamp so the prototype renders the same every time. */
export const RECORDED_AT = "13 Oct 2026, 14:20 SGT";

/** Privileged: the register search the lawyer reviews. Never shown to requesters. */
export const REGISTER_HITS = [
  {
    id: "hit-1",
    party: "Harbourline Holdings Pte Ltd",
    relation: "Parent of the sample party",
    detail:
      "Adverse party in matter M-2025-0388 (supply dispute, closed March 2026).",
  },
  {
    id: "hit-2",
    party: "Harbourline Systems Pte Ltd",
    relation: "Same sample name",
    detail: "No current or past matters. Listed as a prospect only.",
  },
] as const;

export const WAIVER_REASON_MAX = 2000;

/** Required-field checks for the intake form. Plain language, names the fix. */
export function validateDetails(details: IntakeDetails): IntakeErrors {
  const errors: IntakeErrors = {};
  if (!details.counterparty.trim()) {
    errors.counterparty = "Enter the other party's name.";
  }
  if (!details.contractType) {
    errors.contractType = "Choose a contract type.";
  }
  if (!details.deadline) {
    errors.deadline = "Enter the date you need this by.";
  }
  return errors;
}

/** Returns an error message, or null when the waiver reason is acceptable. */
export function validateWaiverReason(reason: string): string | null {
  const trimmed = reason.trim();
  if (!trimmed) {
    return "Enter a reason for the waiver. The signing partner will see it.";
  }
  if (Array.from(trimmed).length > WAIVER_REASON_MAX) {
    return `Keep the waiver reason to ${WAIVER_REASON_MAX} characters or fewer.`;
  }
  return null;
}

/** Review may start only once a result and a named clearer are recorded. */
export function isReadyForReview(stage: IntakeStage): boolean {
  return stage === "cleared" || stage === "waived";
}

/** Lawyer-facing stage labels. */
export const STAGE_LABEL: Record<IntakeStage, string> = {
  draft: "Draft",
  pending: "Conflict pending",
  conflict: "Conflict found",
  cleared: "Cleared",
  waived: "Waived",
  declined: "Declined",
};

/**
 * Requester-facing stage. Deliberately coarse: a requester must not be able
 * to infer that a conflict was found, waived or why a matter was declined.
 */
export const REQUESTER_STAGE: Record<IntakeStage, { label: string; note: string }> = {
  draft: { label: "Not sent", note: "Your request has not been sent to legal yet." },
  pending: {
    label: "Checks in progress",
    note: "Legal is running its standard checks before work starts.",
  },
  conflict: {
    label: "Checks in progress",
    note: "Legal is running its standard checks before work starts.",
  },
  cleared: { label: "With legal for review", note: "Ready for legal review. Legal can begin after its checks." },
  waived: { label: "With legal for review", note: "Ready for legal review. Legal can begin after its checks." },
  declined: {
    label: "Closed",
    note: "Legal cannot take this matter on. Contact the legal team to discuss next steps.",
  },
};

/** The four-step progress line shown to lawyers. */
export const PROGRESS_STEPS = ["Draft", "Submitted", "Conflict check", "Ready for review"] as const;

export function progressIndex(stage: IntakeStage): number {
  switch (stage) {
    case "draft":
      return 0;
    case "pending":
    case "conflict":
    case "declined":
      return 2;
    case "cleared":
    case "waived":
      return 3;
  }
}

/** Announcement for the polite live region after each state change. */
export function announce(stage: IntakeStage, viewer: Viewer): string {
  if (viewer === "requester") {
    const { label, note } = REQUESTER_STAGE[stage];
    return `Status: ${label}. ${note}`;
  }
  switch (stage) {
    case "draft":
      return "Back to draft. Nothing has been sent.";
    case "pending":
      return `Request submitted as ${MATTER_REFERENCE}. Conflict check pending.`;
    case "conflict":
      return "Conflict found and recorded. Review stays blocked until it is waived or the matter is declined.";
    case "cleared":
      return `Conflict check recorded as clear by ${PEOPLE.lawyer.name}. Ready for review.`;
    case "waived":
      return `Conflict waived by ${PEOPLE.lawyer.name}, with reason. Ready for review. The waiver will show at sign-off.`;
    case "declined":
      return "Matter declined. The requester sees that it is closed, without the reason.";
  }
}
