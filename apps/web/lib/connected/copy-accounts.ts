/**
 * Front-door copy: sign-in, account and administration. Same rules as copy.ts: plain,
 * sentence case, no exclamation marks, no em or en dashes, no promises the system cannot
 * keep. Change wording with the designer.
 */

export const AUTH = {
  SIGN_IN_TITLE: "Sign in to Verina",
  SIGN_IN_LEDE:
    "Enter your work email. Verina emails you a sign-in link and a one-time code. There is no password.",
  EMAIL_LABEL: "Work email",
  EMAIL_BLANK: "Enter your email address.",
  EMAIL_INVALID: "Enter an email address in the format name@example.com.",
  SEND: "Email me a sign-in link",
  SENDING: "Sending",
  CHECK_HEADING: "Check your email",
  checkBody: (email: string) =>
    `If ${email} belongs to a Verina account, a sign-in email is on its way. Open the link on this device, or enter the code from the email.`,
  CODE_LABEL: "Code from the email",
  CODE_HINT: "6 to 10 digits. It works once and expires after a short time.",
  CODE_BLANK: "Enter the code from the email.",
  CODE_FORMAT: "Enter the code using digits only.",
  CODE_INVALID: "That code is not valid or has expired. Check the email, or request a new one.",
  VERIFY: "Sign in with code",
  VERIFYING: "Signing in",
  RESTART: "Use a different email",
  RATE_LIMITED: "Too many sign-in requests. Wait a minute, then try again.",
  UNAVAILABLE: "Verina cannot sign you in right now. Try again in a few minutes.",
  LINK_FAILED: "That sign-in link has expired or was already used. Request a new one below.",
  SIGNED_OUT: "You have signed out of Verina on this device.",
  NO_ACCOUNT_NOTE:
    "Verina accounts are created by your organization's administrator. You cannot create one here.",
  SIGNED_IN_HEADING: "You are signed in",
  SIGNED_IN_BODY: "Return to the tab you were working in to carry on. You can close this tab.",
  SIGN_OUT: "Sign out",
  DEV_NOTICE: "Development environment. Use invented examples only.",
} as const;

export const ACCOUNT = {
  NOT_LINKED_HEADING: "Your account isn't linked to an organization yet",
  NOT_LINKED_BODY: "Ask your organization's administrator.",
  NOT_LINKED_NOTE:
    "You signed in successfully. Verina shows nothing else until an administrator links your account.",
  TITLE: "Your account",
  LEDE: "What your organization's administrator has set up for you. Ask them to change it.",
  NAME: "Name",
  ORGANIZATION: "Organization",
  NO_ORGANIZATION: "None. You administer Verina for all organizations.",
  ROLES: "Roles",
  NO_ROLES: "No roles in an organization",
  ACCESS: "Administration",
  PLATFORM_ADMIN: "Platform administrator. You can create organizations and manage their members.",
  REJECTED_HEADING: "Your account is not set up for Verina",
  REJECTED_BODY:
    "You signed in, but this account cannot use Verina yet. Contact your Verina administrator.",
  UNAVAILABLE_HEADING: "Verina is not available right now",
  UNAVAILABLE_BODY: "This is a problem on our side. Try again in a few minutes.",
  TRY_AGAIN: "Try again",
} as const;

