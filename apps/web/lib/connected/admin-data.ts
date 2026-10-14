/**
 * Accounts contract v1 response shapes for organizations and members, parsed defensively.
 * Unexpected shapes are treated as "unavailable" by the caller, never guessed at.
 */

import { ROLES, type Role } from "./copy-accounts";

export type OrganizationSummary = {
  id: string;
  name: string;
  slug: string;
  active: boolean;
  memberCount: number | null;
};

export type Member = {
  actorId: string;
  displayName: string;
  email: string;
  roles: Role[];
  active: boolean;
  invitePending: boolean;
};

const isString = (value: unknown): value is string => typeof value === "string";

export function parseOrganization(value: unknown): OrganizationSummary | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (!isString(raw.id) || !isString(raw.name) || !isString(raw.slug) || typeof raw.active !== "boolean") {
    return null;
  }
  const count = raw.member_count;
  return {
    id: raw.id,
    name: raw.name,
    slug: raw.slug,
    active: raw.active,
    memberCount: typeof count === "number" && Number.isInteger(count) && count >= 0 ? count : null,
  };
}

export function parseOrganizations(json: unknown): OrganizationSummary[] | null {
  if (!json || typeof json !== "object") return null;
  const list = (json as { organizations?: unknown }).organizations;
  if (!Array.isArray(list)) return null;
  const parsed = list.map(parseOrganization);
  return parsed.every((item): item is OrganizationSummary => item !== null) ? parsed : null;
}

export function parseMember(value: unknown): Member | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (
    !isString(raw.actor_id) ||
    !isString(raw.display_name) ||
    !isString(raw.email) ||
    !Array.isArray(raw.roles) ||
    typeof raw.active !== "boolean" ||
    (raw.invite_status !== "pending" && raw.invite_status !== "accepted")
  ) {
    return null;
  }
  const roles = raw.roles as unknown[];
  return {
    actorId: raw.actor_id,
    displayName: raw.display_name,
    email: raw.email,
    roles: ROLES.filter((role) => roles.includes(role)),
    active: raw.active,
    invitePending: raw.invite_status === "pending",
  };
}

export function parseMembers(json: unknown): Member[] | null {
  if (!json || typeof json !== "object") return null;
  const list = (json as { members?: unknown }).members;
  if (!Array.isArray(list)) return null;
  const parsed = list.map(parseMember);
  return parsed.every((item): item is Member => item !== null) ? parsed : null;
}

export function organizationsPath() {
  return "/admin/organizations";
}

export function organizationPath(orgId: string) {
  return `/admin/organizations/${encodeURIComponent(orgId)}`;
}

export function membersPath(orgId: string) {
  return `/organizations/${encodeURIComponent(orgId)}/members`;
}

export function memberPath(orgId: string, actorId: string) {
  return `${membersPath(orgId)}/${encodeURIComponent(actorId)}`;
}
