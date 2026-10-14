import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionState } from "@/lib/connected/auth/provider";
import { readConnectedConfig, type ConnectedConfig } from "@/lib/connected/config";
import { ACCOUNT, NAV } from "@/lib/connected/copy-accounts";
import { navFor, parseMe, type LinkedMe } from "@/lib/connected/me";

const session = vi.fn<() => Promise<SessionState>>();
vi.mock("@/lib/connected/auth/server", () => ({ getSession: () => session() }));

const { resolveViewer, requireLinked } = await import("@/lib/connected/viewer");
const { AccountDetails } = await import("../../app/(connected)/_components/AccountDetails");
const { NotLinked } = await import("../../app/(connected)/_components/NotLinked");
const { ConnectedFrame } = await import("../../app/(connected)/_components/ConnectedFrame");

const CONFIG = readConnectedConfig({
  VERINA_CONNECTED: "1",
  NEXT_PUBLIC_SUPABASE_URL: "https://example-project.supabase.co",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "sb_publishable_synthetic_key_for_tests_only",
  VERINA_API_BASE_URL: "http://127.0.0.1:8000",
}) as ConnectedConfig;

const LINKED_BODY = {
  linked: true,
  actor_id: "act-1",
  display_name: "Avery Tan",
  organization: { id: "org-1", name: "Harbourline Legal LLP", slug: "harbourline" },
  roles: ["lawyer", "tenant_admin"],
  platform_admin: false,
};

const LAWYER: LinkedMe = parseMe(LINKED_BODY) as LinkedMe;

function meFetch(status: number, body: unknown) {
  return vi.fn(async () => Response.json(body, { status }));
}

describe("GET /v1/me parsing", () => {
  it("parses a linked member", () => {
    expect(LAWYER).toEqual({
      linked: true,
      actorId: "act-1",
      displayName: "Avery Tan",
      organization: { id: "org-1", name: "Harbourline Legal LLP", slug: "harbourline" },
      roles: ["lawyer", "tenant_admin"],
      platformAdmin: false,
    });
  });

  it("parses a platform admin without an organization", () => {
    expect(
      parseMe({ ...LINKED_BODY, organization: null, roles: [], platform_admin: true }),
    ).toMatchObject({ organization: null, roles: [], platformAdmin: true });
  });

  it("treats linked:false as unlinked whatever else is present", () => {
    expect(parseMe({ linked: false, display_name: "should be ignored" })).toEqual({ linked: false });
  });

  it("drops unknown roles and refuses malformed bodies", () => {
    expect(parseMe({ ...LINKED_BODY, roles: ["lawyer", "superuser"] })).toMatchObject({ roles: ["lawyer"] });
    expect(parseMe(null)).toBeNull();
    expect(parseMe({})).toBeNull();
    expect(parseMe({ ...LINKED_BODY, platform_admin: "yes" })).toBeNull();
    expect(parseMe({ ...LINKED_BODY, organization: { id: 1 } })).toBeNull();
    expect(parseMe({ ...LINKED_BODY, roles: "lawyer" })).toBeNull();
  });
});

