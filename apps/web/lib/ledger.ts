/**
 * Ledger vocabulary shared by the UI. Labels and meanings here are the single
 * source for the status legend, the stamps and their accessible names.
 */

export const LEDGER_STATUSES = [
  "verified",
  "unsupported",
  "contradicted",
  "attested",
] as const;

export type LedgerStatus = (typeof LEDGER_STATUSES)[number];

export const STATUS_META: Record<
  LedgerStatus,
  { label: string; meaning: string; blocksExport: boolean }
> = {
  verified: {
    label: "Verified",
    meaning: "The source says what the assertion says.",
    blocksExport: false,
  },
  unsupported: {
    label: "Unsupported",
    meaning: "No source was found for the assertion.",
    blocksExport: true,
  },
  contradicted: {
    label: "Contradicted",
    meaning: "The source says something different.",
    blocksExport: true,
  },
  attested: {
    label: "Attested",
    meaning: "A named lawyer takes responsibility for it, with a reason.",
    blocksExport: false,
  },
};

export const RISK_TIERS = ["green", "yellow", "red"] as const;

export type RiskTier = (typeof RISK_TIERS)[number];

export const TIER_META: Record<RiskTier, { label: string; meaning: string }> = {
  green: { label: "Green", meaning: "Standard terms. Fast sign-off." },
  yellow: { label: "Yellow", meaning: "Deviations from playbook. Counsel review." },
  red: { label: "Red", meaning: "Material risk. Full legal review." },
};
