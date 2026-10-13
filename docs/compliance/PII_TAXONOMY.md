# PII taxonomy and redaction rules (v0)

> **13 Oct 2026 review:** this remains a design-time draft requiring named lawyer review and PO acceptance. [SOURCE_REVIEW.md](SOURCE_REVIEW.md) records the actual source coverage and unresolved version/paragraph checks. [REDACTION_COMPATIBILITY.md](REDACTION_COMPATIBILITY.md) records implementation gaps; the taxonomy is not a live-egress approval.


| | |
| --- | --- |
| Version | 2026-10-13.v0 (Sprint 0, task T0.4 / EN-5) |
| Owner | verina-pdpa-counsel (rules) · verina-ai-engineer (detector implementation, US-7) · verina-security (egress guard) |
| Status | **Draft.** The PO must sign it off in S1 before it becomes the S2 redaction rule-set (US-7, FR-2.4, Gate 1). |
| Machine-readable | [`pii-taxonomy.json`](pii-taxonomy.json) is canonical. If this page and the JSON disagree, the JSON wins and this page must be fixed. |
| Related | [PDPA_ASSESSMENT.md](PDPA_ASSESSMENT.md) · [DATA_INVENTORY.md](DATA_INVENTORY.md) · [`../security/DATA_FLOW.md`](../security/DATA_FLOW.md) §4 (redaction point F5 → F6) |

This is a design document for attorney review, not legal advice. Items marked **to verify** could not be confirmed from a primary source.

## 1. Purpose and scope

Verina replaces personal data and client-identifying information with placeholders **inside the tenant** before any external model call (DATA_FLOW F5). The egress guard then re-scans the final payload and fails closed (F6). This page sets out:

- what to detect;
- how to detect it (regex, checksum, context, local NER);
- what to do with it (pseudonymise, mask, drop, block, keep);
- whether the value may be re-identified, and where the mapping is stored.

