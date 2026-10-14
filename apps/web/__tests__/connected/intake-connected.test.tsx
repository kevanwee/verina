import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectedIntake } from "../../app/(connected)/intake-connected/ConnectedIntake";
import { SessionPanel } from "../../app/(connected)/intake-connected/SessionPanel";
import { C, TITLES } from "@/lib/connected/copy";
import { parseMatter } from "@/lib/connected/matter";
import { fetchRouter, json } from "./fetch-router";

const MATTERS = "/api/v1/matters";
const M1 = `${MATTERS}/mtr-1`;
const lawyerView = (overrides: Record<string, unknown> = {}) => ({
  matter_id: "mtr-1",
  revision: 1,
  title: "Synthetic supply agreement",
  conflict_status: "pending",
  status: "awaiting_clearance",
  ...overrides,
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function install(routes: Parameters<typeof fetchRouter>[0]) {
  const router = fetchRouter(routes);
  vi.stubGlobal("fetch", router.impl);
  return router;
}

const live = () => document.querySelector('[role="status"][aria-live="polite"]');

describe("matter projections", () => {
  it("chooses the view from the response: revision means lawyer, none means requester", () => {
    expect(parseMatter(lawyerView())).toMatchObject({ kind: "lawyer", revision: 1 });
    expect(parseMatter({ matter_id: "mtr-1", status: "ready" })).toEqual({
      kind: "requester",
      matterId: "mtr-1",
      status: "ready",
    });
    expect(parseMatter({ ...lawyerView(), conflict_status: "maybe" })).toBeNull();
    expect(parseMatter({ ...lawyerView(), matter_id: "../x" })).toBeNull();
  });
});

describe("signed out and not set up", () => {
  it("replaces the intake with a sign-in panel that sends no matter request", () => {
    const router = install({});
    render(<SessionPanel kind="signed_out" returnTo="/workbench/intake/mtr-1" />);
    const heading = screen.getByRole("heading", { name: C.C01_HEADING });
    expect(heading).toHaveFocus();
    expect(screen.getByText(C.C02_BODY)).toBeVisible();
    expect(screen.getByRole("link", { name: C.C02_BUTTON })).toHaveAttribute(
      "href",
      "/sign-in?returnTo=%2Fworkbench%2Fintake%2Fmtr-1",
    );
    expect(document.title).toBe(TITLES.signIn);
    expect(router.calls).toHaveLength(0);
  });

  it("explains an account that is not set up", () => {
    render(<SessionPanel kind="not_set_up" returnTo="/workbench/intake" />);
    expect(screen.getByRole("heading", { name: C.C09_HEADING })).toHaveFocus();
    expect(screen.getByText(C.C09_BODY)).toBeVisible();
  });
});

describe("new matter", () => {
  it("validates the title like the API and sends nothing until it passes", async () => {
    const user = userEvent.setup();
    const router = install({});
    render(<ConnectedIntake matterId={null} subject="tag-a" />);
    expect(document.title).toBe(TITLES.newMatter);
    const field = screen.getByRole("textbox", { name: /Matter title/ });

    await user.click(screen.getByRole("button", { name: "Open matter" }));
    await waitFor(() => expect(field).toHaveFocus());
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(`${C.C11_HINT} ${C.C13_BLANK}`);

    await user.type(field, "Acme​supply");
    await user.click(screen.getByRole("button", { name: "Open matter" }));
    expect(field).toHaveAccessibleDescription(`${C.C11_HINT} ${C.C13_HIDDEN}`);

    await user.clear(field);
    fireEvent.change(field, { target: { value: "x".repeat(201) } });
    expect(screen.getByText(C.c12(0))).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Open matter" }));
    expect(field).toHaveAccessibleDescription(`${C.C11_HINT} ${C.c12(0)} ${C.C13_LONG}`);
    expect(router.calls).toHaveLength(0);
  });

  it("shows the counter only near the limit", async () => {
    install({});
    render(<ConnectedIntake matterId={null} subject="tag-a" />);
    const field = screen.getByRole("textbox", { name: /Matter title/ });
    fireEvent.change(field, { target: { value: "x".repeat(179) } });
    expect(screen.queryByText(/characters left/)).toBeNull();
    fireEvent.change(field, { target: { value: "x".repeat(185) } });
    expect(screen.getByText(C.c12(15))).toBeVisible();
  });

  it("opens the matter only after the server confirms, replacing the URL and focusing the reference", async () => {
    const user = userEvent.setup();
    const replace = vi.spyOn(window.history, "replaceState");
    const router = install({
      [`POST ${MATTERS}`]: json({ matter_id: "mtr-1", revision: 1 }, 201, { etag: '"1"' }),
      [`GET ${M1}`]: json(lawyerView()),
    });
    render(<ConnectedIntake matterId={null} subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Matter title/ }), "  Synthetic supply agreement  ");
    await user.click(screen.getByRole("button", { name: "Open matter" }));

    const reference = await screen.findByRole("heading", { name: "Matter reference mtr-1" });
    await waitFor(() => expect(reference).toHaveFocus());
    expect(replace).toHaveBeenCalledWith(null, "", "/workbench/intake/mtr-1");
    expect(live()).toHaveTextContent(C.c21("mtr-1", 1));
    expect(document.title).toBe(TITLES.matter("mtr-1"));
    expect(screen.getByText("Synthetic supply agreement")).toBeVisible();
    expect(screen.getByText(C.C27_PENDING)).toBeVisible();
    expect(screen.getByText(C.c26(1))).toBeVisible();
    expect(screen.getByText(C.C14)).toBeVisible();
    const [post] = router.of("POST", MATTERS);
    expect(JSON.parse(post.body!)).toEqual({ title: "Synthetic supply agreement" });
    expect(post.headers.get("if-match")).toBeNull();
    // Nothing about the matter is written to storage or the URL beyond the id.
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("retries an unconfirmed create with the same key and body", async () => {
    const user = userEvent.setup();
    const router = install({
      [`POST ${MATTERS}`]: [json({ error: "upstream_timeout" }, 504), json({ matter_id: "mtr-1", revision: 1 }, 201)],
      [`GET ${M1}`]: json(lawyerView()),
    });
    render(<ConnectedIntake matterId={null} subject="tag-a" />);
    const field = screen.getByRole("textbox", { name: /Matter title/ });
    await user.type(field, "Synthetic supply agreement");
    await user.click(screen.getByRole("button", { name: "Open matter" }));

    expect(await screen.findByRole("heading", { name: C.C30_HEADING })).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent(C.C31_BODY);
    expect(field).toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: "Open matter" })).toHaveAttribute("aria-disabled", "true");

    await user.click(screen.getByRole("button", { name: C.RETRY }));
    await screen.findByRole("heading", { name: "Matter reference mtr-1" });
    const [first, second] = router.of("POST", MATTERS);
    expect(second.headers.get("idempotency-key")).toBe(first.headers.get("idempotency-key"));
    expect(second.body).toBe(first.body);
  });

  it("explains 403, 401 and 503 on create", async () => {
    const user = userEvent.setup();
    install({ [`POST ${MATTERS}`]: json({ error: "forbidden" }, 403) });
    const { unmount } = render(<ConnectedIntake matterId={null} subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Matter title/ }), "Synthetic");
    await user.click(screen.getByRole("button", { name: "Open matter" }));
    const forbidden = await screen.findByText(C.C10);
    await waitFor(() => expect(forbidden).toHaveFocus());
    unmount();

    install({ [`POST ${MATTERS}`]: json({ error: "unauthenticated" }, 401) });
    const second = render(<ConnectedIntake matterId={null} subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Matter title/ }), "Synthetic");
    await user.click(screen.getByRole("button", { name: "Open matter" }));
    expect(await screen.findByRole("heading", { name: C.C05_HEADING })).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent(C.C07_BODY);
    expect(screen.getByRole("button", { name: C.C06_BUTTON })).toBeVisible();
    second.unmount();

    install({ [`POST ${MATTERS}`]: json({ error: "unavailable" }, 503) });
    render(<ConnectedIntake matterId={null} subject="tag-a" />);
    await user.type(screen.getByRole("textbox", { name: /Matter title/ }), "Synthetic");
    await user.click(screen.getByRole("button", { name: "Open matter" }));
    expect(await screen.findByRole("heading", { name: C.C61_HEADING })).toHaveFocus();
  });

  it("warns before the page unloads with a typed title", async () => {
    const user = userEvent.setup();
    install({});
    render(<ConnectedIntake matterId={null} subject="tag-a" />);
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    await user.type(screen.getByRole("textbox", { name: /Matter title/ }), "Draft");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });
});

