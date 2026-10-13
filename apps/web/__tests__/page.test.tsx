import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Home from "../app/page";

describe("Home page", () => {
  it("explains the proposition and links to the preserved demo", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Every assertion. Accounted for." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Explore the workbench" })).toHaveAttribute("href", "/workbench");
    expect(screen.getByText(/Statuses are preset/)).toBeVisible();
    expect(screen.getByText(/does not accept uploads/)).toBeVisible();
  });

  it("lets a visitor inspect contradictory and missing evidence without pretending to verify", () => {
    render(<Home />);
    const preview = screen.getByRole("region", { name: "The Verification Ledger" });
    fireEvent.click(within(preview).getByRole("button", { name: "Termination" }));
    expect(within(preview).getByText("Contradicted")).toBeVisible();
    expect(within(preview).getByText(/ninety \(90\) days/)).toBeVisible();
    expect(within(preview).getByRole("button", { name: "Termination" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(preview).getByRole("button", { name: "Governing law" }));
    expect(within(preview).getByText("Unsupported")).toBeVisible();
    expect(within(preview).getByText(/No governing-law clause was found/)).toBeVisible();
    expect(within(preview).getByRole("button", { name: "Termination" })).toHaveAttribute("aria-pressed", "false");
    expect(within(preview).getByText(/Unresolved entries keep the gate closed/)).toBeVisible();
  });

  it("renders readable content in the reduced-motion fallback", () => {
    const { container } = render(<Home />);
    expect(screen.getByRole("heading", { level: 1 })).toBeVisible();
    expect(container.querySelector("[data-reveal]")).not.toHaveStyle({ visibility: "hidden" });
    const preview = screen.getByRole("region", { name: "The Verification Ledger" });
    fireEvent.click(within(preview).getByRole("button", { name: "Termination" }));
    expect(within(preview).getByText("Contradicted")).toBeVisible();
  });
});
