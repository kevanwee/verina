import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrganizationsConsole } from "../../app/(connected)/admin/OrganizationsConsole";
import { MembersManager } from "../../app/(connected)/_components/MembersManager";
import { ADMIN, MEMBERS, REQUEST } from "@/lib/connected/copy-accounts";
import { classify, freeze, sendFrozen } from "@/lib/connected/request";
import { suggestSlug } from "@/lib/connected/validation";
import { fetchRouter, json } from "./fetch-router";

const ORGS = "/api/v1/admin/organizations";
const ORG_LIST = {
  organizations: [
    { id: "org-1", name: "Harbourline Legal LLP", slug: "harbourline", active: true, member_count: 3 },
    { id: "org-2", name: "Kestrel Counsel", slug: "kestrel", active: false, member_count: 1 },
  ],
};
const CREATED = { id: "org-3", name: "Marlow & Reyes", slug: "marlow-reyes", active: true };

afterEach(() => {
  vi.unstubAllGlobals();
});

function install(routes: Parameters<typeof fetchRouter>[0]) {
  const router = fetchRouter(routes);
  vi.stubGlobal("fetch", router.impl);
  return router;
}

describe("request library", () => {
  it("re-sends identical bytes and key on silent network retries", async () => {
    const router = fetchRouter({
      [`POST ${ORGS}`]: ["network-error", "network-error", json(CREATED, 201)],
    });
    const frozen = freeze("POST", "/admin/organizations", { name: "A", slug: "ab" });
    const sleep = vi.fn(async () => {});
    const outcome = await sendFrozen(frozen, { fetchImpl: router.impl, sleep });
    expect(outcome).toMatchObject({ kind: "ok", status: 201 });
    expect(sleep.mock.calls).toEqual([[1000], [3000]]);
    const posts = router.of("POST", ORGS);
    expect(posts).toHaveLength(3);
    expect(new Set(posts.map((call) => call.headers.get("idempotency-key"))).size).toBe(1);
    expect(new Set(posts.map((call) => call.body)).size).toBe(1);
    expect(posts[0].headers.get("idempotency-key")).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("gives up after two silent retries and reports the outcome as unconfirmed", async () => {
    const router = fetchRouter({ [`POST ${ORGS}`]: "network-error" });
    const outcome = await sendFrozen(freeze("POST", "/admin/organizations", {}), {
      fetchImpl: router.impl,
      sleep: async () => {},
    });
    expect(outcome).toEqual({ kind: "unconfirmed" });
    expect(router.calls).toHaveLength(3);
  });

  it("never retries an HTTP status silently", async () => {
    const router = fetchRouter({ [`POST ${ORGS}`]: json({ error: "upstream_unavailable" }, 502) });
    expect(await sendFrozen(freeze("POST", "/admin/organizations", {}), { fetchImpl: router.impl })).toEqual({
      kind: "unconfirmed",
    });
    expect(router.calls).toHaveLength(1);
  });

  it.each([
    [401, { kind: "session" }],
    [403, { kind: "forbidden" }],
    [404, { kind: "not_found" }],
    [409, { kind: "conflict", code: "slug_taken" }],
    [422, { kind: "invalid", code: "slug_taken" }],
    [503, { kind: "unavailable" }],
    [504, { kind: "unconfirmed" }],
    [428, { kind: "defect", code: "slug_taken" }],
    [500, { kind: "defect", code: "slug_taken" }],
  ])("classifies %i", (status, expected) => {
    expect(classify(status, { error: "slug_taken" })).toEqual(expected);
  });

  it("never reflects an unexpected error string into copy", () => {
    expect(classify(500, { error: "<script>alert(1)</script>" })).toEqual({ kind: "defect", code: "http_500" });
  });

  it("suggests a valid short name from an organization name", () => {
    expect(suggestSlug("Marlow & Reyes LLP")).toBe("marlow-reyes-llp");
    expect(suggestSlug("  Café Légal  ")).toBe("cafe-legal");
  });
});

describe("organizations console (US-53, platform admin)", () => {
  it("lists organizations with status in words", async () => {
    install({ [`GET ${ORGS}`]: json(ORG_LIST) });
    render(<OrganizationsConsole subject="tag-a" />);
    const link = await screen.findByRole("link", { name: "Harbourline Legal LLP" });
    expect(link).toHaveAttribute("href", "/admin/organizations/org-1");
    const row = link.closest("tr")!;
    expect(within(row).getByText(ADMIN.ACTIVE)).toBeVisible();
    expect(within(screen.getByText("Kestrel Counsel").closest("tr")!).getByText(ADMIN.INACTIVE)).toBeVisible();
  });

  it("validates inline, associates errors and focuses the first invalid field without sending", async () => {
    const user = userEvent.setup();
    const router = install({ [`GET ${ORGS}`]: json(ORG_LIST) });
    render(<OrganizationsConsole subject="tag-a" />);
    await user.click(screen.getByRole("button", { name: ADMIN.CREATE }));
    const name = screen.getByRole("textbox", { name: /Organization name/ });
    await waitFor(() => expect(name).toHaveFocus());
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription(`${ADMIN.NAME_HINT} ${ADMIN.NAME_BLANK}`);
    expect(screen.getByRole("textbox", { name: /Short name/ })).toHaveAccessibleDescription(
      `${ADMIN.SLUG_HINT} ${ADMIN.SLUG_BLANK}`,
    );
    expect(router.of("POST", ORGS)).toHaveLength(0);

    const slug = screen.getByRole("textbox", { name: /Short name/ });
    await user.type(slug, "Bad Slug");
    await user.tab();
    expect(slug).toHaveAccessibleDescription(`${ADMIN.SLUG_HINT} ${ADMIN.SLUG_FORMAT}`);
  });

  it("suggests the short name from the name until it is edited", async () => {
    const user = userEvent.setup();
    install({ [`GET ${ORGS}`]: json(ORG_LIST) });
    render(<OrganizationsConsole subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Organization name/ }), "Marlow & Reyes");
    expect(screen.getByRole("textbox", { name: /Short name/ })).toHaveValue("marlow-reyes");
  });

  it("keeps one Idempotency-Key per action and reuses it when the user retries", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${ORGS}`]: [json(ORG_LIST), json({ organizations: [...ORG_LIST.organizations, { ...CREATED, member_count: 0 }] })],
      [`POST ${ORGS}`]: [json({ error: "upstream_timeout" }, 504), json(CREATED, 201)],
    });
    render(<OrganizationsConsole subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Organization name/ }), "Marlow & Reyes");
    await user.click(screen.getByRole("button", { name: ADMIN.CREATE }));

    const heading = await screen.findByRole("heading", { name: REQUEST.UNCONFIRMED_HEADING });
    expect(heading).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent(REQUEST.UNCONFIRMED_BODY);
    // Inputs are read-only (still focusable), the action is aria-disabled, nothing new is listed.
    expect(screen.getByRole("textbox", { name: /Organization name/ })).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: ADMIN.CREATE })).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByText(CREATED.name)).toBeNull();

    // Activating Create again while unconfirmed sends nothing.
    await user.click(screen.getByRole("button", { name: ADMIN.CREATE }));
    expect(router.of("POST", ORGS)).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: REQUEST.RETRY }));
    await screen.findByRole("link", { name: CREATED.name });
    const posts = router.of("POST", ORGS);
    expect(posts).toHaveLength(2);
    expect(posts[1].headers.get("idempotency-key")).toBe(posts[0].headers.get("idempotency-key"));
    expect(posts[1].body).toBe(posts[0].body);
    expect(JSON.parse(posts[0].body!)).toEqual({ name: "Marlow & Reyes", slug: "marlow-reyes" });
    expect(screen.getByRole("status")).toHaveTextContent(ADMIN.created(CREATED.name));
    expect(screen.getByRole("textbox", { name: /Organization name/ })).toHaveValue("");
  });

  it("shows slug_taken on the short name, discards the key and uses a new one next time", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${ORGS}`]: json(ORG_LIST),
      [`POST ${ORGS}`]: [json({ error: "slug_taken" }, 409), json(CREATED, 201)],
    });
    render(<OrganizationsConsole subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Organization name/ }), "Harbourline");
    await user.click(screen.getByRole("button", { name: ADMIN.CREATE }));
    const slug = screen.getByRole("textbox", { name: /Short name/ });
    await waitFor(() => expect(slug).toHaveFocus());
    expect(slug).toHaveAccessibleDescription(`${ADMIN.SLUG_HINT} ${ADMIN.SLUG_TAKEN}`);
    expect(screen.queryByRole("alert")).toBeNull();

    await user.clear(slug);
    await user.type(slug, "harbourline-2");
    await user.click(screen.getByRole("button", { name: ADMIN.CREATE }));
    await screen.findByText(ADMIN.created(CREATED.name));
    const [first, second] = router.of("POST", ORGS);
    expect(second.headers.get("idempotency-key")).not.toBe(first.headers.get("idempotency-key"));
  });

  it.each([
    [404, REQUEST.NOT_AVAILABLE_HEADING],
    [422, REQUEST.INVALID_HEADING],
    [503, REQUEST.UNAVAILABLE_HEADING],
    [500, REQUEST.DEFECT_HEADING],
  ])("explains a %i in plain words and focuses it", async (status, heading) => {
    const user = userEvent.setup();
    install({
      [`GET ${ORGS}`]: json(ORG_LIST),
      [`POST ${ORGS}`]: json({ error: status === 500 ? "internal_error" : "x" }, status),
    });
    render(<OrganizationsConsole subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Organization name/ }), "Marlow");
    await user.click(screen.getByRole("button", { name: ADMIN.CREATE }));
    expect(await screen.findByRole("heading", { name: heading })).toHaveFocus();
    if (status === 500) expect(screen.getByRole("alert")).toHaveTextContent("internal_error");
  });

  it("asks the user to sign in again on 401, then re-sends the same request", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${ORGS}`]: json(ORG_LIST),
      [`POST ${ORGS}`]: [json({ error: "unauthenticated" }, 401), json(CREATED, 201)],
      "GET /auth/session": json({ signedIn: true, subject: "tag-a" }),
    });
    const popup = {} as Window;
    const open = vi.fn(() => popup);
    vi.stubGlobal("open", open);
    render(<OrganizationsConsole subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Organization name/ }), "Marlow");
    await user.click(screen.getByRole("button", { name: ADMIN.CREATE }));
    expect(await screen.findByRole("heading", { name: REQUEST.SESSION_HEADING })).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent(REQUEST.SESSION_BODY);

    await user.click(screen.getByRole("button", { name: REQUEST.SIGN_IN_AGAIN }));
    expect(open).toHaveBeenCalledWith("/sign-in?returnTo=%2Fauth%2Fsigned-in", "verina-sign-in");
    // The sign-in window reports success.
    const channel = new BroadcastChannel("verina-auth");
    channel.postMessage({ type: "signed-in" });
    channel.close();

    await waitFor(() => expect(router.of("POST", ORGS)).toHaveLength(2));
    const [first, second] = router.of("POST", ORGS);
    expect(second.headers.get("idempotency-key")).toBe(first.headers.get("idempotency-key"));
    await screen.findByText(ADMIN.created(CREATED.name));
  });

  it("explains a failed load with a retry", async () => {
    const user = userEvent.setup();
    install({ [`GET ${ORGS}`]: [json({ error: "unavailable" }, 503), json(ORG_LIST)] });
    render(<OrganizationsConsole subject="tag-a" />);
    expect(await screen.findByRole("heading", { name: REQUEST.LOAD_FAILED_HEADING })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: REQUEST.TRY_AGAIN }));
    await screen.findByRole("link", { name: "Harbourline Legal LLP" });
  });
});

const MEMBERS_URL = "/api/v1/organizations/org-1/members";
const member = (overrides: Record<string, unknown>) => ({
  actor_id: "act-1",
  display_name: "Avery Tan",
  email: "avery.tan@example.com",
  roles: ["lawyer", "tenant_admin"],
  active: true,
  invite_status: "accepted",
  ...overrides,
});
const MEMBER_LIST = {
  members: [
    member({}),
    member({
      actor_id: "act-2",
      display_name: "Jordan Lee",
      email: "jordan.lee@example.com",
      roles: ["requester"],
      invite_status: "pending",
    }),
  ],
};

describe("members manager (US-53)", () => {
  it("lists members with roles, status and invitation state", async () => {
    install({ [`GET ${MEMBERS_URL}`]: json(MEMBER_LIST) });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    const self = (await screen.findByText(/Avery Tan/)).closest("tr")!;
    expect(self).toHaveTextContent(MEMBERS.YOU);
    expect(self).toHaveTextContent("Lawyer, Organization administrator");
    expect(self).toHaveTextContent(MEMBERS.INVITE_ACCEPTED);
    const pending = screen.getByText(/Jordan Lee/).closest("tr")!;
    expect(pending).toHaveTextContent(MEMBERS.INVITE_PENDING);
    expect(within(pending).getByRole("button", { name: `${MEMBERS.RESEND}: Jordan Lee` })).toBeVisible();
    expect(within(self).queryByRole("button", { name: /Resend/ })).toBeNull();
  });

  it("validates the add form and focuses the first error", async () => {
    const user = userEvent.setup();
    const router = install({ [`GET ${MEMBERS_URL}`]: json(MEMBER_LIST) });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    await screen.findByText(/Avery Tan/);
    await user.click(screen.getByRole("button", { name: MEMBERS.ADD }));
    const email = screen.getByRole("textbox", { name: /Email/ });
    await waitFor(() => expect(email).toHaveFocus());
    expect(email).toHaveAccessibleDescription(MEMBERS.EMAIL_BLANK);
    expect(screen.getByRole("textbox", { name: /Display name/ })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("group", { name: /^Roles/ })).toHaveAccessibleDescription(
      `${MEMBERS.ROLES_HINT} ${MEMBERS.ROLES_BLANK}`,
    );
    expect(router.of("POST", MEMBERS_URL)).toHaveLength(0);
  });

  it("adds a member, showing them only after the server confirms", async () => {
    const user = userEvent.setup();
    const added = member({ actor_id: "act-3", display_name: "Sam Ortiz", email: "sam.ortiz@example.com", roles: ["lawyer"], invite_status: "pending" });
    const router = install({
      [`GET ${MEMBERS_URL}`]: [json(MEMBER_LIST), json({ members: [...MEMBER_LIST.members, added] })],
      [`POST ${MEMBERS_URL}`]: json(added, 201),
    });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    await screen.findByText(/Avery Tan/);
    await user.type(screen.getByRole("textbox", { name: /Email/ }), "sam.ortiz@example.com");
    await user.type(screen.getByRole("textbox", { name: /Display name/ }), "Sam Ortiz");
    await user.click(screen.getByRole("checkbox", { name: "Lawyer" }));
    await user.click(screen.getByRole("button", { name: MEMBERS.ADD }));
    await screen.findByText(MEMBERS.added("Sam Ortiz"));
    expect(await screen.findByText(/sam\.ortiz@example\.com/)).toBeVisible();
    const [post] = router.of("POST", MEMBERS_URL);
    expect(JSON.parse(post.body!)).toEqual({
      email: "sam.ortiz@example.com",
      display_name: "Sam Ortiz",
      roles: ["lawyer"],
    });
    expect(post.headers.get("idempotency-key")).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("shows account_exists on the email field", async () => {
    const user = userEvent.setup();
    install({
      [`GET ${MEMBERS_URL}`]: json(MEMBER_LIST),
      [`POST ${MEMBERS_URL}`]: json({ error: "account_exists" }, 409),
    });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    await screen.findByText(/Avery Tan/);
    await user.type(screen.getByRole("textbox", { name: /Email/ }), "taken@example.com");
    await user.type(screen.getByRole("textbox", { name: /Display name/ }), "Taken Person");
    await user.click(screen.getByRole("checkbox", { name: "Requester" }));
    await user.click(screen.getByRole("button", { name: MEMBERS.ADD }));
    const email = screen.getByRole("textbox", { name: /Email/ });
    await waitFor(() => expect(email).toHaveFocus());
    expect(email).toHaveAccessibleDescription(MEMBERS.EMAIL_TAKEN);
  });

  it("explains last_admin when removing the last administrator role", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${MEMBERS_URL}`]: json(MEMBER_LIST),
      [`PATCH ${MEMBERS_URL}/act-1`]: json({ error: "last_admin" }, 409),
    });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    await screen.findByText(/Avery Tan/);
    await user.click(screen.getByRole("button", { name: `${MEMBERS.EDIT_ROLES}: Avery Tan` }));
    const group = screen.getByRole("group", { name: /Roles for Avery Tan/ });
    await waitFor(() => expect(within(group).getByRole("checkbox", { name: "Partner" })).toHaveFocus());

    // No role at all is refused on the client.
    await user.click(within(group).getByRole("checkbox", { name: "Lawyer" }));
    await user.click(within(group).getByRole("checkbox", { name: "Organization administrator" }));
    await user.click(screen.getByRole("button", { name: MEMBERS.SAVE_ROLES }));
    expect(group).toHaveAccessibleDescription(`${MEMBERS.ROLES_HINT} ${MEMBERS.ROLES_BLANK}`);
    expect(router.of("PATCH", `${MEMBERS_URL}/act-1`)).toHaveLength(0);

    await user.click(within(group).getByRole("checkbox", { name: "Lawyer" }));
    await user.click(screen.getByRole("button", { name: MEMBERS.SAVE_ROLES }));
    expect(await screen.findByRole("heading", { name: REQUEST.NOT_SAVED_HEADING })).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent(MEMBERS.LAST_ADMIN);
    const [patch] = router.of("PATCH", `${MEMBERS_URL}/act-1`);
    expect(JSON.parse(patch.body!)).toEqual({ roles: ["lawyer"] });
    expect(patch.headers.get("idempotency-key")).toBeTruthy();
  });

  it("confirms before deactivating, then returns focus to the row", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${MEMBERS_URL}`]: [
        json(MEMBER_LIST),
        json({ members: [MEMBER_LIST.members[0], { ...MEMBER_LIST.members[1], active: false }] }),
      ],
      [`PATCH ${MEMBERS_URL}/act-2`]: json({ ...MEMBER_LIST.members[1], active: false }),
    });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    await screen.findByText(/Jordan Lee/);
    await user.click(screen.getByRole("button", { name: `${MEMBERS.DEACTIVATE}: Jordan Lee` }));
    const confirmText = screen.getByText(MEMBERS.deactivateConfirm("Jordan Lee"));
    await waitFor(() => expect(confirmText).toHaveFocus());
    expect(router.of("PATCH", `${MEMBERS_URL}/act-2`)).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: MEMBERS.CONFIRM_DEACTIVATE }));
    await screen.findByText(MEMBERS.deactivated("Jordan Lee"));
    const reactivate = await screen.findByRole("button", { name: `${MEMBERS.REACTIVATE}: Jordan Lee` });
    await waitFor(() => expect(reactivate).toHaveFocus());
    expect(JSON.parse(router.of("PATCH", `${MEMBERS_URL}/act-2`)[0].body!)).toEqual({ active: false });
  });

  it("resends an invitation", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${MEMBERS_URL}`]: json(MEMBER_LIST),
      [`POST ${MEMBERS_URL}/act-2/resend-invite`]: new Response(null, { status: 202 }),
    });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    await user.click(await screen.findByRole("button", { name: `${MEMBERS.RESEND}: Jordan Lee` }));
    await screen.findByText(MEMBERS.resent("Jordan Lee"));
    expect(router.of("POST", `${MEMBERS_URL}/act-2/resend-invite`)[0].headers.get("idempotency-key")).toBeTruthy();
  });

  it("answers an unauthorised or missing organization with one plain message", async () => {
    install({ [`GET ${MEMBERS_URL}`]: json({ error: "not_found" }, 404) });
    render(<MembersManager orgId="org-1" subject="tag-a" selfActorId="act-1" />);
    expect(await screen.findByRole("heading", { name: REQUEST.NOT_AVAILABLE_HEADING })).toHaveFocus();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