describe("resumed matter (lawyer projection)", () => {
  it("records a conflict result with If-Match and shows it only once confirmed", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${M1}`]: [json(lawyerView()), json(lawyerView({ revision: 2, conflict_status: "clear", status: "ready" }))],
      [`POST ${M1}/conflict-checks`]: json({ matter_id: "mtr-1", revision: 2, conflict_status: "clear" }),
    });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    await screen.findByText(C.C27_PENDING);
    const panel = screen.getByRole("region", { name: "Conflict check" });
    await user.click(within(panel).getByRole("radio", { name: "Clear" }));
    await user.click(within(panel).getByRole("button", { name: "Record result" }));

    await screen.findByText(C.C27_OPEN);
    expect(screen.getByRole("heading", { name: "Conflict check" })).toHaveFocus();
    expect(live()).toHaveTextContent(C.c23(2));
    expect(screen.getByText(C.c26(2))).toBeVisible();
    const [post] = router.of("POST", `${M1}/conflict-checks`);
    expect(JSON.parse(post.body!)).toEqual({ result: "CLEAR" });
    expect(post.headers.get("if-match")).toBe('"1"');
    expect(post.headers.get("idempotency-key")).toMatch(/^[0-9a-f-]{36}$/);
    // Clear collapses the options behind "Change the result".
    expect(within(panel).getByRole("button", { name: "Change the result" })).toBeVisible();
  });

  it("requires a choice and a valid waiver reason, then never shows the reason again", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${M1}`]: [
        json(lawyerView({ revision: 2, conflict_status: "conflict" })),
        json(lawyerView({ revision: 3, conflict_status: "waived", status: "ready" })),
      ],
      [`POST ${M1}/conflict-waivers`]: json({ matter_id: "mtr-1", revision: 3, conflict_status: "waived" }),
    });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    await screen.findByText(C.C27_CONFLICT);
    const panel = screen.getByRole("region", { name: "Conflict check" });

    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    const waive = within(panel).getByRole("radio", { name: "Waive the conflict" });
    await waitFor(() => expect(waive).toHaveFocus());
    expect(within(panel).getByText("Choose a result to record.")).toBeVisible();

    await user.click(waive);
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    const reason = within(panel).getByRole("textbox", { name: /Reason for waiver/ });
    await waitFor(() => expect(reason).toHaveFocus());
    expect(reason).toHaveAccessibleDescription(`${C.C16_HINT} ${C.C16_BLANK}`);

    await user.type(reason, "Parent dispute closed; no overlap with this synthetic contract.");
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    await screen.findByText(C.C27_OPEN);
    expect(live()).toHaveTextContent(C.c25(3));
    expect(screen.queryByText(/Parent dispute closed/)).toBeNull();
    const [post] = router.of("POST", `${M1}/conflict-waivers`);
    expect(JSON.parse(post.body!)).toEqual({ reason: "Parent dispute closed; no overlap with this synthetic contract." });
    expect(post.headers.get("if-match")).toBe('"2"');
  });

  it("keeps the reason readable when the conflict changed before the waiver was recorded", async () => {
    const user = userEvent.setup();
    install({
      [`GET ${M1}`]: [
        json(lawyerView({ revision: 2, conflict_status: "conflict" })),
        json(lawyerView({ revision: 3, conflict_status: "clear", status: "ready" })),
      ],
      [`POST ${M1}/conflict-waivers`]: json({ error: "conflict_changed" }, 409),
    });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    await screen.findByText(C.C27_CONFLICT);
    const panel = screen.getByRole("region", { name: "Conflict check" });
    await user.click(within(panel).getByRole("radio", { name: "Waive the conflict" }));
    await user.type(within(panel).getByRole("textbox", { name: /Reason for waiver/ }), "Synthetic reason");
    await user.click(within(panel).getByRole("button", { name: "Record result" }));

    expect(await screen.findByRole("heading", { name: C.C42_HEADING })).toHaveFocus();
    expect(screen.getByText(C.c42Body("Cleared"))).toBeVisible();
    expect(screen.getByText("Synthetic reason")).toBeVisible();
    expect(screen.getByRole("button", { name: C.C42_COPY })).toBeVisible();
    expect(screen.getByText(C.C45)).toBeVisible();
    expect(screen.getByText(C.C27_OPEN)).toBeVisible();
  });

  it("never overwrites a newer title: shows both and saves only on request with the new revision", async () => {
    const user = userEvent.setup();
    const router = install({
      [`GET ${M1}`]: [
        json(lawyerView()),
        json(lawyerView({ revision: 3, title: "Renamed by a colleague" })),
        json(lawyerView({ revision: 4, title: "My synthetic title" })),
      ],
      [`PATCH ${M1}`]: [json({ error: "revision_mismatch" }, 409), json({ matter_id: "mtr-1", revision: 4 })],
    });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    await user.click(await screen.findByRole("button", { name: "Edit title" }));
    const input = screen.getByRole("textbox", { name: /Matter title/ });
    await waitFor(() => expect(input).toHaveFocus());
    await user.clear(input);
    await user.type(input, "My synthetic title");
    await user.click(screen.getByRole("button", { name: "Save title" }));

    expect(await screen.findByRole("heading", { name: C.C40_HEADING })).toHaveFocus();
    expect(screen.getByText(C.c40Latest(3))).toBeVisible();
    expect(screen.getByText("Renamed by a colleague")).toBeVisible();
    expect(screen.getByRole("textbox", { name: /Your unsaved title/ })).toHaveValue("My synthetic title");
    expect(router.of("PATCH", M1)).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: C.C40_SAVE }));
    await waitFor(() => expect(document.querySelector("dl + p")).toHaveTextContent(C.c22(4)));
    expect(live()).toHaveTextContent(C.c22(4));
    const [first, second] = router.of("PATCH", M1);
    expect(first.headers.get("if-match")).toBe('"1"');
    expect(second.headers.get("if-match")).toBe('"3"');
    expect(second.headers.get("idempotency-key")).not.toBe(first.headers.get("idempotency-key"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit title" })).toHaveFocus());
  });

  it("clears everything and shows one message when a change returns 404", async () => {
    const user = userEvent.setup();
    install({
      [`GET ${M1}`]: json(lawyerView()),
      [`POST ${M1}/conflict-checks`]: json({ error: "not_found" }, 404),
    });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    await screen.findByText(C.C27_PENDING);
    await user.click(screen.getByRole("radio", { name: "Conflict found" }));
    await user.click(screen.getByRole("button", { name: "Record result" }));
    expect(await screen.findByRole("heading", { name: C.C50_HEADING })).toHaveFocus();
    expect(screen.queryByText("Synthetic supply agreement")).toBeNull();
    expect(screen.queryByText("mtr-1")).toBeNull();
    expect(document.title).toBe(TITLES.notAvailable);
  });

  it("asks before leaving with an unsaved change, with Stay focused", async () => {
    const user = userEvent.setup();
    install({ [`GET ${M1}`]: json(lawyerView({ conflict_status: "conflict" })) });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    await screen.findByText(C.C27_CONFLICT);
    await user.click(screen.getByRole("radio", { name: "Waive the conflict" }));
    await user.type(screen.getByRole("textbox", { name: /Reason for waiver/ }), "Unsaved");
    await user.click(screen.getByRole("button", { name: "Open another matter" }));
    const dialog = screen.getByRole("alertdialog", { name: C.C70_HEADING });
    expect(dialog).toHaveTextContent(C.C70_BODY);
    await waitFor(() => expect(within(dialog).getByRole("button", { name: C.C70_STAY })).toHaveFocus());
  });
});

