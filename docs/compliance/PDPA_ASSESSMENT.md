# PDPA assessment (v0)

> **13 Oct 2026 review:** this remains a design-time draft requiring named lawyer review and PO acceptance. [SOURCE_REVIEW.md](SOURCE_REVIEW.md) records the actual source coverage and unresolved version/paragraph checks. [REDACTION_COMPATIBILITY.md](REDACTION_COMPATIBILITY.md) records implementation gaps; the taxonomy is not a live-egress approval.


| | |
| --- | --- |
| Version | v0 (Sprint 0, task T0.4 / EN-5) |
| Owner | verina-pdpa-counsel. The PO (senior legal counsel) accepts it and makes the decisions in §10 |
| Status | **Draft for PO review.** Design-time: no production processing exists, so this assesses planned flows |
| Related | [PII_TAXONOMY.md](PII_TAXONOMY.md) · [pii-taxonomy.json](pii-taxonomy.json) · [DATA_INVENTORY.md](DATA_INVENTORY.md) · [MODEL_PROVIDER_DPA_CHECKLIST.md](MODEL_PROVIDER_DPA_CHECKLIST.md) · [`../security/DATA_FLOW.md`](../security/DATA_FLOW.md) · [`../security/CONTROLS.md`](../security/CONTROLS.md) · [`../security/THREAT_MODEL.md`](../security/THREAT_MODEL.md) |
| Sources retrieved | 13 Oct 2026 (see §11). SSO publisher bytes showed a current-at-13-Oct-2026 marker; the base fetch contained preliminary provisions only. Wider provision verification is incomplete (SOURCE_REVIEW.md) |

> This is a draft compliance analysis to support the PO's legal judgement. It is not a legal opinion. Anything marked **to verify** could not be confirmed from a primary source in this pass.

## 1. Conclusions

1. **Verina is a data intermediary** (DI) for the matter content it processes for law-firm and in-house customers ([PDPA s 2](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr2-) "data intermediary"). The partial exemption in [s 4(2)](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr4-) applies **only** if that processing is "pursuant to a contract which is evidenced or made in writing". A written customer processing agreement is therefore a precondition, not paperwork. Without it, Verina carries every obligation in Parts 3 to 6B for customer data.
2. As a DI, Verina is **directly** bound by Protection (s 24), Retention Limitation (s 25) and the duty to notify the customer of a data breach without undue delay (s 26C(3)(a), and s 26E for public-agency customers). Every other obligation sits with the customer under s 4(3). Customers can only meet those obligations if the product supports them, so they still drive product requirements.
3. **Verina is an organisation** (full obligations) for its own data: user accounts, security logs, support, billing and marketing. It is also an organisation for **any** processing of customer data outside the customer's instructions, such as training, evaluation or analytics on customer content. That processing must stay prohibited.
4. **The model provider is Verina's sub-processor.** Under the PDPC [Advisory Guidelines on Use of Personal Data in Generative AI](https://www.pdpc.gov.sg/organisations/regulations-decisions/regulatory-guidance/advisory-guidelines-on-use-of-personal-data-in-generative-ai) (20 Jul 2026), Verina is a "System Provider" acting as DI (para 8.1), the model provider is a DI when running inference (para 7.4), and the customer is the "System Deployer" with primary responsibility (para 9.1).
5. **Redaction does not take the model call outside the PDPA.** Placeholdered prompts stay personal data while the mapping exists, and contract context can re-identify people. So the Transfer Limitation Obligation (TLO) still applies if inference happens outside Singapore. Redaction is the main **protection** control (s 24) and the main **confidentiality** control (PCR r 6). It is not a TLO workaround.
6. **The TLO is the customer's, but Verina must enable it.** PDPC states that the organisation is responsible for the TLO "regardless of whether the personal data is transferred by the organisation to an overseas data intermediary or transferred overseas by the data intermediary in Singapore" ([Key Concepts](https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/advisory-guidelines/ag-on-key-concepts/advisory-guidelines-on-key-concepts-in-the-pdpa-17-may-2022.pdf), Part II, "Overseas transfers of personal data", p 26). For the proposed contractual route, if the model route leaves Singapore, Verina should hold a [PDP Regs 2021 reg 11](https://sso.agc.gov.sg/SL/PDPA2012-S63-2021) contract (or reg 12 certification) with the provider and disclose the countries to customers.
7. The **AGENTS.md blocking rule** (no unredacted personal data to an external model without a recorded PO exception) is consistent with s 24, the PCR r 6 duty and MinLaw Guide para 23. It should stay a hard technical control (egress guard, fail closed), not a policy.
8. **Redaction review is a release control.** Product priority and acceptance remain the PO's decisions.

