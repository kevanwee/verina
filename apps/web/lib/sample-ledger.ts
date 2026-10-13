import type { LedgerEntryData } from "@/app/components/ledger/LedgerEntry";

/**
 * SYNTHETIC sample data for the workspace shell. The parties, agreement,
 * clauses and lawyer are invented. No real client material.
 */
export const SAMPLE_MATTER = {
  title: "Master services agreement, Kestrel Freight and Harbourline Systems",
  type: "Master services agreement (inbound, supplier paper)",
  tier: "yellow",
} as const;

export const SAMPLE_LEDGER: LedgerEntryData[] = [
  {
    id: "LE-0141",
    assertion:
      "The supplier's total liability is capped at the fees paid in the 12 months before the claim.",
    status: "verified",
    stampDetail: "Verina, 13 Oct 2026",
    source: {
      kind: "quote",
      citation: "Clause 14.2, Master Services Agreement",
      text: "The Supplier's aggregate liability under this Agreement shall not exceed the total Fees paid by the Customer in the twelve (12) months preceding the event giving rise to the claim.",
    },
  },
  {
    id: "LE-0142",
    assertion: "Either party may terminate for convenience on 30 days' notice.",
    status: "contradicted",
    stampDetail: "Verina, 13 Oct 2026",
    source: {
      kind: "quote",
      citation: "Clause 18.3, Master Services Agreement",
      text: "The Customer may terminate this Agreement for convenience by giving the Supplier not less than ninety (90) days' written notice.",
    },
    note: "Verina: the clause gives 90 days, and only the Customer may terminate for convenience.",
  },
  {
    id: "LE-0143",
    assertion: "The agreement is governed by Singapore law.",
    status: "unsupported",
    stampDetail: "Verina, 13 Oct 2026",
    source: {
      kind: "none",
      searched:
        "No governing-law clause was found in the parsed agreement or its schedules.",
    },
  },
  {
    id: "LE-0144",
    assertion:
      "The indemnity in clause 16.1 is consistent with the firm's playbook position for logistics services.",
    status: "attested",
    stampDetail: "N. Lim, 13 Oct 2026",
    source: {
      kind: "quote",
      citation: "Clause 16.1, Master Services Agreement",
      text: "Each party shall indemnify the other against losses arising from its breach of the confidentiality obligations in clause 12.",
    },
    note: "Reason (N. Lim): mutual and limited to confidentiality breach, which matches playbook position P-07.",
  },
];
