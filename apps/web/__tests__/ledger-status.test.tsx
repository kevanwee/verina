import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LedgerEntry } from "../app/components/ledger/LedgerEntry";
import { RiskTierBadge } from "../app/components/ledger/RiskTierBadge";
import { StatusStamp } from "../app/components/ledger/StatusStamp";
import Workbench from "../app/workbench/page";
import {
  LEDGER_STATUSES,
  RISK_TIERS,
  STATUS_META,
  TIER_META,
} from "../lib/ledger";
import { SAMPLE_LEDGER } from "../lib/sample-ledger";

describe("StatusStamp", () => {
  it.each(LEDGER_STATUSES)("shows a visible text label for %s", (status) => {
    const { container } = render(<StatusStamp status={status} />);
    const label = STATUS_META[status].label;
    expect(screen.getByText(label)).toBeVisible();
    // Spoken as "Ledger status: <label>", not as a colour or icon.
    expect(container.firstChild).toHaveTextContent(`Ledger status: ${label}`);
  });

  it.each(LEDGER_STATUSES)("hides the decorative icon for %s", (status) => {
    const { container } = render(<StatusStamp status={status} />);
    const icon = container.querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("gives each status a distinct icon shape", () => {
    const shapes = LEDGER_STATUSES.map((status) => {
      const { container, unmount } = render(<StatusStamp status={status} />);
      const markup = container.querySelector("svg")?.innerHTML ?? "";
      unmount();
      return markup;
    });
    expect(new Set(shapes).size).toBe(LEDGER_STATUSES.length);
  });

  it("renders the imprint detail when given", () => {
    render(<StatusStamp status="attested" detail="N. Lim, 13 Oct 2026" />);
    expect(screen.getByText("N. Lim, 13 Oct 2026")).toBeInTheDocument();
  });
});

describe("RiskTierBadge", () => {
  it.each(RISK_TIERS)("announces the %s tier by name", (tier) => {
    const { container } = render(<RiskTierBadge tier={tier} />);
    expect(container.firstChild).toHaveTextContent(
      `Risk tier: ${TIER_META[tier].label}`,
    );
    expect(container.querySelector("svg")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });
});

describe("LedgerEntry", () => {
  it("is an article named by its assertion, with status and source", () => {
    const entry = SAMPLE_LEDGER[1];
    render(<LedgerEntry entry={entry} />);
    const article = screen.getByRole("article", { name: entry.assertion });
    expect(
      within(article).getByText(STATUS_META[entry.status].label),
    ).toBeInTheDocument();
    if (entry.source.kind === "quote") {
      expect(within(article).getByText(entry.source.citation)).toBeVisible();
    }
  });
});

describe("Workbench ledger", () => {
  it("lists every sample entry and a legend for every status and tier", () => {
    render(<Workbench />);
    const ledger = screen.getByRole("region", { name: "Verification ledger" });
    expect(within(ledger).getAllByRole("article")).toHaveLength(
      SAMPLE_LEDGER.length,
    );

    const legend = screen.getByRole("region", { name: "Reading a status" });
    for (const status of LEDGER_STATUSES) {
      expect(
        within(legend).getByText(STATUS_META[status].label),
      ).toBeInTheDocument();
    }
    for (const tier of RISK_TIERS) {
      expect(within(legend).getByText(TIER_META[tier].label)).toBeInTheDocument();
    }
  });

  it("puts entries that block export first", () => {
    render(<Workbench />);
    const ledger = screen.getByRole("region", { name: "Verification ledger" });
    const statuses = within(ledger)
      .getAllByRole("article")
      .map((article) => article.getAttribute("data-status"));
    const firstCleared = statuses.findIndex(
      (status) => !STATUS_META[status as keyof typeof STATUS_META].blocksExport,
    );
    const lastOpen = statuses.findLastIndex(
      (status) => STATUS_META[status as keyof typeof STATUS_META].blocksExport,
    );
    expect(lastOpen).toBeLessThan(firstCleared);
  });

  it("explains why export is locked", () => {
    render(<Workbench />);
    const exportButton = screen.getByRole("button", { name: "Export to client" });
    expect(exportButton).toHaveAttribute("aria-disabled", "true");
    expect(exportButton).toHaveAccessibleDescription(/Export is blocked/);
  });
});