describe("reads", () => {
  it("shows the same not-available panel for any 404", async () => {
    install({ [`GET ${M1}`]: json({ error: "not_found" }, 404) });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    expect(await screen.findByRole("heading", { name: C.C50_HEADING })).toHaveFocus();
    expect(screen.getByRole("link", { name: C.C51_LINK })).toHaveAttribute("href", "/workbench/intake");
  });

  it("explains an outage on read with Try again", async () => {
    const user = userEvent.setup();
    install({ [`GET ${M1}`]: [json({ error: "unavailable" }, 503), json(lawyerView())] });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    expect(await screen.findByRole("heading", { name: C.C60_HEADING })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: C.TRY_AGAIN }));
    await screen.findByText(C.C27_PENDING);
  });

  it("renders the requester projection with status only and refreshes by GET", async () => {
    const user = userEvent.setup();
    install({
      [`GET ${M1}`]: [
        json({ matter_id: "mtr-1", status: "awaiting_clearance" }),
        json({ matter_id: "mtr-1", status: "ready" }),
      ],
    });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    const region = await screen.findByRole("region", { name: "Request status" });
    expect(within(region).getByText(C.C80_LABEL)).toBeVisible();
    expect(within(region).getByText(C.C82)).toBeVisible();
    expect(screen.queryByRole("region", { name: "Conflict check" })).toBeNull();
    expect(screen.queryByText(/revision/i)).toBeNull();
    expect(document.title).toBe(TITLES.requester);
    await user.click(within(region).getByRole("button", { name: "Refresh status" }));
    await within(region).findByText(C.C81_LABEL);
    expect(live()).toHaveTextContent(C.c83(C.C81_LABEL));
  });

  it("refetches on focus after a minute and announces an update", async () => {
    const now = Date.now();
    const clock = vi.spyOn(Date, "now").mockReturnValue(now);
    install({
      [`GET ${M1}`]: [json(lawyerView()), json(lawyerView({ revision: 5, conflict_status: "clear", status: "ready" }))],
    });
    render(<ConnectedIntake matterId="mtr-1" subject="tag-a" />);
    await screen.findByText(C.C27_PENDING);
    clock.mockReturnValue(now + 61_000);
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await screen.findByText(C.C27_OPEN);
    expect(live()).toHaveTextContent(C.c43(5));
    expect(screen.getByText(C.C45)).toBeVisible();
    clock.mockRestore();
  });
});