**Legal anchors**
- "Personal data" is data about an individual who can be identified from that data, or from that data plus other information the organisation has or is likely to have access to ([PDPA s 2](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr2-)).
- Security must be proportionate to the sensitivity of the data ([PDPA s 24](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr24-); [Advisory Guidelines on Key Concepts](https://www.pdpc.gov.sg/-/media/files/pdpc/pdf-files/advisory-guidelines/ag-on-key-concepts/advisory-guidelines-on-key-concepts-in-the-pdpa-17-may-2022.pdf), revised 29 Apr 2026, paras 17.2–17.3).
- The sensitivity tiers are product policy, informed by the data the [PDP (Notification of Data Breaches) Regulations 2021](https://sso.agc.gov.sg/SL/PDPA2012-S64-2021) prescribe as causing "significant harm" (reg 3 and the Schedule).
- National ID numbers follow the [PDPC NRIC Advisory Guidelines](https://www.pdpc.gov.sg/-/media/Files/PDPC/PDF-Files/Advisory-Guidelines/Advisory-Guidelines-for-NRIC-Numbers---310818.pdf) (31 Aug 2018). PDPC's guidelines page reportedly says they will be updated after the MDDI statement of 13 Dec 2024 and remain valid until then. We saw this only in a search snippet, so it is **to verify**.

**Pseudonymised is not anonymised.** While the mapping exists, a placeholdered prompt is still personal data in Verina's hands. The PDPC [Guide to Basic Anonymisation](https://www.pdpc.gov.sg/News-and-Events/Announcements/2022/03/Guide-to-Basic-Anonymisation-Now-Available) (31 Mar 2022) says de-identification "is only the first step of anonymisation". It also requires the "identity mapping table for pseudonyms" to be safeguarded. Context in a contract can still identify people: the MinLaw Guide notes that "anonymised content may still be identifiable with sufficient context" (para 23(d)(ii)). Redaction therefore **reduces** risk. It does not take model calls outside the PDPA (see PDPA_ASSESSMENT §6).

## 2. Sensitivity tiers

| Tier | Name | What falls in it | Basis |
| --- | --- | --- | --- |
| **T1** | Restricted | National ID numbers (NRIC, FIN, passport, birth certificate, work permit, foreign IDs); bank account and card numbers; an individual's financial data; health data; minors' data; prescribed highly sensitive data; credentials, private keys and biometrics | DBN Regs reg 2 ("identification number"), reg 3, Schedule Part 1; NRIC Guidelines paras 1.3–1.5, 2.4 |
| **T2** | Sensitive | Personal phone and email, residential address, date of birth, vehicle number, account/reference ids, signatures, special attributes (policy) | Direct contact/location identifiers and quasi-identifiers |
| **T3** | Personal | Names, business contact information, online identifiers | PDPA s 2; s 4(5) (business contact information is excluded from Parts 3–6A but is still confidential) |
| **C** | Client-confidential (not personal data) | Client and counterparty organisation names, UEN, file references, deal code names | Not personal data (unless a sole proprietor). Confidential under [PCR 2015 r 6](https://sso.agc.gov.sg/SL/LPA1966-S706-2015?ProvIds=pr6-) and [Evidence Act 1893 ss 128, 128A](https://sso.agc.gov.sg/Act/EA1893?ProvIds=pr128-,pr128A-); FR-2.4 |

A tier can rise: once any identifier of a person is linked to T1 data (for example, a minor), all of that person's identifiers are handled as T1.

## 3. Actions

| Action | What happens to the model payload | Re-identification | Mapping store |
| --- | --- | --- | --- |
| **PSEUDONYMISE** | Span → stable typed placeholder, e.g. `[PERSON_1]` | Yes. Inside the tenant, at render/export, for users with matter access | Tenant redaction map |
| **MASK** | Span → typed placeholder | **No** re-insertion into AI output; the UI shows "value withheld — see source" | None (the original stays only in the original document) |
| **DROP** | Span or object removed; neutral marker `[OMITTED_<TYPE>]` | No | None |
| **BLOCK** | Excerpt not sent to any external model; matter flagged; audit event | n/a | None. Matter approval must satisfy firm policy and be logged; any unredacted external egress additionally requires the explicit recorded PO exception required by AGENTS.md |
| **KEEP** | Not redacted (public bodies, statutes, case citations, contract dates, corporate amounts) | n/a | n/a |

## 4. Placeholder rules

1. **Format** `[<TYPE>_<n>]` (validator regex in the JSON). `n` counts from 1 per type, in order of first appearance in the **matter**.
2. **Stable within a matter.** The same normalised value gets the same placeholder in every model call on that matter. "Tan Ah Kow", "Mr Tan" and "Ah Kow" form one alias cluster and share `[PERSON_1]`. The lawyer can merge or split clusters in the redaction review screen.
3. **Never stable across matters or tenants.** This prevents cross-matter linkage.
4. **Normalisation:** NRIC uppercase with no spaces; phones in E.164; emails lowercase; organisations with and without suffix ("Pte. Ltd.") plus defined short names form one cluster.
5. **Collision escape.** If the source already contains text shaped like a placeholder, escape it before redaction and restore it after re-identification.
6. **Placeholders reveal only the category**, never any character of the value. There are no partial masks such as `S****567D` in model payloads.
7. **Role-bearing org placeholders** (`ORG_CLIENT`, `ORG_COUNTERPARTY`, `ORG`) keep the model's analysis intact. This follows the MinLaw Guide's own placeholder pattern ("[Party A], [Company B]", para 23(d)(ii)). The Guide also suggests documenting the placeholders used, which Verina does in the audit event (count by type; never values).

## 5. Re-identification and the mapping

- **Store:** the tenant redaction map, in the tenant database in the Singapore region, encrypted with the tenant data key (DATA_FLOW F5; "Redaction map" in §5.1). It is crypto-shredded when the matter is deleted.
- **Never:** sent to a model provider or any external service; written to application logs, telemetry or error reports; included in audit metadata; shared across matters or tenants; readable by Verina staff without a customer-approved, time-boxed, audited support grant. The implemented audit boundary stores registered metadata and hashes, not prompts, model outputs or mapping values ([ADR 004](../adr/004-durable-audit-chain.md)). A separate encrypted evidence store is unbuilt and requires its own reviewed purpose, access, retention and deletion design.
- **Audit privacy and retention:** opaque identifiers and hashes may still be personal or confidential when linkable. The metadata-only schema is not a PII detector or proof of anonymisation; retention, identifying linkage, legal holds and backup expiry remain open design work. Tenant administration grants no implicit access to matter metadata; requester access is limited to the reviewed coarse status projection.
- **When:** at render or export time, for a user who passes the matter ACL and ethical-wall checks (NFR-4).
- **Offence awareness:** an individual who re-identifies anonymised information without authorisation may commit an offence ([PDPA s 48F](https://sso.agc.gov.sg/Act/PDPA2012?ProvIds=pr48F-)). Unauthorised disclosure or improper use by individuals is covered by ss 48D–48E. These go into staff training (PDPA_ASSESSMENT, accountability row).

## 6. Category table

The detection details (regex, context keywords, NER labels) are in the JSON. Examples are **synthetic**. Any well-formed NRIC/FIN may belong to a real person, so use them only with fictional names in fixtures.

| # | Category (JSON `id`) | Placeholder | Tier | Detection | Synthetic example | Default action | Re-id? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Person name (`person_name`) | `PERSON` | T3 (↑T1 if minor/T1-linked) | Intake dictionary + local NER (PERSON) + honorific/signature-block regex + coreference. Handles Malay (bin/binte), Indian (s/o, d/o, a/l, a/p) and Chinese name orders | Mr Tan Ah Kow; Mdm Siti binte Ahmad | PSEUDONYMISE | Yes |
| 2 | NRIC / FIN (`nric_fin`) | `NRIC` | T1 | Regex `[STFGM]` + 7 digits + letter (spaces/hyphens tolerated), partial/masked forms; **checksum** (§7) raises confidence; context ("NRIC", "FIN", "I/C") | S1234567D; T1234567J; SXXXX567D | PSEUDONYMISE | Yes |
| 3 | Other SG ID numbers (`other_sg_identity_number`) | `ID_NUMBER` | T1 | Context-led regex (birth certificate, work permit, pass no.). Formats **to verify** | Work Permit No: 012345678 | PSEUDONYMISE | Yes |
| 4 | Passport (`passport_number`) | `PASSPORT` | T1 | SG `[EK]`+7 digits+letter (**to verify**); generic by context | K1234567A | PSEUDONYMISE | Yes |
| 5 | Foreign national ID (`foreign_national_id`) | `ID_NUMBER` | T1 | MyKad `YYMMDD-PB-####` (**to verify**); generic by context | 900101-14-5678 | PSEUDONYMISE | Yes |
| 6 | Phone (`phone_number`) | `PHONE` | T2 | `+65`/`(65)`/`0065` optional + 8 digits starting 3/6/8/9 (**to verify** against IMDA numbering plan); 1800/1300; international `+CC`; bare 8 digits only with context | +65 9123 4567; (65) 6123-4567 | PSEUDONYMISE | Yes |
| 7 | Email (`email_address`) | `EMAIL` | T2 (T3 if business) | Regex | tan.ahkow@example.com | PSEUDONYMISE | Yes |
| 8 | Address incl. postal code (`residential_address`) | `ADDRESS` | T2 | NER (ADDRESS/LOC/FAC) + regex: "Singapore 123456", Blk, `#05-67` unit, street suffixes. A 6-digit postal code counts only with address context (sector range **to verify**). Whole address = one placeholder | Blk 123 Example Avenue 4 #05-67 Singapore 560123 | PSEUDONYMISE | Yes |
| 9 | Bank account / IBAN (`bank_account`) | `BANK_ACCOUNT` | T1 | Context ("A/C", "account no.", "beneficiary") + digits; IBAN regex. SWIFT/BIC and bank names are KEEP | Account No.: 123-456789-0 | PSEUDONYMISE | Yes |
| 10 | Card number (`payment_card`) | `CARD` | T1 | 13–19 digits with separators + **Luhn** | 4111 1111 1111 1111 (network test number) | **MASK** | **No** |
| 11 | Date of birth / age (`date_of_birth`) | `DOB` | T2 (↑T1 if <18) | DOB/age context only. Other contract dates are KEEP | Date of Birth: 01/02/1980 | PSEUDONYMISE | Yes |
| 12 | Minor (`minor_flag`) | `MINOR` | T1 | Derived: age <18 from DOB, or minor keywords → elevate the person cluster; matter flag `minor_data_present` | "the infant, [PERSON_2]" | PSEUDONYMISE + flag | Yes |
| 13 | Health (`health_information`) | `HEALTH_INFO` | T1 | Local medical lexicon + NER + context; the category placeholder keeps the clause analysable | diagnosed with type 2 diabetes | PSEUDONYMISE | Yes |
| 14 | Prescribed highly sensitive (`special_category_prescribed`) | `RESTRICTED` | T1 | Lexicon + context for DBN Schedule Part 1 items 5, 6, 6A, 6B, 18–23 (CYPA/VAA matters, sexual-offence victims, specified conditions, suicide, abuse, adoption) | history of substance addiction | **BLOCK** + matter flag | No |
| 15 | Individual's financial data (`personal_financial`) | `PERSONAL_FINANCIAL` | T1 | Amount + remuneration/net-worth/debt context, tied to an individual. Corporate prices, fees and caps are KEEP | a monthly salary of S$8,500 | PSEUDONYMISE | Yes |
| 16 | Credentials and secrets (`credentials_secrets`) | `SECRET` | T1 | Regex (password:, private-key header, api/token keys) + entropy | Password: Example#2026 | **DROP** | No |
| 17 | Signatures (`signature_image`) | `SIGNATURE` | T2 | Document structure / image classifier. Images are never sent to a model | embedded signature image | **DROP** | No |
| 18 | Photos, ID scans, biometrics (`photo_biometric`) | `IMAGE` | T1 | Document structure / image classifier. OCR is local; OCR text goes through the text rules | scanned NRIC in an annex | **DROP** | No |
| 19 | Vehicle number (`vehicle_registration`) | `VEHICLE` | T2 | `S[A-Z]{1,2} ####[A-Z]` (**to verify**) + context | SBA 1234 A | PSEUDONYMISE | Yes |
| 20 | Account/reference ids (`account_or_reference_id`) | `ACCOUNT_ID` | T2 | Context (employee/customer/policy/CPF/tax ref) + id | Employee ID: E-00123 | PSEUDONYMISE | Yes |
| 21 | Online identifiers (`online_identifier`) | `ONLINE_ID` | T3 | IPv4, social-profile URLs (mainly email-intake headers) | 192.0.2.10 | PSEUDONYMISE | Yes |
| 22 | Special attributes (`special_attributes_policy`) | `SENSITIVE_ATTR` | T2 | Lexicon (race, religion, orientation, politics, adult criminal record). **Policy category**: the PDPA has no statutory "special categories" | — | PSEUDONYMISE | Yes |
| 23 | Client organisation (`org_client`) | `ORG_CLIENT` | C | Intake record + NER (ORG) + company-suffix regex (Pte. Ltd., LLP, Sdn. Bhd., …) | Example Holdings Pte. Ltd. | PSEUDONYMISE | Yes |
| 24 | Counterparty organisation (`org_counterparty`) | `ORG_COUNTERPARTY` | C | As above, role from the intake record | Acme Cloud Services Inc. | PSEUDONYMISE (firm-configurable, Q-7) | Yes |
| 25 | Other organisations (`org_other`) | `ORG` | C | NER + suffix regex. Public bodies, courts, regulators, SIAC/SIMC are **KEEP** (`keep_list_public_bodies`) | Example Logistics Pte Ltd | PSEUDONYMISE | Yes |
| 26 | UEN (`uen`) | `UEN` | C | ROB `########X`, local company `YYYY#####X`, others `[TSR]YY`+entity type+`####X` (**to verify**); context "UEN", "Co. Reg. No." Business identifier, not personal data, but a sole-proprietor UEN can identify an individual | UEN 202612345A | PSEUDONYMISE | Yes |
| 27 | File refs / matter names (`matter_reference`) | `REFERENCE` | C | Intake dictionary + "Our/Your Ref" regex | Our Ref: ABC/2026/0142 | PSEUDONYMISE | Yes |

**Always KEEP** (needed for the review and the Verification Ledger): statute names and section numbers; case citations and case names within citations; contract dates other than DOB; governing law, forum and place names; corporate amounts, fees, caps and percentages; defined terms that are not names; public bodies on the keep list.

## 7. NRIC/FIN checksum (confidence signal only)

ICA confirms the format: prefix S/T (citizens and PRs) or F/G/M (foreigners), seven digits and a checksum letter ([ICA, M-series release](https://www.ica.gov.sg/news-and-publications/newsroom/media-release/new-m-fin-series-to-be-introduced-from-1-january-2022)). ICA does **not** publish the checksum algorithm. The widely documented community algorithm is:

```
weights = [2,7,6,5,4,3,2]
offset  = {S:0, F:0, T:4, G:4, M:3}
r       = (sum(d[i] * weights[i]) + offset[prefix]) mod 11
letter  = S/T: "JZIHGFEDCBA"[r]   F/G: "XWUTRQPNMLK"[r]   M: "XWUTRQPNJLK"[r]
```

**To verify:** the M-series table. ICA's illustrative example `M1234567B` does not validate under it. Design rule: **a pattern hit is redacted whether or not the checksum validates.** A valid checksum or a context keyword only raises confidence from medium to high. Partial NRICs (last 3 digits + letter) are still personal data where identifiable (NRIC Guidelines para 5.3), so masked forms are detected too.

## 8. Detection pipeline (all local)

All detection runs **inside the tenant**. No external API, including the model provider, may be used to find PII, because that would itself be an unredacted egress.

1. Intake dictionary (parties, signatories, contacts, matter name).
2. Regex + checksum candidates.
3. Context window (about ±40 characters) adjusts confidence.
4. Local NER model (PERSON, ORG, ADDRESS/LOC, DATE) + local lexicons (health, prescribed categories).
5. Coreference / alias clustering.
6. **Lawyer review of the placeholder list** before the first model call on a matter (US-7). Additions and removals are audit-logged.
7. **Egress guard**: an independent second detector over the final serialised request. Any residual T1 pattern candidate (even with a failed checksum), T2 high-confidence hit, or unplaceholdered intake-dictionary value blocks the call (DATA_FLOW §4; CONTROLS C-1.4).

**Bias:** over-redact. Medium-confidence hits are redacted automatically and surfaced for review. Low-confidence hits are suggestions only.

**Proposed Gate 1 targets** (PO to approve, Q-5), measured on the synthetic SG PII test set:

| Tier | Minimum recall |
| --- | --- |
| T1 | 0.99 |
| T2 | 0.97 |
| T3 | 0.95 |
| C | 0.97 |

Overall precision must be at least 0.85. The 2026 PDPC GenAI Guidelines give a legal-summarisation provider as an example of good practice: it documents input redaction filters and "the rate at which personal identifiers are detected and redacted" ([AG on Use of Personal Data in Generative AI](https://www.pdpc.gov.sg/organisations/regulations-decisions/regulatory-guidance/advisory-guidelines-on-use-of-personal-data-in-generative-ai), 20 Jul 2026, para 8.3 example). Verina should publish these metrics to customers.

## 9. Worked example (synthetic)

Source (intake: client = Example Holdings Pte. Ltd.; counterparty = Acme Cloud Services Inc.):

> This Agreement is made between Example Holdings Pte. Ltd. (UEN 202612345A) ("Customer") and Acme Cloud Services Inc. ("Supplier"). Notices to the Customer: Attn Mr Tan Ah Kow, tan.ahkow@example.com, +65 9123 4567. Guarantor: Tan Ah Kow (NRIC S1234567D) of Blk 123 Example Avenue 4 #05-67 Singapore 560123. Liability is capped at S$500,000 under clause 12.

Payload after F5:

> This Agreement is made between [ORG_CLIENT_1] (UEN [UEN_1]) ("Customer") and [ORG_COUNTERPARTY_1] ("Supplier"). Notices to the Customer: Attn [PERSON_1], [EMAIL_1], [PHONE_1]. Guarantor: [PERSON_1] (NRIC [NRIC_1]) of [ADDRESS_1]. Liability is capped at S$500,000 under clause 12.

The cap amount and clause number are kept. "Mr Tan Ah Kow" and "Tan Ah Kow" share `[PERSON_1]`.

## 10. Open points

- **To verify:** formats for SG passport, work permit, MyKad, vehicle plates, UEN, the postal sector range and phone prefixes; the M-series checksum table. Owner: PDPA counsel + AI engineer, S1.
- Local NER model choice and its own data handling (it must run in-tenant). Owner: AI engineer, S2.
- Counterparty-name policy (Q-7) and deal-value policy (Q-8). Owner: PO.
- Gate 1 recall/precision targets (Q-5). Owner: PO.

## 11. Change log

| Version | Date | Change | Author |
| --- | --- | --- | --- |
| 2026-10-13.v0 | 2026-10-13 | Initial taxonomy and rules | verina-pdpa-counsel |
