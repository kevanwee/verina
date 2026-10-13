# DPA Checklist Review: Model provider (pre-negotiation requirements)

> **13 Oct 2026 review:** this remains a design-time draft requiring named lawyer review and PO acceptance. [SOURCE_REVIEW.md](SOURCE_REVIEW.md) records the actual source coverage and unresolved version/paragraph checks. [REDACTION_COMPATIBILITY.md](REDACTION_COMPATIBILITY.md) records implementation gaps; the taxonomy is not a live-egress approval.


| | |
| --- | --- |
| Version | v0 (Sprint 0, task T0.4 / EN-5) |
| Method | `lq-dpa-checklist-review` skill, regime **general_commercial**, with a Singapore **PDPA Transfer Limitation overlay** (PDPA s 26; PDP Regs 2021 regs 9–12; Key Concepts ch 19) |
| Status | **Requirements checklist. No provider DPA has been received yet.** Every Status cell reads "Not yet assessed". In S2 (roadmap: "DPA review of model provider"), counsel runs the skill against each candidate's actual DPA, ZDR addendum and service terms and fills in Status and Clause |
| Owner | verina-pdpa-counsel; PO approves the route (C-1.1, C-1.2) |
| Related | [PDPA_ASSESSMENT.md](PDPA_ASSESSMENT.md) §8 · [DATA_INVENTORY.md](DATA_INVENTORY.md) D-06 · [`../security/CONTROLS.md`](../security/CONTROLS.md) C-1.1–C-1.4, C-2.2 |

**Regulatory regime:** general_commercial + PDPA transfer limitation overlay
**Party role:** Verina is the data exporter, i.e. the customer of the model provider. Verina is itself a data intermediary for its law-firm customers, so these terms must let Verina flow down its own obligations (PDPA s 4(2)–(3)). Reviewed from the **controller-side perspective**: we want strong, specific processor obligations.
**Data categories:** redacted (pseudonymised) matter excerpts, playbook rules, instructions and model outputs. These remain personal data while the tenant redaction map exists ([PII_TAXONOMY.md](PII_TAXONOMY.md) §1). Residual contextual identifiers and unredacted commercial terms are confidential and potentially privileged.
**International transfer context:** to be determined in S2. Singapore-region inference is preferred. If any processing, storage or support access happens outside Singapore, the PDPA overlay rows (T-1 to T-4) are mandatory.

> **Privilege and confidentiality:** this checklist and the future completed review are draft legal work product for the PO, who is senior legal counsel, inside an attorney-supervised workflow. Provider documents reviewed in S2 must be handled in the same way. Do not paste customer data into any provider portal during evaluation; synthetic fixtures only.

## Overall posture

**Not yet assessed: no document.** These are the terms Verina will **require** before any customer data, even redacted, reaches a model endpoint. Items marked **High** are walk-away terms: if a route cannot meet them, it is blocked unless the PO records an exception (AGENTS.md blocking rule; CONTROLS C-1.1).

> Note: this review applies the general commercial DPA baseline. The DPA's compliance with specific regulatory regimes (GDPR, CCPA/CPRA, HIPAA, etc.) was not assessed and may require additional review. Once the applicable regime(s) are identified, recommend re-running this skill with the specific regime to confirm compliance. For Singapore, the PDPA transfer-limitation overlay below has been added because the skill has no PDPA regime file.

## Compliance checklist

Severity: **High** = proposed release-blocking position (statutory requirements and stricter product/contract terms are distinguished below); **Medium** = real legal or operational risk; **Low** = hygiene or preference.

