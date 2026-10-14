/**
 * Connected-mode microcopy, keyed by the ids in docs/design/INTAKE_PERSISTENCE_STATES.md
 * section 10. Plain, sentence case, no exclamation marks, no em or en dashes.
 * Change wording only through the design specification.
 */

export const C = {
  C01_HEADING: "Sign in to continue",
  C02_BODY: "Sign in to open a matter or view its status.",
  C02_BUTTON: "Sign in",

  C05_HEADING: "Your session has ended",
  C06_BODY: "Sign in again to keep working. Your unsaved changes stay on this page.",
  C07_BODY:
    "Sign in again to finish saving. Your last change has not been confirmed. After you sign in, Verina sends the same request again, so it cannot be recorded twice.",
  C06_BUTTON: "Sign in again",
  C08_APPENDIX: "Signing in reloads this page. Changes that are not saved will be lost.",

  C09_HEADING: "Your account is not set up for Verina",
  C09_BODY:
    "You signed in, but this account cannot use Verina yet. Contact your Verina administrator.",

  C10: "Your account cannot open matters. A lawyer on your team can open one for you.",

  C11_LABEL: "Matter title (required)",
  C11_HINT: "A short working name, such as the counterparty and contract type.",
  c12: (left: number) => `${left} ${left === 1 ? "character" : "characters"} left`,
  C13_BLANK: "Enter a matter title.",
  C13_LONG: "Keep the title to 200 characters or fewer.",
  C13_HIDDEN: "Remove line breaks and hidden characters from the title.",

  C14: "Verina does not search a conflict register in this release. Record the result of your firm's check here.",
  C15: "Recorded under your signed-in account.",

  C16_LABEL: "Reason for waiver (required)",
  C16_HINT:
    "Up to 2,000 characters. The reason is kept in the matter's audit record and is not shown on this page after it is saved.",
  C16_BLANK: "Enter a reason for the waiver.",
  C16_LONG: "Keep the reason to 2,000 characters or fewer.",
  C16_HIDDEN: "Remove hidden characters from the reason.",

  C18: "Replaces the current result. Any waiver on record stops applying.",

  C20: "Saving.",
  c21: (id: string, revision: number) =>
    `Matter opened. Reference ${id}. Revision ${revision}. Conflict check pending.`,
  c22: (revision: number) => `Saved. Revision ${revision}.`,
  c23: (revision: number) =>
    `Conflict check recorded as clear. Revision ${revision}. Ready for review.`,
  c24: (revision: number) =>
    `Conflict recorded. Revision ${revision}. Review stays blocked until the conflict is waived with a reason.`,
  c25: (revision: number) =>
    `Waiver recorded with its reason. Revision ${revision}. Ready for review. The reason is in the audit record.`,
  c26: (revision: number) => `On record, revision ${revision}`,
  C27_OPEN: "Ready for review. A conflict result is on record.",
  C27_PENDING: "Review is blocked until a conflict result is recorded.",
  C27_CONFLICT: "Review is blocked until the conflict is waived with a reason.",

  C30_HEADING: "Not confirmed yet",
  C31_BODY:
    "Verina could not confirm the matter was opened. Your connection may have dropped. Retry sends the same request, so it cannot open a second matter.",
  C32_BODY:
    "Verina could not confirm this change was saved. Retry sends the same request, so it cannot be recorded twice.",
  RETRY: "Retry",

  C33_HEADING: "This request could not be completed",
  C33_BODY: "Verina has reloaded the latest version of this matter. Check it, then try again.",

  C40_HEADING: "This matter changed while you were editing",
  c40Body: (revision: number) =>
    `Someone saved a new version (revision ${revision}). Your title has not been saved. Choose which to keep.`,
  c40Latest: (revision: number) => `Latest saved title (revision ${revision})`,
  C40_YOURS: "Your unsaved title",
  C40_KEEP: "Keep the latest",
  C40_SAVE: "Save my title",

  C41_HEADING: "This matter changed before your result was recorded",
  C41_BODY:
    "The latest version is shown above. Your choice is still selected but has not been recorded. Check it, then select Record result again.",

  C42_HEADING: "The conflict check changed before your result was recorded",
  c42Body: (stampLabel: string) =>
    `It now reads ${stampLabel}. Your result was not recorded. Your waiver reason is kept below until you leave this page.`,
  C42_COPY: "Copy reason",

  c43: (revision: number) => `This matter was updated. Now at revision ${revision}.`,
  C44_BODY: "This matter has changed since you opened it. Your edits are kept.",
  C44_BUTTON: "Show latest",
  C45: "Changed since you opened this matter",

  C50_HEADING: "This matter is not available",
  C51_BODY:
    "It may not exist, or your account may not have access to it. Check the link, or ask the person who shared it.",
  C51_LINK: "Go to Intake",

  C60_HEADING: "Verina cannot load this matter right now",
  C60_BODY: "This is a problem on our side. Try again in a few minutes.",
  C61_HEADING: "Verina could not save this just now",
  C61_BODY:
    "Try again in a few minutes. Retrying sends the same request, so it cannot be recorded twice.",
  TRY_AGAIN: "Try again",
  c62: (time: string) =>
    `Last loaded at ${time} on this device. Actions are paused until Verina is available.`,

  C63_HEADING: "This request could not be completed",
  c63Body: (code: string) =>
    `Nothing new was recorded. Reload the page and try again. If it happens again, tell your Verina administrator and quote code ${code}.`,

  C70_HEADING: "Leave without saving?",
  C70_BODY: "Your changes on this page have not been saved.",
  C70_BODY_PENDING:
    "Your last change has not been confirmed. If you leave now, you cannot retry it from here.",
  C70_STAY: "Stay on this page",
  C70_LEAVE: "Leave without saving",

  C80_LABEL: "Checks in progress",
  C80_NOTE: "Legal is completing its standard checks before work starts.",
  C81_LABEL: "With legal for review",
  C81_NOTE: "Legal's checks are complete. The request is ready for legal review.",
  C82: "This page shows status only. Your lawyer shares advice with you directly.",
  c83: (label: string) => `Status checked: ${label}.`,

  C90: "Development environment. Use invented examples only. Matters you open here are saved to a test database.",
} as const;

/** Document titles (section 8). Never include the matter title. */
export const TITLES = {
  newMatter: "New matter | Verina",
  matter: (reference: string) => `Matter ${reference} | Verina`,
  requester: "Request status | Verina",
  notAvailable: "Matter not available | Verina",
  signIn: "Sign in | Verina",
} as const;
