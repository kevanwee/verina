import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import IntakePage from "../app/workbench/intake/page";
import Workbench from "../app/workbench/page";
import { ConflictStamp } from "../app/components/intake/ConflictStamp";
import {
  REGISTER_HITS,
  validateDetails,
  validateWaiverReason,
  SAMPLE_DETAILS,
  WAIVER_REASON_MAX,
} from "../lib/intake";

const WAIVER_REASON =
  "Parent dispute closed in March 2026; no overlap with this supply contract.";

function setup() {
  const user = userEvent.setup();
  render(<IntakePage />);
  return user;
}

async function submitIntake(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Submit for conflict check" }));
}

function conflictPanel() {
  return screen.getByRole("region", { name: "Conflict check" });
}

describe("Intake prototype page", () => {
  it("is labelled as a synthetic prototype and linked from the workbench", () => {
    render(<IntakePage />);
    expect(screen.getByText(/Synthetic prototype\./)).toBeVisible();
    expect(
      screen.getByRole("heading", { level: 1, name: "Open a matter and record its conflict check." }),
    ).toBeInTheDocument();
    render(<Workbench />);
    expect(screen.getByRole("link", { name: "Intake prototype" })).toHaveAttribute(
      "href",
      "/workbench/intake",
    );
  });

  it("has no form element, file input or external action", () => {
    const { container } = render(<IntakePage />);
    expect(container.querySelector("form")).toBeNull();
    expect(container.querySelector('input[type="file"]')).toBeNull();
    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveAttribute("type", "button");
    }
  });

  it("warns against real input and disables browser autofill for prototype fields", () => {
    const { container } = render(<IntakePage />);
    expect(screen.getByText(/Use invented examples only/)).toBeVisible();
    expect(screen.getByText(/reset on reload/)).toBeVisible();
    for (const field of container.querySelectorAll('input:not([type="radio"]), select')) {
      expect(field).toHaveAttribute("autocomplete", "off");
    }
  });

  it("resets entered details and recorded results instead of persisting them", async () => {
    const user = setup();
    await user.clear(screen.getByRole("textbox", { name: /Counterparty/ }));
    await user.type(screen.getByRole("textbox", { name: /Counterparty/ }), "Invented Demo Supplier");
    await submitIntake(user);
    let panel = conflictPanel();
    await user.click(within(panel).getByRole("radio", { name: "Clear" }));
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    await user.click(screen.getByRole("button", { name: "Start again" }));
    expect(screen.getByRole("textbox", { name: /Counterparty/ })).toHaveValue(SAMPLE_DETAILS.counterparty);
    expect(screen.queryByRole("region", { name: "Conflict check" })).toBeNull();
    await submitIntake(user);
    panel = conflictPanel();
    expect(within(panel).getByText("Conflict pending")).toBeVisible();
    expect(within(panel).queryByRole("region", { name: "Simulated record" })).toBeNull();
  });

  it("gives every intake control an accessible name and marks required fields", () => {
    render(<IntakePage />);
    const counterparty = screen.getByRole("textbox", { name: /Counterparty/ });
    expect(counterparty).toBeRequired();
    expect(counterparty).toHaveAccessibleDescription(/other party to the contract/);
    expect(screen.getByRole("combobox", { name: /Contract type/ })).toBeRequired();
    expect(screen.getByRole("textbox", { name: /Contract value/ })).not.toBeRequired();
    expect(screen.getByLabelText(/Needed by/)).toBeRequired();
    expect(screen.getByText(/Uploads are switched off/)).toBeVisible();
    const viewGroup = screen.getByRole("group", { name: "View as" });
    expect(within(viewGroup).getByRole("radio", { name: /Lawyer/ })).toBeChecked();
    expect(within(viewGroup).getByRole("radio", { name: /Requester/ })).not.toBeChecked();
  });

  it("shows inline errors and focuses the first invalid field", async () => {
    const user = setup();
    await user.clear(screen.getByRole("textbox", { name: /Counterparty/ }));
    await user.selectOptions(screen.getByRole("combobox", { name: /Contract type/ }), "");
    await submitIntake(user);
    const counterparty = screen.getByRole("textbox", { name: /Counterparty/ });
    expect(counterparty).toHaveAttribute("aria-invalid", "true");
    expect(counterparty).toHaveAccessibleDescription(/Enter the other party's name\./);
    expect(screen.getByText("Choose a contract type.")).toBeVisible();
    expect(counterparty).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("2 fields need attention.");
    expect(screen.queryByRole("region", { name: "Conflict check" })).toBeNull();
  });

  it("blocks review until a result is recorded, then clears with a named lawyer", async () => {
    const user = setup();
    await submitIntake(user);
    const panel = conflictPanel();
    expect(within(panel).getByText("Conflict pending")).toBeVisible();
    expect(within(panel).getByText(/Review is blocked/)).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(/Conflict check pending/);

    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    expect(within(panel).getByText("Choose a result to record.")).toBeVisible();

    await user.click(within(panel).getByRole("radio", { name: "Clear" }));
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    expect(panel.querySelector('[data-conflict="cleared"]')).toHaveTextContent(
      "Conflict check: Cleared",
    );
    expect(within(panel).getByText(/Ready for review/)).toBeVisible();
    expect(within(panel).getByText("Nadia Lim, 13 Oct 2026, 14:20 SGT")).toBeVisible();
  });
});