| # | Required term | Source | Status | Severity | Clause | Required position |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Definitions and scope: personal data, processing, sub-processor; covers prompts, context, files, outputs, embeddings, logs and metadata | Skill baseline #1 | Not yet assessed | Medium | — | "Customer Data" includes all inputs **and outputs** and any derived data, logs and metadata containing them |
| 2 | Roles: provider is a processor / data intermediary acting on Verina's instructions | Skill #2; PDPA s 2, s 4(2); GenAI AG para 7.4 | Not yet assessed | High | — | Provider processes as a DI "on behalf of and for the purposes of" Verina under a **written** contract. No joint-controller language |
| 3 | **Purpose limitation: no training, no fine-tuning, no product improvement, no benchmarking** on Customer Data, including outputs | Skill #3; NFR-1; MinLaw Guide para 23(e)(ii); GenAI AG para 7.1 | Not yet assessed | **High** | — | Express prohibition, with no opt-out default and no "aggregated/de-identified" carve-out for Customer Data. Survives termination |
| 4 | **Zero data retention and no human review** | NFR-1; MinLaw para 23(d)(i), 23(e)(i)(a); PCR r 6; PDPA s 25 (via flow-down) | Not yet assessed | **High** | — | Inputs and outputs not stored beyond what is needed to return the response (no persistent logs, caching only in memory). **No abuse-monitoring retention and no human access to content.** If the provider cannot offer this, the PO must record an exception (Q-4) |
| 5 | Documented instructions only, including for transfers | Skill #4 (documented instructions is a proposed contractual safeguard; reg 11(2)(b) concerns countries/territories) | Not yet assessed | High | — | Process only on Verina's documented instructions (API requests + DPA). Notify if an instruction would breach law |
| 6 | Personnel confidentiality | Skill #5; PCR r 6; Evidence Act ss 128, 128A | Not yet assessed | Medium | — | Written confidentiality for all personnel and sub-processors; access on a least-privilege basis |
| 7 | Security measures appropriate to risk | Skill #6; PDPA s 24; Key Concepts ch 17; MinLaw para 23(e)(v) | Not yet assessed | High | — | Security annex: encryption in transit (TLS 1.2+) and at rest; tenant/customer isolation; model-isolation controls; access logging; vulnerability management; prompt-injection and data-leakage safeguards (GenAI AG para 8.2). **SOC 2 Type II and/or ISO/IEC 27001** reports available annually |
| 8 | Sub-processors: authorisation, notice, objection, flow-down, liability | Skill #7; PDP Regs reg 10–11 (onward transfers) | Not yet assessed | High | — | Published list with **countries**. ≥30 days' notice of changes with a right to object and terminate. Same DPA obligations flowed down. Provider fully liable for sub-processors |
| 9 | Assistance with data subject requests | Skill #8; PDPA ss 21–22 (customer's obligation flowing through Verina) | Not yet assessed | Low (ZDR means little to retrieve) | — | Reasonable assistance at no extra fee. Confirm in writing that nothing is retained to search |
| 10 | **Breach notification ≤24h** with content | Skill #9; PDPA s 26C(3)(a); DBN Regs reg 5; Key Concepts para 20.7 | Not yet assessed | **High** | — | Notify Verina **without undue delay and in any event within 24 hours** of becoming aware (credible grounds) of any security incident affecting Customer Data. No "confirmed" or "material" qualifier. Include the DBN reg 5 particulars as available: when and how discovered, chronology, cause, affected data and approximate numbers, potential harm, containment and remediation, contact. Ongoing updates and cooperation |
| 11 | Audit rights | Skill #10; MinLaw para 23(e)(iv) (audit capabilities); GenAI AG para 7.5 | Not yet assessed | Medium | — | Annual independent reports (SOC 2 II / ISO 27001), security questionnaire responses, and an on-site or third-party audit right after a breach or regulator request. No per-audit fee that prices out the right |
| 12 | Return or deletion at termination, plus deletion on request | Skill #11; PDPA s 25; MinLaw para 23(e)(iv) | Not yet assessed | High | — | Delete all Customer Data, including any transient or backup copies, within 30 days of termination or on request. Written certification. Carve-out only for legally required retention, and only with notice |
| 13 | Term, termination and survival | Skill #13 | Not yet assessed | Low | — | DPA runs while any processing occurs. Confidentiality, deletion, audit and the no-training term survive |
| 14 | Liability: data-protection breaches carved out of the general cap or given a super-cap | Skill #14; PDPA s 48J exposure | Not yet assessed | Medium | — | Super-cap for breach of DPA, confidentiality and no-training terms. Indemnity for regulatory fines and third-party claims caused by provider breach (negotiable) |
| 15 | Governing law and forum | Skill #15 | Not yet assessed | Low | — | Singapore law and SIAC/Singapore courts preferred. Otherwise ensure PDPA-comparable obligations remain enforceable |
| 16 | **Legal process / compelled disclosure** | PCR r 6; Evidence Act ss 128, 131; PDPA_ASSESSMENT §4 | Not yet assessed | High | — | Notify Verina of any government or legal demand (unless legally prohibited); challenge overbroad requests; disclose the minimum. Transparency report |
| 17 | **Data location and processing region per request** | NFR-2; MinLaw para 23(e)(iii) and fn 18; CONTROLS C-2.2 | Not yet assessed | **High** | — | Contractual commitment to the selected region (Singapore preferred) for inference **and** any transient storage, with **no cross-region failover** unless Verina enables it. The region is identifiable per request (header or log) so Verina can record it per call |
| 18 | Model and version change notice | NFR-7; CONTROLS C-7.3 | Not yet assessed | Medium | — | Pinned model versions available; ≥90 days' notice of deprecation; no silent change of model behind a pinned id |
| 19 | Documentation for downstream compliance | GenAI AG paras 7.5, 8.3 | Not yet assessed | Medium | — | Provider supplies, and keeps current, documentation on data access controls, residency, retention, incident response and breach procedures, which Verina may share with customers under NDA |
| 20 | No use of Customer Data to identify individuals / re-identification prohibition | PDPA s 48F (policy analogue); PII_TAXONOMY §5 | Not yet assessed | Medium | — | Provider shall not attempt to re-identify individuals from pseudonymised data or combine Customer Data with other data |

