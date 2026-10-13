# Product

<!-- impeccable:product-schema 1 -->

> Init note (13 Oct 2026): written by the designer agent without a live interview (no question tool in
> the subagent session). Every fact below is taken from the product owner's written brief and the team
> charter (`AGENTS.md`); items marked *(inferred)* need PO confirmation.

## Platform

web

## Users

- **Associates** at small and mid-sized Singapore law firms reviewing inbound commercial contracts
  (NDA, MSA, SaaS/vendor, DPA) under time pressure. Job: turn a long agreement into a redline and an
  advice note they can defend.
- **Partners** who sign off deliverables. Job: confirm quickly and confidently that every assertion in
  the deliverable is grounded or owned by a named lawyer.
- **In-house counsel** (often a one- or two-person legal team). Job: triage incoming contracts and sign
  off low-risk ones fast without signing anything unread.
- Secondary: business requesters who submit a contract and need to see its status; they must never
  see privileged analysis.

## Product Purpose

Verina is a verified AI workbench for contract matters under Singapore law. It takes a matter from
intake to a signed-off deliverable in one workspace. Success: a lawyer can trust and defend every line
that leaves the building.

## Positioning

The **Verification Ledger**: every AI-generated legal assertion becomes a ledger entry, and export to a
client is blocked until each entry is verified against its source (statute section, judgment, parsed
contract clause) or attested by a named lawyer with a reason. Verina's claim is not speed; it is that
nothing unchecked reaches a client.

## Operating Context

- Desk work on firm laptops and large monitors, long sessions, often under deadline. *(inferred)*
- Source material is legal text: contract clauses, Singapore statutes, judgments. Users read closely
  and quote exactly.
- Matter flow: intake and triage (risk tier Green / Yellow / Red), conflict check, ingest and redact,
  playbook review and risk grid, accept or override, redline and memo, Verification Ledger, partner
  sign-off, delivery with AI-use disclosure, audit pack.
- Ledger entry statuses: **Verified**, **Unsupported**, **Contradicted**, **Attested**.

## Capabilities and Constraints

- Web workspace in Next.js (App Router), React 19, TypeScript, plain CSS custom properties (no
  Tailwind). Motion via GSAP; smooth scroll via Lenis (both mandated by the PO).
- Synthetic content only during development; no real client documents or names.
- Role-based visibility: the requester role never sees privileged analysis.
- Landing page at `/`; synthetic read-only workbench demonstration at `/workbench`.
- Undecided: final product name treatment / logo, Word add-in surface
  (later release).

## Brand Commitments

- Calm, precise, trustworthy. Closer to a well-set legal document than a SaaS dashboard (PO brief).
- Avoid generic SaaS and AI aesthetics: no AI-purple, no glow, no hype copy.

## Evidence on Hand

- No customers, testimonials, benchmarks or metrics exist yet. Do not fabricate any.
- No logo or brand assets exist yet.

## Product Principles

1. Every assertion shows its provenance; status is never implied, always stated.
2. The lawyer stays the decision-maker; the interface proposes, the named lawyer disposes.
3. Calm under pressure: nothing on a work surface competes with the text being reviewed.
4. Status must be readable without colour, without motion, and by a screen reader.

## Accessibility & Inclusion

WCAG 2.2 AA is a product requirement: full keyboard paths, visible focus, screen-reader labels, and
contrast in both light and dark themes. Respect `prefers-reduced-motion` everywhere (smooth scrolling
and reveals switch off entirely).