describe("Conflict waiver", () => {
  it("requires a reason before a waiver can be recorded", async () => {
    const user = setup();
    await submitIntake(user);
    const panel = conflictPanel();
    await user.click(within(panel).getByRole("radio", { name: "Conflict waived" }));

    const reason = within(panel).getByRole("textbox", { name: /Reason for waiver/ });
    expect(reason).toBeRequired();
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    expect(reason).toHaveAttribute("aria-invalid", "true");
    expect(reason).toHaveAccessibleDescription(/Enter a reason for the waiver/);
    expect(reason).toHaveFocus();
    expect(within(panel).queryByText("Waived")).toBeNull();

    await user.type(reason, "Agreed.");
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    expect(panel.querySelector('[data-conflict="waived"]')).toHaveTextContent("Waived");
  });

  it("records the named lawyer and reason, and flags it for sign-off", async () => {
    const user = setup();
    await submitIntake(user);
    let panel = conflictPanel();
    await user.click(within(panel).getByRole("radio", { name: "Conflict found" }));
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    panel = conflictPanel();
    expect(within(panel).getByText("Conflict found")).toBeVisible();
    expect(within(panel).getByText(/Review is blocked/)).toBeVisible();

    await user.click(within(panel).getByRole("radio", { name: "Waive the conflict" }));
    await user.type(within(panel).getByRole("textbox", { name: /Reason for waiver/ }), WAIVER_REASON);
    await user.click(within(panel).getByRole("button", { name: "Record result" }));

    const record = within(panel).getByRole("region", { name: "Simulated record" });
    expect(within(record).getByText("Waived by")).toBeVisible();
    expect(within(record).getByText(/Nadia Lim, associate/)).toBeVisible();
    expect(within(record).getByText(WAIVER_REASON)).toBeVisible();
    expect(within(record).getByText(/listed for Daniel Koh at sign-off/)).toBeVisible();
    expect(within(record).getByText(/same lawyer found and waived/)).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(/Conflict waived by Nadia Lim/);
  });

  it("rejects overlong waiver text with a focused error and recovers", async () => {
    const user = setup();
    await submitIntake(user);
    const panel = conflictPanel();
    await user.click(within(panel).getByRole("radio", { name: "Conflict waived" }));
    const reason = within(panel).getByRole("textbox", { name: /Reason for waiver/ });
    await user.click(reason);
    await user.paste("x".repeat(WAIVER_REASON_MAX + 1));
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    expect(reason).toHaveFocus();
    expect(reason).toHaveAccessibleDescription(/2000 characters or fewer/);
    expect(within(panel).queryByRole("region", { name: "Simulated record" })).toBeNull();
    await user.clear(reason);
    await user.type(reason, "Demo reason.");
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    expect(within(panel).getByRole("region", { name: "Simulated record" })).toBeVisible();
  });

  it("validates waiver reasons in the model", () => {
    expect(validateWaiverReason("   ")).toMatch(/Enter a reason/);
    expect(validateWaiverReason("short")).toBeNull();
    expect(validateWaiverReason("a".repeat(WAIVER_REASON_MAX))).toBeNull();
    expect(validateWaiverReason("a".repeat(WAIVER_REASON_MAX + 1))).toMatch(/2000 characters/);
    expect(validateWaiverReason("\u{1F600}".repeat(WAIVER_REASON_MAX))).toBeNull();
    expect(validateWaiverReason("\u{1F600}".repeat(WAIVER_REASON_MAX + 1))).toMatch(/2000 characters/);
    expect(validateWaiverReason(WAIVER_REASON)).toBeNull();
    expect(validateDetails(SAMPLE_DETAILS)).toEqual({});
  });
});