export const ROLES = ["partner", "lawyer", "requester", "knowledge", "tenant_admin"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_LABELS: Record<Role, string> = {
  partner: "Partner",
  lawyer: "Lawyer",
  requester: "Requester",
  knowledge: "Knowledge",
  tenant_admin: "Organization administrator",
};

export const ROLE_HELP: Record<Role, string> = {
  partner: "Signs off deliverables.",
  lawyer: "Opens matters and records conflict checks.",
  requester: "Submits requests and sees their status only.",
  knowledge: "Maintains playbooks and precedents.",
  tenant_admin: "Manages members and roles for this organization.",
};

export const NAV = {
  LABEL: "Workspace",
  ACCOUNT: "Account",
  MEMBERS: "Members",
  ADMIN: "Admin",
  INTAKE: "Intake",
} as const;

export const ADMIN = {
  TITLE: "Organizations",
  LEDE: "Create organizations, then add each organization's first administrator. Organizations manage their own members after that.",
  LIST_HEADING: "All organizations",
  EMPTY: "No organizations yet. Create the first one below.",
  COL_NAME: "Name",
  COL_SLUG: "Short name",
  COL_STATUS: "Status",
  COL_MEMBERS: "Members",
  ACTIVE: "Active",
  INACTIVE: "Deactivated",
  CREATE_HEADING: "Create an organization",
  NAME_LABEL: "Organization name",
  NAME_HINT: "As its members will recognise it. Up to 120 characters.",
  NAME_BLANK: "Enter the organization name.",
  NAME_LONG: "Keep the name to 120 characters or fewer.",
  NAME_HIDDEN: "Remove line breaks and hidden characters from the name.",
  SLUG_LABEL: "Short name",
  SLUG_HINT: "Lowercase letters and numbers, with single hyphens between them. 2 to 40 characters.",
  SLUG_BLANK: "Enter a short name.",
  SLUG_FORMAT: "Use 2 to 40 lowercase letters or numbers, with single hyphens between them.",
  SLUG_TAKEN: "Another organization already uses this short name. Choose a different one.",
  CREATE: "Create organization",
  CREATING: "Creating",
  created: (name: string) => `Organization created: ${name}.`,
  BACK: "All organizations",
  DETAILS: "Details",
  LOADING: "Loading organizations.",
  LOADING_ONE: "Loading organization.",
} as const;

export const MEMBERS = {
  TITLE: "Members",
  lede: (org: string) => `People who can sign in to Verina for ${org}, and what each of them can do.`,
  LIST_HEADING: "Current members",
  EMPTY: "No members yet. Add the first one below.",
  COL_NAME: "Name",
  COL_ROLES: "Roles",
  COL_STATUS: "Status",
  COL_ACTIONS: "Actions",
  ACTIVE: "Active",
  INACTIVE: "Deactivated",
  INVITE_PENDING: "Invitation not accepted yet",
  INVITE_ACCEPTED: "Has signed in",
  ADD_HEADING: "Add a member",
  ADD_LEDE: "Verina emails them an invitation to sign in. There is no password.",
  EMAIL_LABEL: "Email",
  EMAIL_BLANK: "Enter their email address.",
  EMAIL_INVALID: "Enter an email address in the format name@example.com.",
  EMAIL_TAKEN:
    "This email already has a Verina account. Each person can belong to one organization.",
  NAME_LABEL: "Display name",
  NAME_HINT: "Shown to colleagues and used to identify their work. Up to 120 characters.",
  NAME_BLANK: "Enter their display name.",
  NAME_LONG: "Keep the display name to 120 characters or fewer.",
  NAME_HIDDEN: "Remove line breaks and hidden characters from the display name.",
  ROLES_LEGEND: "Roles",
  ROLES_HINT: "Choose at least one.",
  ROLES_BLANK: "Choose at least one role.",
  ADD: "Add member",
  ADDING: "Adding",
  added: (name: string) => `Member added: ${name}. Invitation requested.`,
  EDIT_ROLES: "Change roles",
  rolesFor: (name: string) => `Roles for ${name}`,
  SAVE_ROLES: "Save roles",
  SAVING: "Saving",
  CANCEL: "Cancel",
  rolesSaved: (name: string) => `Roles saved for ${name}.`,
  DEACTIVATE: "Deactivate",
  REACTIVATE: "Reactivate",
  deactivateConfirm: (name: string) =>
    `Deactivate ${name}? They can no longer access this organization or its matters. Their past work stays attributed to them. You can reactivate them later.`,
  reactivateConfirm: (name: string) =>
    `Reactivate ${name}? They can sign in again with the roles shown.`,
  CONFIRM_DEACTIVATE: "Deactivate member",
  CONFIRM_REACTIVATE: "Reactivate member",
  deactivated: (name: string) => `${name} is deactivated.`,
  reactivated: (name: string) => `${name} is active again.`,
  RESEND: "Resend invitation",
  resent: (name: string) => `Invitation requested again for ${name}.`,
  LAST_ADMIN:
    "This is the last active organization administrator. Give another active member the Organization administrator role first.",
  LOADING: "Loading members.",
  YOU: "(you)",
} as const;

/** Request outcomes shared by the administration screens. */
export const REQUEST = {
  UNCONFIRMED_HEADING: "Not confirmed yet",
  UNCONFIRMED_BODY:
    "Verina could not confirm this change was saved. Your connection may have dropped. Retry sends the same request, so a saved directory change is not duplicated. An invitation email may be requested again.",
  RETRY: "Retry",
  UNAVAILABLE_HEADING: "Verina could not save this just now",
  UNAVAILABLE_BODY:
    "Try again in a few minutes. Retrying sends the same request, so a saved directory change is not duplicated. An invitation email may be requested again.",
  TRY_AGAIN: "Try again",
  SESSION_HEADING: "Your session has ended",
  SESSION_BODY:
    "Sign in again to finish saving. Your last change has not been confirmed. After you sign in, Verina sends the same request again, so a saved directory change is not duplicated. An invitation email may be requested again.",
  SESSION_READ_BODY: "Sign in again to keep working.",
  SIGN_IN_AGAIN: "Sign in again",
  NOT_AVAILABLE_HEADING: "This is not available",
  NOT_AVAILABLE_BODY:
    "It may not exist, or your account may not have access to it. Reload the page to see what you can manage.",
  NOT_SAVED_HEADING: "This change was not saved",
  INVALID_HEADING: "Verina did not accept these details",
  INVALID_BODY: "Nothing was saved. Check each field against its hint, then try again.",
  DEFECT_HEADING: "This request could not be completed",
  defectBody: (code: string) =>
    `Verina could not confirm the result. Reload the page and try again. If it happens again, tell your Verina administrator and quote code ${code}.`,
  LOAD_FAILED_HEADING: "Verina cannot load this right now",
  LOAD_FAILED_BODY: "This is a problem on our side. Try again in a few minutes.",
  SAVING: "Saving.",
} as const;