### PDPA transfer-limitation overlay (required if any processing, storage or access occurs outside Singapore)

| # | Required term | Source | Status | Severity | Clause | Required position |
| --- | --- | --- | --- | --- | --- | --- |
| T-1 | Legally enforceable obligation to provide a standard of protection **at least comparable** to the PDPA | [PDP Regs 2021 reg 10(1), reg 11(1)(b), 11(2)(a)](https://sso.agc.gov.sg/SL/PDPA2012-S63-2021) | Not yet assessed | **High** | — | Express clause: the recipient "shall provide to the transferred personal data a standard of protection that is at least comparable to the protection under the Personal Data Protection Act 2012 (Singapore)" |
| T-2 | **Countries and territories specified** | reg 11(2)(b) | Not yet assessed | **High** | — | Schedule listing every country where Customer Data may be processed, stored or accessed (incl. support and sub-processors). Changes only under item 8 notice |
| T-3 | Minimum areas for a DI recipient: **protection, retention limitation, breach notification** to Verina without undue delay | [Key Concepts](https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/advisory-guidelines/ag-on-key-concepts/advisory-guidelines-on-key-concepts-in-the-pdpa-17-may-2022.pdf) para 19.9 table, para 19.10 | Not yet assessed | **High** | — | Covered by items 7, 4/12 and 10. Confirm each is expressly tied to the transferred data |
| T-4 | Alternative basis: **specified certification** (DI recipient: APEC PRP or CBPR, Global PRP or CBPR) | reg 12(1), 12(2)(a) as amended by S 86/2026 w.e.f. 2 Mar 2026 | Not yet assessed | Medium (alternative to T-1/T-2) | — | If relied on, obtain current certificate evidence, scope (must cover the service) and renewal date; record it in the sub-processor register. The ASEAN Model Contractual Clauses are an accepted contractual option (para 19.10) |

## Detailed findings

None yet: no document assessed. In S2, for each candidate route (Anthropic API direct; Amazon Bedrock; Google Vertex AI), counsel will:

1. Collect the DPA, ZDR or zero-retention addendum, service-specific terms, sub-processor list, region documentation and security reports, recording the **retrieval date** for each.
2. Fill in Status, Clause and Assessment for every row, and write a detailed finding (required / document says / gap / recommended language) for each Partial, Missing or Unclear item.
3. Compare the routes side by side for the PO's S2 decision (PDPA_ASSESSMENT §8).

## Items requiring human judgment

- Whether any route actually serves the chosen Claude models from Singapore without cross-region routing (**to verify** with each provider in S2).
- Whether to accept abuse-monitoring retention or human review if true ZDR is unavailable (PO, Q-4).
- Whether disclosing redacted contract excerpts to a provider under these terms preserves privilege (**to verify** under Singapore law; PDPA_ASSESSMENT §4).
- How much liability to accept from a large provider whose terms are non-negotiable.

## Recommended next steps

1. S2: run `lq-dpa-checklist-review` against each candidate's actual documents and attach the completed checklists to the C-1.1 approval record.
2. Block live model calls (fake clients only) until one route passes every **High** row or the PO records an exception.
3. Mirror rows 3, 4, 10, 12, 16 and 17 in Verina's customer-facing DPA as the flow-down promise (PDPA_ASSESSMENT P-1).

## Change log

| Version | Date | Change | Author |
| --- | --- | --- | --- |
| v0 | 2026-10-13 | Requirements checklist (no document assessed) | verina-pdpa-counsel |
