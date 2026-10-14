/**
 * GET /v1/me (accounts contract v1), parsed defensively: an unexpected shape is treated as
 * "unavailable", never as a grant. Navigation derived from it is a convenience only; the API
 * enforces every route.
 */

import { NAV, ROLES, type Role } from "./copy-accounts";
import { PATHS } from "./routes";

export type Organization = { id: string; name: string; slug: string };

export type LinkedMe = {
  linked: true;
  actorId: string;
  displayName: string;
  organization: Organization | null;
  roles: Role[];
  platformAdmin: boolean;
};

export type Me = { linked: false } | LinkedMe;

const isString = (value: unknown): value is string => typeof value === "string";

function parseOrganization(value: unknown): Organization | null | undefined {
  if (value === null) return null;
  if (!value || typeof value !== "object") return undefined;
  const { id, name, slug } = value as Record<string, unknown>;
  if (!isString(id) || !isString(name) || !isString(slug)) return undefined;
  return { id, name, slug };
}

export function parseMe(json: unknown): Me | null {
  if (!json || typeof json !== "object") return null;
  const body = json as Record<string, unknown>;
  if (body.linked === false) return { linked: false };
  if (body.linked !== true) return null;
  const organization = parseOrganization(body.organization);
  if (organization === undefined) return null;
  if (!isString(body.actor_id) || !isString(body.display_name)) return null;
  if (!Array.isArray(body.roles) || typeof body.platform_admin !== "boolean") return null;
  return {
    linked: true,
    actorId: body.actor_id,
    displayName: body.display_name,
    organization,
    // Unknown role names are ignored rather than shown or trusted.
    roles: ROLES.filter((role) => (body.roles as unknown[]).includes(role)),
    platformAdmin: body.platform_admin,
  };
}

export function canManageMembers(me: LinkedMe) {
  return me.organization !== null && me.roles.includes("tenant_admin");
}

export type NavEntry = { href: string; label: string; current: boolean };

export function navFor(me: LinkedMe, currentPath: string): NavEntry[] {
  const entries: { href: string; label: string; show: boolean; match: (path: string) => boolean }[] = [
    {
      href: PATHS.members,
      label: NAV.MEMBERS,
      show: canManageMembers(me),
      match: (path) => path === PATHS.members,
    },
    {
      href: PATHS.admin,
      label: NAV.ADMIN,
      show: me.platformAdmin,
      match: (path) => path === PATHS.admin || path.startsWith(`${PATHS.admin}/`),
    },
    {
      href: PATHS.account,
      label: NAV.ACCOUNT,
      show: true,
      match: (path) => path === PATHS.account,
    },
  ];
  return entries
    .filter((entry) => entry.show)
    .map(({ href, label, match }) => ({ href, label, current: match(currentPath) }));
}