## 2. Roles

| Context | Verina's role | Customer's role | Basis | Consequence |
| --- | --- | --- | --- | --- |
| Matter content: uploaded contracts, email intake, parsed text, review results, drafts, ledger, audit of matter actions | **Data intermediary** | Organisation (controller); "System Deployer" | PDPA s 2, s 4(2)–(3); Key Concepts Part II "Data intermediaries" (pp 24–30); GenAI AG paras 8.1, 9.1 | Verina: ss 24, 25, 26C(3)(a) (+26E). Customer: everything else, including for Verina's processing |
| Customer users' identities (lawyers' names, emails, roles) used to provide the service | DI for the customer's user directory and audit attributions; **organisation** for Verina's own account and contract administration | Organisation | s 4(2) | Split: product data vs Verina business records. Attestation names inside the ledger are matter content (DI) |
| Verina's own operations: accounts, billing, support, security logs, telemetry, marketing, pilot recruitment | **Organisation** | — | s 4(2) excludes only processing "on behalf of and for the purposes of another organisation" | All Data Protection Provisions apply, incl. DPO, notice, consent, DBN, and Do Not Call (Part 9) for marketing |
| Any use of customer content for Verina's own purposes (training, evals, product analytics, benchmarking) | Would be **organisation**, likely without a lawful basis | — | Key Concepts Part II: a DI "remains responsible for complying with all Data Protection Provisions" for other activities | **Prohibited by design.** Evals use synthetic fixtures only (AGENTS.md; CONTROLS C-5.4) |
| Model provider during inference | Sub-processor (DI of Verina, ultimately for the customer) | — | GenAI AG para 7.4; para 7.1 (provider becomes an organisation if it uses prompts for model development) | DPA must prohibit training/secondary use. See checklist |
| Public-agency customers (if ever in scope) | DI of a public agency | Public agency (outside the Data Protection Provisions) | s 4(1)(c), s 26E | Breach notice to the agency under s 26E. Out of MVP scope unless the PO decides otherwise (Q-10) |

**Data subjects** in matter content: signatories, directors, guarantors, employees and contractors named in contracts, contact persons, counterparty personnel, the client's individual customers (e.g. in DPAs or schedules), minors (rare), witnesses (rare), and email senders and recipients.

**Business contact information.** A name or contact detail falls within business contact information only when the statutory definition and context are satisfied; a contractual name is not automatically exempt. [s 4(5)](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr4-) excludes it from Parts 3–6A, **but not** from client confidentiality. Verina therefore redacts it anyway (PII_TAXONOMY §2). Guarantors' residential addresses, NRICs and personal financial data are **not** business contact information.

## 3. Obligation map

**Owners:** PO = product owner; PDPA = verina-pdpa-counsel; SEC = verina-security; ENG = verina-engineer; AI = verina-ai-engineer; QA = verina-qa; UX = verina-designer.
**Scheduling:** the internal sprint board controls timing; phase references here are proposed implementation sequencing.
"DI" is what binds Verina for customer data; "Org" is what binds it for its own data.