describe("Requester view", () => {
  it("hides privileged analysis and shows only stage, lawyer and target date", async () => {
    const user = setup();
    await submitIntake(user);
    let panel = conflictPanel();
    await user.click(within(panel).getByRole("radio", { name: "Conflict waived" }));
    await user.type(within(panel).getByRole("textbox", { name: /Reason for waiver/ }), WAIVER_REASON);
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    panel = conflictPanel();
    expect(within(panel).getByText(WAIVER_REASON)).toBeVisible();

    await user.click(screen.getByRole("radio", { name: /Requester/ }));

    expect(screen.queryByRole("region", { name: "Conflict check" })).toBeNull();
    for (const hit of REGISTER_HITS) {
      expect(screen.queryByText(hit.detail)).toBeNull();
    }
    expect(screen.queryByText(WAIVER_REASON)).toBeNull();
    expect(screen.queryByText(/waive/i)).toBeNull();
    expect(screen.queryByText(/conflict found/i)).toBeNull();
    expect(screen.queryByText(/Privileged/)).toBeNull();
    expect(screen.queryByText(/SGD 180,000/)).toBeNull();

    const status = screen.getByRole("region", { name: /Your request/ });
    expect(within(status).getByText("With legal for review")).toBeVisible();
    expect(within(status).getByText("Nadia Lim")).toBeVisible();
    expect(within(status).getByText("24 Oct 2026")).toBeVisible();
  });

  it("does not reveal that a conflict was found or why a matter was declined", async () => {
    const user = setup();
    await submitIntake(user);
    let panel = conflictPanel();
    await user.click(within(panel).getByRole("radio", { name: "Conflict found" }));
    await user.click(within(panel).getByRole("button", { name: "Record result" }));

    await user.click(screen.getByRole("radio", { name: /Requester/ }));
    let status = screen.getByRole("region", { name: /Your request/ });
    expect(within(status).getByText("Checks in progress")).toBeVisible();
    expect(within(status).queryByText(/conflict/i)).toBeNull();

    await user.click(screen.getByRole("radio", { name: /Lawyer/ }));
    panel = conflictPanel();
    await user.click(within(panel).getByRole("radio", { name: "Decline the matter" }));
    await user.click(within(panel).getByRole("button", { name: "Record result" }));
    await user.click(screen.getByRole("radio", { name: /Requester/ }));
    status = screen.getByRole("region", { name: /Your request/ });
    expect(within(status).getByText("Closed")).toBeVisible();
    expect(within(status).queryByText(/conflict|Harbourline Holdings/i)).toBeNull();
  });
});

describe("Keyboard operation", () => {
  it("completes intake and a waiver with the keyboard alone", async () => {
    const user = setup();

    // Skip link, then the workspace nav links, then the view toggle.
    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();
    await user.tab();
    await user.tab();
    await user.tab();
    await user.tab();
    expect(screen.getByRole("radio", { name: /Lawyer/ })).toHaveFocus();

    // Arrow keys move within the radio group, as native radios do.
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: /Requester/ })).toBeChecked();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: /Lawyer/ })).toBeChecked();

    // Tab through the fields to the submit button and press Enter.
    const submit = screen.getByRole("button", { name: "Submit for conflict check" });
    for (let tabs = 0; tabs < 20 && document.activeElement !== submit; tabs += 1) {
      await user.tab();
    }
    expect(submit).toHaveFocus();
    await user.keyboard("{Enter}");

    const panel = conflictPanel();
    const waived = within(panel).getByRole("radio", { name: "Conflict waived" });
    waived.focus();
    await user.keyboard(" ");
    expect(waived).toBeChecked();

    await user.tab();
    const reason = within(panel).getByRole("textbox", { name: /Reason for waiver/ });
    expect(reason).toHaveFocus();
    await user.keyboard(WAIVER_REASON);
    await user.tab();
    expect(within(panel).getByRole("button", { name: "Record result" })).toHaveFocus();
    await user.keyboard(" ");

    expect(panel.querySelector('[data-conflict="waived"]')).toHaveTextContent(
      "Conflict check: Waived",
    );
    expect(within(panel).getByRole("heading", { name: "Conflict check" })).toHaveFocus();
  });

  it("keeps every control in the tab order with a visible label", () => {
    render(<IntakePage />);
    for (const control of [
      ...screen.getAllByRole("button"),
      ...screen.getAllByRole("textbox"),
      ...screen.getAllByRole("radio"),
      screen.getByRole("combobox"),
    ]) {
      expect(control).not.toHaveAttribute("tabindex", "-1");
      expect(control).toHaveAccessibleName();
    }
  });
});

describe("ConflictStamp", () => {
  it.each([
    ["pending", "Conflict pending"],
    ["conflict", "Conflict found"],
    ["cleared", "Cleared"],
    ["waived", "Waived"],
    ["declined", "Declined"],
  ] as const)("announces %s with a text label and hides the icon", (stage, label) => {
    const { container } = render(<ConflictStamp stage={stage} />);
    expect(container.firstChild).toHaveTextContent(`Conflict check: ${label}`);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("gives each state a distinct icon shape", () => {
    const shapes = (["pending", "conflict", "cleared", "waived", "declined"] as const).map(
      (stage) => {
        const { container, unmount } = render(<ConflictStamp stage={stage} />);
        const markup = container.querySelector("svg")?.innerHTML ?? "";
        unmount();
        return markup;
      },
    );
    expect(new Set(shapes).size).toBe(5);
  });
});