describe("viewer resolution", () => {
  afterEach(() => vi.restoreAllMocks());

  it("calls /v1/me with the bearer token and routes linked and unlinked accounts", async () => {
    const linked = meFetch(200, LINKED_BODY);
    expect(await resolveViewer(CONFIG, "token-a", linked)).toEqual({ kind: "linked", me: LAWYER });
    const [url, init] = linked.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8000/v1/me");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer token-a");

    expect(await resolveViewer(CONFIG, "token-a", meFetch(200, { linked: false }))).toEqual({ kind: "unlinked" });
  });

  it("distinguishes a refused token from an outage", async () => {
    expect(await resolveViewer(CONFIG, "t", meFetch(401, { error: "unauthenticated" }))).toEqual({ kind: "rejected" });
    expect(await resolveViewer(CONFIG, "t", meFetch(503, { error: "unavailable" }))).toEqual({ kind: "unavailable" });
    expect(await resolveViewer(CONFIG, "t", meFetch(200, { linked: "maybe" }))).toEqual({ kind: "unavailable" });
    const offline = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    expect(await resolveViewer(CONFIG, "t", offline)).toEqual({ kind: "unavailable" });
  });

  it("does not call the API without a session", async () => {
    const fetchImpl = meFetch(200, LINKED_BODY);
    expect(await resolveViewer(CONFIG, null, fetchImpl)).toEqual({ kind: "signed_out" });
    expect(await resolveViewer(CONFIG, "unavailable", fetchImpl)).toEqual({ kind: "unavailable" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("routing after sign-in", () => {
  beforeEach(() => {
    session.mockResolvedValue({ state: "signed_in", subject: "iss|sub", accessToken: "token-a" });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function redirectOf(promise: Promise<unknown>) {
    try {
      await promise;
    } catch (error) {
      return String((error as { digest?: string }).digest);
    }
    return null;
  }

  it("sends an unlinked account to the neutral not-linked page", async () => {
    vi.stubGlobal("fetch", meFetch(200, { linked: false }));
    expect(await redirectOf(requireLinked(CONFIG, "/account"))).toContain("/not-linked");
  });

  it("sends a signed-out visitor to sign-in with returnTo", async () => {
    session.mockResolvedValue({ state: "signed_out" });
    expect(await redirectOf(requireLinked(CONFIG, "/settings/members"))).toContain(
      "/sign-in?returnTo=%2Fsettings%2Fmembers",
    );
  });

  it("lets a linked account through", async () => {
    vi.stubGlobal("fetch", meFetch(200, LINKED_BODY));
    await expect(requireLinked(CONFIG, "/account")).resolves.toEqual({ kind: "linked", me: LAWYER });
  });
});

describe("account surfaces", () => {
  it("shows name, organization and roles (US-52)", () => {
    render(<AccountDetails me={LAWYER} />);
    expect(screen.getByRole("heading", { level: 1, name: ACCOUNT.TITLE })).toBeVisible();
    expect(screen.getByText("Avery Tan")).toBeVisible();
    expect(screen.getByText("Harbourline Legal LLP")).toBeVisible();
    expect(screen.getByText("Lawyer")).toBeVisible();
    expect(screen.getByText("Organization administrator")).toBeVisible();
    expect(screen.queryByText(ACCOUNT.PLATFORM_ADMIN)).toBeNull();
  });

  it("explains a platform admin without an organization", () => {
    render(<AccountDetails me={{ ...LAWYER, organization: null, roles: [], platformAdmin: true }} />);
    expect(screen.getByText(ACCOUNT.NO_ORGANIZATION)).toBeVisible();
    expect(screen.getByText(ACCOUNT.NO_ROLES)).toBeVisible();
    expect(screen.getByText(ACCOUNT.PLATFORM_ADMIN)).toBeVisible();
  });

  it("shows the not-linked page with sign-out and no data", () => {
    const { container } = render(<NotLinked />);
    expect(
      screen.getByRole("heading", { name: "Your account isn't linked to an organization yet" }),
    ).toBeVisible();
    expect(screen.getByText("Ask your organization's administrator.")).toBeVisible();
    const form = container.querySelector("form")!;
    expect(form).toHaveAttribute("method", "post");
    expect(form).toHaveAttribute("action", "/sign-out");
    expect(within(form).getByRole("button", { name: "Sign out" })).toBeVisible();
    expect(container.querySelectorAll("dl, table, a")).toHaveLength(0);
  });
});

describe("navigation from /v1/me", () => {
  it("shows Members only to an organization administrator and Admin only to a platform admin", () => {
    const labels = (me: LinkedMe) => navFor(me, "/account").map((entry) => entry.label);
    expect(labels(LAWYER)).toEqual([NAV.MEMBERS, NAV.ACCOUNT]);
    expect(labels({ ...LAWYER, roles: ["lawyer"] })).toEqual([NAV.ACCOUNT]);
    expect(labels({ ...LAWYER, roles: ["lawyer"], platformAdmin: true })).toEqual([NAV.ADMIN, NAV.ACCOUNT]);
    // tenant_admin without an organization cannot manage members.
    expect(labels({ ...LAWYER, organization: null })).toEqual([NAV.ACCOUNT]);
  });

  it("marks the current page", () => {
    render(
      <ConnectedFrame nav={navFor({ ...LAWYER, platformAdmin: true }, "/admin/organizations/org-1")} signedIn>
        <p>content</p>
      </ConnectedFrame>,
    );
    const nav = screen.getByRole("navigation", { name: NAV.LABEL });
    expect(within(nav).getByRole("link", { name: NAV.ADMIN })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: NAV.ACCOUNT })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("button", { name: "Sign out" })).toBeVisible();
  });
});