| # | Obligation (primary source) | Binds Verina as DI? | Binds Verina as Org? | What it means for Verina | Required product / technical control | Owner | Sprint |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Accountability, DPO**: designate ≥1 individual; publish business contact information; policies and practices; complaints process; staff communication ([ss 11–12](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr11-,pr12-); Key Concepts ch 21) | Not directly (s 4(2)). Customers need evidence of Verina's practices (GenAI AG paras 7.5, 8.3) | **Yes** | Appoint Verina's DPO. A data protection management programme (policies, complaints process, training). Publish a customer "AI and data safeguards" sheet. Individuals face offences for unauthorised disclosure, improper use and re-identification ([ss 48D–48F](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr48D-,pr48E-,pr48F-)) | DPO named; BCI published (BizFile+ is acceptable, Key Concepts para 21.7). Privacy policy for users. Staff confidentiality terms + training covering ss 48D–48F. PDPA review gate in the story flow (AGENTS §4). Safeguards sheet (residency, retention, redaction metrics, incident process) | PO (DPO), PDPA | S1 (DPO, gate), S7 (sheet), S8 (published before pilot) |
| 2 | **Consent** incl. deemed consent, exceptions, withdrawal ([ss 13–17](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr13-,pr14-,pr15-,pr15A-,pr16-,pr17-)) | No. The customer relies on consent, deemed consent by contract (s 15(3), (6)) or an exception; which First/Second Schedule paragraphs suit legal services is **to verify** | Yes (accounts, marketing) | Verina must never create a new purpose needing fresh consent. Withdrawal: the customer must make its DIs "cease" (s 16(4)) | Customer-instruction tooling: stop processing and delete per matter, and per individual across a tenant. User sign-up notice. No marketing without consent; check the DNC Register for SG numbers (Part 9, **to verify** scope) | ENG, PDPA | S1 (notice), S3 (deletion tooling) |
| 3 | **Purpose limitation** ([s 18](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr18-)) | Indirect. Processing outside instructions makes Verina an organisation (row 2 of §2) | Yes | Process customer content only to deliver the instructed service. GenAI AG para 9.2: deployers specify the intended purpose and the data needed | No training, evals, analytics or benchmarking on customer content. Telemetry is content-free (CONTROLS B-4). Firm AI policy can restrict matter types (US-29). Context builder is limited to one matter (DATA_FLOW F4) | AI, ENG | S1 (B-4), S7 (US-29) |
| 4 | **Notification of purpose** ([s 20](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr20-)) | No (customer) | Yes | Customers must be able to describe AI processing to clients (MinLaw para 30). Verina notifies its own users | AI-use disclosure per matter (FR-9.1, US-27) covering the provider, region, retention and redaction. Plain-English description for customers' engagement letters. User privacy notice | PDPA, UX | S7 |
| 5 | **Access and correction** ([ss 21, 22, 22A](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr21-,pr22-,pr22A-); [PDP Regs regs 3–8](https://sso.agc.gov.sg/SL/PDPA2012-S63-2021): respond within 30 days or notify the time needed (reg 5); preserve a copy for ≥30 days after a refusal (reg 8)) | No. A DI may forward requests but need not (Key Concepts; GenAI AG para 10.2) | Yes (account data) | Customers must find, export, correct or annotate an individual's data held in Verina. Legal privilege is an access exception (Key Concepts para 15.30(f), Fifth Schedule; para number **to verify**) | Admin tooling: search a tenant by individual (via the redaction-map index, permission-checked); export; correct; annotate an uncorrected record (s 22(5)); preserve on refusal (s 22A). Forward requests received by Verina to the customer within 2 business days (proposed). Own DSAR process | ENG, PDPA | S7 (C-5.3) |
| 6 | **Accuracy** ([s 23](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr23-)) | No (customer) | Yes | Verina's outputs make statements about people (guarantors, signatories). A re-identification error would attribute data to the wrong person, which is both inaccurate and an unauthorised disclosure | Verification Ledger (FR-7) for assertions. OCR confidence flags (US-5). **Re-identification correctness tests**: placeholder→value round-trip and alias clusters must be lawyer-confirmable | AI, QA | S2 (round-trip tests), S6 (ledger) |
| 7 | **Protection** ([s 24](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr24-); Key Concepts ch 17; NRIC Guidelines para 2.4: a "greater level of security" for NRICs) | **Yes, directly** | Yes | Reasonable security arrangements proportionate to sensitivity. GenAI AG para 8.2: System Providers must periodically review the need for additional security as new system types appear (e.g. prompt injection) | All of [CONTROLS.md](../security/CONTROLS.md), notably: redaction + egress guard fail-closed (C-1.4); tenant/matter ACL and ethical walls (NFR-4); per-tenant keys (NFR-3); parsing sandbox; prompt-injection boundary (B-6); zero standing staff access (break-glass with customer approval, audited); T1 data never in logs | SEC (lead), AI, ENG | S1–S8 (per CONTROLS) |
| 8 | **Retention limitation** ([s 25](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr25-); Key Concepts ch 18: paras 18.13 factors for having "ceased to retain"; para 18.14 anonymisation) | **Yes, directly** | Yes | Stop retaining once the customer's purpose ends and there is no legal or business need. The customer's instruction defines the purpose period. GenAI AG para 7.3: publish a retention policy | Per-matter retention with deletion cascading to originals, text, embeddings, redaction map, drafts and audit payloads (crypto-shred; keep hashes). Backups ≤35 days (NFR-5). Legal hold. Tenant off-boarding: export then delete, with a deletion certificate. Provider ZDR (row 9). Defaults in DATA_INVENTORY §4 (PO decision Q-6) | ENG, PDPA | S3 (design per roadmap) |
| 9 | **Transfer limitation** ([s 26](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr26-); [PDP Regs regs 9–12](https://sso.agc.gov.sg/SL/PDPA2012-S63-2021); Key Concepts ch 19) | Not directly (s 4(2)), but the customer is liable for transfers its DI makes (Key Concepts p 26) | Yes (own data) | Before any transfer outside SG, the recipient must be bound by legally enforceable obligations of comparable protection (reg 10(1)). A contract must require comparable protection **and specify the countries** (reg 11(2)). For a DI recipient it must cover at least **protection, retention limitation and breach notification** (Key Concepts para 19.9 table). Alternatively a specified certification: for a DI recipient, APEC PRP or CBPR, or Global PRP or CBPR (reg 12(2)(a), as amended by S 86/2026 w.e.f. 2 Mar 2026). ASEAN Model Contractual Clauses are recognised (para 19.10). "Data in transit" is deemed compliant (reg 10(2)(d)) only if no organisation accesses or uses the data in transit, so inference is **not** data in transit | SG-region storage and processing by default (NFR-2, C-2.1). Model route chosen with a reg 11/12 basis **before** go-live (S2). Processing country recorded per call and shown per matter (C-2.2). Sub-processor list with countries published to customers. No sub-processor outside SG without a reg 11/12 basis. Region-pinning policy as code | PDPA, SEC, PO | S2 (model route), S1 (other vendors, C-2.3) |
| 10 | **Data breach notification** ([ss 26A–26E](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr26A-,pr26B-,pr26C-,pr26D-,pr26E-); [DBN Regs 2021](https://sso.agc.gov.sg/SL/PDPA2012-S64-2021); Key Concepts ch 20) | **Yes**: notify the customer "without undue delay" once there is reason to believe a breach occurred (s 26C(3)(a); Key Concepts para 20.7: from credible grounds). The DI does not assess or notify PDPC (para 20.8) | Yes: assess; notify PDPC ≤3 calendar days after assessing a breach as notifiable (s 26D(1)); notify individuals (s 26D(2)) | **Notifiable** = likely significant harm (deemed for name or ID number + prescribed data, DBN reg 3 + Schedule) or significant scale (≥500 individuals, reg 4). The customer should normally finish its assessment within 30 days (para 20.4) and then has 3 calendar days for PDPC. Breaches only within an organisation are not notifiable (s 26B(4)). Encryption can trigger the technological-protection exception for notifying individuals (s 26D(5)(b); para 20.30) | Incident response plan with a DI path. **Contractual SLA (proposed): initial notice to the customer ≤24h after credible grounds; DBN reg 5 particulars as available within 72h; daily updates.** Per-incident query of which tenants, matters, PII categories and tiers were affected, using the taxonomy to support the customer's harm assessment. Provider must notify Verina ≤24h (DPA checklist). Encryption at rest with tenant keys. Annual tabletop drill | SEC (lead), PDPA | S1 (IR plan v0), S8 (drill) |
| 11 | **DI contract precondition** (s 4(2): "contract which is evidenced or made in writing") | **Yes**: conditions the whole DI position | — | Without written terms Verina has full organisation obligations for customer data | Customer-facing processing terms (Verina DPA): scope and instructions, the three DI duties, customer-assist duties for rows 2–6, sub-processors and countries, deletion, audit, breach SLA. Must be signed before any pilot data | PDPA, PO | Draft S4, signed before S8 pilot |
| 12 | **Penalties** ([s 48J](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr48J-)): up to 10% of annual SG turnover for organisations with turnover above S$10m, otherwise up to S$1m | Yes | Yes | The exposure is material, and customers will push liability onto Verina in contract | Liability allocation in the customer DPA; insurance (PO) | PO | S7 |
| 13 | **Data portability** (Part 6B) | Excluded for DI processing (s 4(2)) | Commencement status **to verify** | Low for MVP | Full export (NFR-16) supports it anyway | PDPA | — |

## 4. Legal professional privilege and confidentiality

Verina processes privileged and confidential material: client instructions, draft advice and redlines. The PDPA is not the binding constraint here. Confidentiality and privilege are.

- **Sources.** [Evidence Act 1893 s 128](https://sso.agc.gov.sg/Act/EA1893?ProvIds=pr128-) covers advocates and solicitors; [s 128A](https://sso.agc.gov.sg/Act/EA1893?ProvIds=pr128A-) covers legal counsel in an entity, but only communications for the purpose of seeking legal advice (s 128A(2)(c)–(d)); [s 131](https://sso.agc.gov.sg/Act/EA1893?ProvIds=pr131-) covers confidential communications with a legal professional adviser. Under [PCR 2015 r 6(2)](https://sso.agc.gov.sg/SL/LPA1966-S706-2015?ProvIds=pr6-) a lawyer "must not knowingly disclose" client-confidential information. [PDPA s 4(6)(a)](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr4-) preserves legal privilege, and Key Concepts para 15.30(f) lists privileged personal data as an access exception.
- **The MinLaw Guide** (para 21) says r 6 "does not prohibit the use of GenAI provided that appropriate safeguards are implemented". Verina's job is to be that safeguard, provably.
- **Waiver risk.** Whether privilege survives disclosure to a technology service provider acting under confidentiality is **to verify** against Singapore authority. No case was checked in this pass. Provider confidentiality, access restrictions and purpose limits are proposed safeguards; they do not establish that privilege is preserved. That conclusion remains for Singapore-qualified counsel on the actual facts and terms.

Product implications:

1. **Zero standing access by Verina staff** to matter content. Break-glass only with time-boxed, customer-approved grants, audited and visible to the customer.
2. **No human review at the model provider.** That includes abuse-monitoring review. Otherwise there must be a contractual exclusion or a PO-recorded exception (DPA checklist item 4).
3. **Privileged/non-privileged separation in outputs:** counterparty-tone comments carry no internal analysis (US-16); the requester status page shows stage, lawyer and date only (US-4); internal margin comments are stripped before external export.
4. **In-house tenants:** business requesters' submissions may not attract s 128A protection unless made to seek legal advice. Label intake channels and avoid implying privilege in the UI.
5. **Audit packs** (FR-9.4) contain privileged content. Mark them "Privileged & Confidential", control their export and watermark them.
6. **Compelled disclosure:** the customer DPA must commit Verina to notify the customer of any legal demand for its data (unless prohibited), to resist overbroad demands, and to disclose the minimum.
7. **Ethical walls** (NFR-4) and the conflict-check record (FR-1.3) support r 6 and conflict duties. AI context must respect walls: no cross-matter retrieval.
8. **Legal hold** must override retention deletion (row 8).

## 5. MinLaw Guide for Using GenAI in the Legal Sector (6 Mar 2026)

Source: [MinLaw launch release](https://www.mlaw.gov.sg/launch-of-guide-for-using-generative-artificial-intelligence-in-the-legal-sector/) and [Guide PDF](https://www.mlaw.gov.sg/files/Final_Ver__Guide_for_using_Generative_AI_in_the_Legal_Sector.pdf). It is guidance, not law, but it provides a relevant assessment framework; actual customer requirements must be confirmed.

| Principle (Guide) | What the Guide expects | Verina implication | Where |
| --- | --- | --- | --- |
| **Professional ethics**: professionals "remain ultimately responsible for all work products" | Knowledge, skill, judgement; verify outputs | Verification Ledger and export gate; drafts labelled until sign-off; the attesting lawyer is named; no autonomous sending | FR-7, FR-8, US-19–23 |
| **Confidentiality** (s 3.2, paras 21–24): prefer enterprise tools with assurances (23(b)); review ToS on retention and training (23(c)); for enterprise COTS, check data handling, no training, controls, DPAs (23(e)(i)–(ii)); data residency (23(e)(iii), fn 18); deletion on request (23(e)(iv)); SOC 2 / ISO 27001, SSO/MFA, model isolation, incident response (23(e)(v)); anonymise with placeholders "[Party A], [Company B]" and document them (23(d)(ii)) | Customers will run this checklist against Verina **and** its model provider | Publish a **provider assurance sheet** that answers each 23(e) item, for Verina and for the model provider. Redaction with documented placeholders (PII_TAXONOMY). SG residency shown per matter (C-2.2). Deletion on request (row 8). NFR-12 certifications. Fn 18 refers to the Law Society's Guidance Note 3.4.1 on cloud computing (content **to verify**) | NFR-1, -2, -12; US-7; C-1.x |
| **Transparency** (s 3.3, paras 25–30): consider disclosing GenAI use where it is substantial (27(a)), affects cost (27(b)) or conflicts with client data preferences (27(c)). Explain tools, stage, who and verification (30(b)); responsibility (30(c)); safeguards (30(d)); contact channel (30(e)); **option to opt out** (30(f)) | Contract review in Verina is "substantial" use, so disclosure will usually be expected | The disclosure template (US-27) must cover 30(b)–(e). Add a **per-matter "AI off" switch** that the orchestrator enforces, so firms can honour a client opt-out (30(f)) (Q-12). Annex C sample engagement-letter clause: verbatim vs editable is the existing S7 PO decision | FR-9.1, US-27, US-29 |

## 6. Redaction, pseudonymisation and the external model call

- **Position.** The F6 payload ([DATA_FLOW](../security/DATA_FLOW.md) §4) is personal data while the redaction map exists and context can re-identify people. Sources: PDPA s 2 limb (b); the Guide to Basic Anonymisation (de-identification is "only the first step"); MinLaw para 23(d)(ii) note.
- **Consequences.** The provider is a sub-processor handling personal data. The TLO applies if it processes outside SG. The DPA must contain the DI-minimum terms (Key Concepts para 19.9). The breach clause must cover prompt and output data.
- **Residual risk the PO is asked to accept (Q-8).** Commercial terms (prices, caps, scope) are not redacted, because the review needs them. They reach the provider under ZDR and no-training terms. The firm AI policy and the disclosure must say so (DATA_FLOW §4 item 5).
- **No unredacted path in MVP** (recommended). Any exception must be recorded by the PO per AGENTS.md, scoped to a tenant, time-limited, and visible in the matter's disclosure (Q-9).
- **Detection is local.** A cloud PII-detection API would itself be an unredacted egress (PII_TAXONOMY §8).

## 7. PDPC Advisory Guidelines on Use of Personal Data in Generative AI (20 Jul 2026)

| Para | Requirement or good practice | Verina response |
| --- | --- | --- |
| 6.3 | Be clear about your role in each context | §2 of this document |
| 7.1, 7.4–7.5 | Model provider is a DI for inference; an organisation if it uses prompts for development; good practice to document access controls, residency, retention, incident procedures | DPA checklist items 3, 6, 9, 12; request the provider's documentation in the S2 review |
| 8.1–8.3 | System Provider as DI. Review security periodically (prompt injection). Share safeguards with deployers: residency, retention, input/output filters, leakage-testing metrics, incident timelines. The example is a legal summarisation API that publishes redaction rates | Safeguards sheet (row 1). Publish redaction recall/precision from the Gate 1 test set. Re-baseline threat model per release |
| 9.1–9.4 | Deployer (customer) responsibilities: purpose specification; guidance to users on what personal data to input; written policies | Firm AI policy settings (FR-9.3) with matter-type restrictions; in-product guidance on intake; customer policy template (S7) |
| 9.5 | Agentic features increase risk; human escalation | Human checkpoints at irreversible steps; no autonomous sending (guardrails) |
| 10.2–10.5 | Access/correction: DI may forward requests; RAG stores should be searchable and correctable | Row 5 tooling covers pgvector content per individual |

The [Advisory Guidelines on Use of Personal Data in AI Recommendation and Decision Systems](https://www.pdpc.gov.sg/organisations/regulations-decisions/regulatory-guidance/advisory-guidelines-on-use-of-personal-data-in-ai-recommendation-and-decision-systems) (1 Mar 2024) are cross-referenced by the GenAI guidelines. Their detailed paragraphs were **not reviewed** in this pass (to verify in S2).

## 8. Model route: PDPA inputs to the S2 decision

The PO decides in S2 (roadmap: "Anthropic API ZDR vs Bedrock/Vertex in-region"). Counsel's criteria, in priority order:

1. **Inference and any transient storage in Singapore.** This avoids the TLO for customer data and matches NFR-2 and MinLaw 23(e)(iii). Whether Claude models are served from a Singapore region on each route, without cross-region routing, is **to verify** with each provider's current documentation and contract.
2. If processing outside SG is unavoidable, a **reg 11 contract** naming the countries, or **reg 12 certification** of the provider. The countries must be disclosed to customers and recorded per call.
3. **Zero data retention and no training**, contractually (NFR-1), with no human review of content.
4. The remaining items of [MODEL_PROVIDER_DPA_CHECKLIST.md](MODEL_PROVIDER_DPA_CHECKLIST.md).

Until a route passes, development uses fake model clients only (DATA_FLOW §5.3).

## 9. Controls this assessment adds to CONTROLS.md (for verina-security to merge)

| Proposed id | Control | Owner | Sprint |
| --- | --- | --- | --- |
| P-1 | Written customer processing terms in place before any customer data (s 4(2)) | PDPA/PO | before S8 pilot |
| P-2 | Verina DPO designated and BCI published (s 11(3), (5)) | PO | S1 |
| P-3 | Zero standing staff access to matter content; break-glass with customer approval and audit | SEC/ENG | S1 |
| P-4 | Individual-centric search/export/correct/annotate tooling for customer access and correction requests | ENG | S7 |
| P-5 | DI breach notice to customer ≤24h, with DBN reg 5 particulars as available | SEC/PDPA | S1 (plan), S8 (drill) |
| P-6 | Per-matter AI opt-out enforced by the orchestrator | AI/ENG | S7 |
| P-7 | Re-identification round-trip and alias-cluster tests | AI/QA | S2 |
| P-8 | Sub-processor register with countries and transfer basis, published to customers | PDPA | S2 |
| P-9 | Legal hold overrides retention deletion | ENG | S3 |
| P-10 | Legal-process (compelled disclosure) handling procedure | PDPA/PO | S7 |

## 10. Open questions for the PO

| # | Decision needed | Counsel's recommendation | Needed by |
| --- | --- | --- | --- |
| Q-1 | Who is Verina's DPO, and how is their BCI published? | Named individual; publish on BizFile+ and the website | S1 |
| Q-2 | Verina's contracting entity and the customer DPA / processing terms (s 4(2)) | Counsel drafts in S4; PO approves | S4 draft, S8 signed |
| Q-3 | Model route and processing country | SG-region inference with ZDR and no training. Otherwise reg 11 contract + per-matter disclosure | S2 |
| Q-4 | If the provider retains prompts for abuse monitoring or allows human review, accept as an exception? | No. Require a ZDR / human-review exclusion; anything less is a PO-recorded exception | S2 |
| Q-5 | Gate 1 redaction targets (T1 recall ≥0.99 etc., PII_TAXONOMY §8) | Approve as proposed | S1 |
| Q-6 | Default retention: matter content after closure, email-intake non-matters, audit payloads, account data | See DATA_INVENTORY §4 proposals | S3 |
| Q-7 | Pseudonymise counterparty names by default? | Yes by default; firm may relax | S1 |
| Q-8 | Accept that commercial terms (amounts, caps, scope) reach the provider unredacted under ZDR? | Accept, disclosed in firm AI policy and AI-use disclosure | S2 |
| Q-9 | Any lawyer-approved unredacted-call path in MVP? | No | S2 |
| Q-10 | Public-agency customers in scope (s 26E)? | Out of MVP scope | S1 |
| Q-11 | Email intake: senders and recipients who are not customer users. Keep non-converted emails how long? | Delete after 30 days if not converted to a matter | S2 |
| Q-12 | Add a story for the per-matter AI opt-out (MinLaw para 30(f))? | Yes, S7 alongside US-27/US-29 | S3 (backlog) |
| Q-13 | Pursue certification later (DPTM, or APEC/Global PRP under reg 12)? | Consider after SOC 2/ISO (NFR-12) | S8+ |
| Q-14 | Do Verina staff ever need content access for support? | Break-glass only (P-3) | S1 |
| Q-15 | Customer breach-notice SLA (proposed ≤24h initial) | Approve | S1 |
| Q-16 | Verify the "to verify" legal points with external counsel or primary sources: privilege waiver on disclosure to tech providers; consent exceptions for legal services; Fifth Schedule paragraph numbers; Part 6B commencement; Law Society GN 3.4.1 | Counsel resolves in S1; PO confirms | S1 |

## 11. Sources (retrieved 13 Oct 2026)

| Source | Link | Used for |
| --- | --- | --- |
| Personal Data Protection Act 2012 (current at 13 Oct 2026) | https://sso.agc.gov.sg/Act/PDPA2012 | ss 2, 4, 11–26E, 48D–48F, 48J |
| Personal Data Protection Regulations 2021 (S 63/2021, current timeline includes S 86/2026 and S 580/2026; scope review pending) | https://sso.agc.gov.sg/SL/PDPA2012-S63-2021 | Access/correction regs 3–8; transfer regs 9–12 |
| PDP (Notification of Data Breaches) Regulations 2021 (S 64/2021) | https://sso.agc.gov.sg/SL/PDPA2012-S64-2021 | Significant harm (reg 3, Schedule), scale (reg 4), contents (regs 5–6) |
| PDPC Advisory Guidelines on Key Concepts in the PDPA (revised 29 Apr 2026) | https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/advisory-guidelines/ag-on-key-concepts/advisory-guidelines-on-key-concepts-in-the-pdpa-17-may-2022.pdf | DI concepts, chs 15, 17–21 |
| PDPC Advisory Guidelines on the PDPA for NRIC and other National Identification Numbers (31 Aug 2018) | https://www.pdpc.gov.sg/-/media/Files/PDPC/PDF-Files/Advisory-Guidelines/Advisory-Guidelines-for-NRIC-Numbers---310818.pdf | NRIC treatment |
| PDPC Guide to Basic Anonymisation (31 Mar 2022) | https://www.pdpc.gov.sg/News-and-Events/Announcements/2022/03/Guide-to-Basic-Anonymisation-Now-Available (PDF text read from a mirror; the PDPC-hosted PDF link could not be retrieved, **to verify**) | De-identification vs anonymisation; pseudonym mapping |
| PDPC Advisory Guidelines on Use of Personal Data in Generative AI (20 Jul 2026) | https://www.pdpc.gov.sg/organisations/regulations-decisions/regulatory-guidance/advisory-guidelines-on-use-of-personal-data-in-generative-ai | Stakeholder roles, paras 6–10 |
| MinLaw Guide for Using GenAI in the Legal Sector (6 Mar 2026) | https://www.mlaw.gov.sg/files/Final_Ver__Guide_for_using_Generative_AI_in_the_Legal_Sector.pdf | Principles; paras 21–30 |
| Evidence Act 1893 ss 128, 128A, 131 | https://sso.agc.gov.sg/Act/EA1893?ProvIds=pr128-,pr128A-,pr131- | Privilege |
| Legal Profession (Professional Conduct) Rules 2015 rr 5, 6 | https://sso.agc.gov.sg/SL/LPA1966-S706-2015?ProvIds=pr5-,pr6- | Honesty, confidentiality |
| ICA media release, M-series FIN | https://www.ica.gov.sg/news-and-publications/newsroom/media-release/new-m-fin-series-to-be-introduced-from-1-january-2022 | NRIC/FIN format |

## 12. Change log

| Version | Date | Change | Author |
| --- | --- | --- | --- |
| v0 | 2026-10-13 | Initial assessment | verina-pdpa-counsel |
