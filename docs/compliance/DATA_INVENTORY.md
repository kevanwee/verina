# Personal data inventory (v0)

| | |
| --- | --- |
| Version | v0 (Sprint 0, task T0.4 / EN-5) |
| Owner | verina-pdpa-counsel, with verina-security for flows and storage |
| Status | **Draft, design-time**, except implemented repository and metadata-only audit boundaries described below. Other rows remain target holdings, not observed production storage. Vendors marked TBD are not contracted, so no customer data may reach them |
| Aligned with | [`../security/DATA_FLOW.md`](../security/DATA_FLOW.md) v0 (flows F1–F15, §5.1 state map, §5.2 external calls). Flow ids below refer to that document. The PDPA overlay in DATA_FLOW §8 is a per-flow summary of this inventory |
| Related | [PDPA_ASSESSMENT.md](PDPA_ASSESSMENT.md) · [PII_TAXONOMY.md](PII_TAXONOMY.md) |

**Role:** DI = Verina processes as data intermediary for the customer (PDPA s 4(2)). ORG = Verina is the organisation. Tier comes from PII_TAXONOMY §2 (T1 highest; C = client-confidential, conditionally personal when it identifies an individual). Classification is context-dependent; credentials are T1 even when associated with a business contact.

**Access roles:** Matter team = users with matter membership past the ethical wall and a role granting the requested action (NFR-4; [access matrix](../security/ACCESS_MATRIX.md)). Tenant admin = customer administrator for tenant configuration, with no implicit access to matter content or metadata; a separate permitted role and matter membership are required. Requesters receive only the reviewed coarse status projection for matters they may access, not conflict details, waiver reasons or documents. Verina ops = Verina staff, with **no standing access to content** (PDPA_ASSESSMENT P-3); break-glass needs customer approval. System = service identities only.

## 1. Customer data (Verina as data intermediary)

| ID | Data item | Data subjects | Highest tier | Source | Purpose | Flows | Storage location | Retention default (proposed, Q-6) | Access roles | Processors / sub-processors | Country |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D-01 | Original uploaded documents (contracts, schedules, annexes, counterparty markups) | Signatories, directors, guarantors, employees and contacts named; counterparty personnel; client's individual customers in schedules | T1 (NRIC, bank details, signatures, ID scans possible) | Customer users via web upload | Deliver the review service as instructed | F1, F2 | Object storage, object-locked, SHA-256, tenant key | Life of matter + **12 months** after matter closure; tenant-configurable 0–7 years; legal hold overrides | Matter team; System | Cloud host (TBD, ADR-002) | SG (C-2.1) |
| D-02 | Email intake messages: headers, body, attachments | Senders, recipients, cc'd persons, people named in content | T1 (attachments as D-01) | Forwarded emails to the tenant intake address | Create matters from email (FR-1.1) | F1e | Intake quarantine store, tenant key | Converted to a matter: as D-01. **Not converted: delete after 30 days** (Q-11) | Tenant intake reviewers; System | Inbound mail service (TBD); cloud host | SG required; inbound MTA region **TBD** |
| D-03 | Matter metadata: counterparty, type, value, deadline, requester name/email, conflict-check record (names searched, result, clearer) | Requesters, clearers, counterparty individuals (if natural persons) | T3 (C for org names) | Intake form/email; lawyers | Intake, triage, conflict record (FR-1.x) | F1 | Postgres (target) | Matter retention (as D-01) | Matter team with permitted role; System; requester only coarse status projection, not this full record | Cloud host | SG |
| D-04 | Parsed text, OCR text, clause tree, definitions, cross-references, tracked changes and comments (incl. author names) | As D-01, plus counterparty reviewers named in tracked changes | T1 | Derived from D-01 (local parse/OCR) | Review | F3 | Postgres + pgvector (embeddings) | Deleted with the matter (cascade incl. embeddings) | Matter team; System | Cloud host. OCR must be local (DATA_FLOW §5.2) | SG |
| D-05 | **Redaction map** (placeholder ↔ original value, alias clusters) | Everyone detected in the matter | T1 (highest concentration) | Generated at F5 | Re-identify outputs inside the tenant | F5, F7 | Postgres, field-encrypted with tenant key | Deleted with the matter; crypto-shred. **Never** in logs, prompts or telemetry | System; rendered values only to the matter team | Cloud host | SG |
| D-06 | Redacted model payloads (prompt, excerpts, playbook rules) and model outputs | People in the matter, by placeholder; residual contextual identifiers | Residual risk up to T1: redaction does not automatically downgrade confidential context (PDPA_ASSESSMENT §6) | Orchestrator | Inference for triage, review, drafting, claim extraction | F6 | **Provider:** transient, zero data retention (required). **Verina:** run-local processing; no prompt/output copy in D-09. Any separate encrypted evidence store is unbuilt and requires a reviewed purpose, access and lifecycle design | Provider: none beyond processing (ZDR). Separate evidence-store retention not decided or implemented | System; any future evidence access requires its own reviewed grant | **Model provider (TBD, S2 decision)** | **TBD: SG required, or a reg 11/12 basis + disclosure** |
| D-07 | Review results, scores, evidence quotes, redlines, margin comments, advice memo, client summary, AI-use disclosure | As D-01 (re-identified) | T1 | Generated (F7), lawyer edits | Deliverables | F7, F10 | Postgres; export artefacts in object storage | Matter retention | Matter team | Cloud host | SG |
| D-08 | Verification Ledger entries incl. attestations (lawyer name, time, reason, exact text) | Attesting lawyers; people mentioned in assertions | T3 (T1 if the assertion quotes T1 data) | Generated + lawyer input | Verification gate (FR-7) | F9 | Postgres | Matter retention | Matter team; sign-off chain | Cloud host | SG |
| D-09 | Audit metadata: opaque tenant/actor/matter ids, event decisions, model/template identifiers and hashes, input/output hashes, counts, timings and outcomes; no document, prompt, output or free-text reason copy | Users (actors); other people when metadata or hashes remain linkable | Context-dependent; metadata may remain personal or confidential | Registered service payloads | Accountability, tamper-evident record (FR-9.2, NFR-6) | F11 | Locally implemented tenant hash chain in SQLAlchemy; optional externally held head HMAC. Independent immutable anchoring and production custody are unbuilt; see ADR 004 | Matter retention + **12 months** is a proposal only. End-of-retention, legal holds and backup expiry remain open; append-only does not mean retain forever | System; future audit/pack reads require explicit authorization and tenant binding, not an implicit tenant-admin grant | Production cloud host TBD | Local SQLite / disposable CI Postgres; production region unselected |
| D-10 | Audit pack exports (PDF + JSON) | As D-09 | T1 | Generated | Customer evidence (FR-9.4) | F12 | Downloaded to the user's device (customer's control); short-lived link | Server copy: 7 days, then deleted (proposed) | Matter team | Cloud host | SG (server copy) |
| D-11 | Playbooks and rules (may carry author names) | Knowledge lawyers (authors) | T3 / C | Customer | Review standards (FR-3) | F4 | Postgres | Life of tenant; versions kept (FR-3.3) | Tenant users per role | Cloud host | SG |
| D-12 | Lawyer-linked judgments and URLs | Litigants, witnesses, judges named in public judgments | T3 (publicly available) | Lawyer links/uploads | Ledger verification (FR-6.2) | F8 | Statute/judgment cache with URL, version, hash | Life of the citation's use; cache refresh (TBD) | Matter team; System | Cloud host; judgment host (GET only, no matter content sent) | SG (cache) |
| D-13 | User directory for the tenant (names, work emails, roles, matter memberships, wall membership) | Customer users | T3 | Customer IdP / admin | Access control, attribution | F13 | Postgres; session store | Life of user in tenant + 90 days (proposed) | Tenant admin; System | Customer's IdP (customer's processor); cloud host | SG (Verina copy) |
| D-14 | OAuth tokens and selected files for M365/DocuSign (later sprints) | Users; people in files | T1 (credentials) | User authorisation | Integrations | F14 | Postgres, tenant-key encrypted | Until revoked or user removed | System | Microsoft / DocuSign (the customer's own tenancy) | Per the customer's own tenancy |

## 2. Verina's own data (Verina as organisation)

| ID | Data item | Data subjects | Tier | Source | Purpose | Flows | Storage | Retention default (proposed) | Access roles | Processors | Country |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V-01 | Customer account and contract records (admin contacts, signatories) | Customer staff | T3 | Customer | Contract administration | — | Business systems (TBD) | Contract term + **5 years** (record-keeping; exact statutory period **to verify**) | Verina finance/ops | TBD | SG preferred |
| V-02 | Authentication and security logs (user id, IP address, user agent, timestamps) | Users | T3 | Platform | Security (s 24), abuse detection | F13, F15 | Log store | **12 months** (proposed) | Verina SEC (no content) | Cloud host; monitoring vendor (TBD) | SG required for logs with IPs (C-2.3) |
| V-03 | Operational telemetry, metrics, traces (content-free by design) | None intended; user ids possible | Internal | Platform | Reliability | F15 | Monitoring stack | 30–90 days | Verina ENG/SEC | Monitoring/error vendor (TBD) | **TBD**: vendor review for region and scrubbing (C-2.3) |
| V-04 | Support tickets and correspondence | Customer users | T3 (must not contain matter content; break-glass only) | Users | Support | — | Support tool (TBD) | 24 months after closure (proposed) | Verina support | TBD | TBD |
| V-05 | Billing and invoices | Customer billing contacts | T3 | Customer | Billing, tax | — | Billing system (TBD) | Statutory record period (**to verify**) | Verina finance | Payment/billing processor (TBD) | TBD |
| V-06 | Pilot and marketing contacts | Prospects | T3 | Direct / events | Business development | — | CRM (TBD) | Until consent withdrawn or 24 months inactive | Verina BD | TBD | TBD (DNC Register check for SG numbers) |
| V-07 | Break-glass grants and staff access records | Verina staff; customer approvers | T3 | Platform | Accountability for staff access (P-3) | F11 | Audit store | As D-09 | Verina SEC; customer admin can view | Cloud host | SG |
| V-08 | Staff records relevant to data protection (training completion, confidentiality undertakings) | Verina staff | T3 | HR | Accountability (s 12(c)) | — | HR system (TBD) | Employment + 2 years (proposed) | Verina HR/DPO | TBD | TBD |

## 3. Data that must never exist in Verina environments

| Item | Rule | Control |
| --- | --- | --- |
| Real client documents in dev, test or CI | Synthetic fixtures only (AGENTS.md "Data") | CONTROLS C-5.4; pre-commit `samples-real/` block |
| Customer content in model training, evals or analytics | Prohibited (PDPA_ASSESSMENT §2) | DPA with the provider (no training); internal policy; telemetry scrubber (B-4) |
| Matter content or redaction-map values in application logs or telemetry | Prohibited | B-4 allow-list logging; canary tests (DATA_FLOW §7.5) |
| Unredacted personal data in any external model payload | Blocked unless the PO records an exception | Egress guard fail-closed (C-1.4) |

## 4. Proposed retention defaults (for PO decision Q-6)

| Data | Default | Configurable | Deletion method |
| --- | --- | --- | --- |
| Matter content (D-01, D-03, D-04, D-07, D-08) | Matter closure + 12 months | Per tenant, 0–7 years; legal hold overrides | Cascade delete; object-lock period ≤ retention commitment |
| Redaction map (D-05) | Deleted with the matter | No (never longer than the matter) | Crypto-shred |
| Email intake not converted (D-02) | 30 days | Per tenant, 7–90 days | Delete |
| Audit events/hashes (D-09) | Matter retention + 12 months (proposal) | Per tenant, subject to reviewed purpose/legal hold | Not implemented: define authorized expiry or removal of identifying linkage, backup handling and integrity evidence. Retaining hashes is not proof of anonymisation |
| Backups | ≤35 days (NFR-5) | No | Lifecycle expiry |
| Model provider copies (D-06) | None (ZDR) | No | Contractual + provider attestation |
| Security logs (V-02) | 12 months | No | Expiry |

The draft reading of section 25 sets no fixed period (primary verification coverage in SOURCE_REVIEW.md): the test is purpose and legal/business necessity (Key Concepts paras 18.3–18.4). These numbers are business defaults to balance firms' file-retention needs against minimisation. The customer's instruction (tenant setting) defines its purpose period.

## 5. Sub-processor register (v0, none contracted)

| Sub-processor | Service | Personal data | Country | Transfer basis (if outside SG) | Status |
| --- | --- | --- | --- | --- | --- |
| Cloud host (AWS ap-southeast-1 or GCP asia-southeast1, ADR-002) | Hosting, storage, KMS | All D-xx | SG | n/a if pinned | PO decision S1 |
| Model provider (Anthropic direct / Bedrock / Vertex) | Inference | D-06 | **TBD** | reg 11 contract or reg 12 certification if not SG | PO decision S2; [MODEL_PROVIDER_DPA_CHECKLIST.md](MODEL_PROVIDER_DPA_CHECKLIST.md) |
| Temporal Cloud (if chosen) | Workflow | Ids + encrypted payloads | TBD | TBD | ENG + SEC, S1 |
| Monitoring / error reporting | Telemetry | V-02/V-03 (no content) | TBD | TBD | ENG + SEC, S1 |
| Inbound mail service | Email intake | D-02 | TBD | TBD | ENG, S2 |
| LawNet | Case lookup | Citation strings only; no personal data sent | SG | n/a | PO decision S4 |
| Singapore Statutes Online | Statute fetch | None sent | SG | n/a | Planned |
| Supabase (Auth + Postgres, Free plan) | Authentication, invitation e-mail, development database host | Auth identities (e-mail, auth logs incl. IP), D-13 directory and all Verina tables on the dev project | SG (project region); support/sub-processing TBD | TBD (PDPA review) | Development only, ADR 009; DPA and review open |

## 6. Change log

| Version | Date | Change | Author |
| --- | --- | --- | --- |
| v0 | 2026-10-13 | Initial inventory aligned with DATA_FLOW v0 | verina-pdpa-counsel |
| v0 | 2026-10-13 | Engineering addendum: identity directory tables (migration 0004) and the disabled-by-default HTTP boundary; pending PDPA counsel review | verina-engineer |
| v0 | 2026-10-14 | Engineering addendum: organizations, member e-mail and invite status, platform admins, directory/auth-failure audit metadata, Supabase as processor (ADR 009); pending PDPA counsel review | verina-engineer |

## Runtime evidence qualification

The inventory is a target design, not observed deployment. The current redaction map is process-local for one run; no encrypted tenant database, deletion cascade, region pinning or backup expiry is demonstrated by this inventory. See [REDACTION_COMPATIBILITY.md](REDACTION_COMPATIBILITY.md). Hashes and metadata may remain personal data when linkable; retention of hashes is not by itself proof of anonymisation or deletion.


## Implemented durable repository boundary

The reusable SQL matter repository persists a tenant/matter-keyed current projection through Alembic on SQLite/PostgreSQL. `access_json` contains protected membership/wall identifiers, recorded conflict outcomes, historical profile names and waiver reasons. `content_json` contains protected matter titles and document text. Neither column is public metadata. Tests use invented fixtures; this does not establish observed customer holdings or production activation.

Access-only queries omit title/document content; requester responses remain opaque ID and coarse conflict-stage status. Canonical audit payloads still contain bounded identifiers/decision metadata and optional reason hashes, not names, reasons, titles or document text. Hashes are linkable evidence, not anonymisation.

Repository restart persistence and revision protection are implemented. Outbox for external side effects, durable historical record policy, authentic identity provisioning, production encryption/KMS, operational database roles/RLS, retention, backups and hold-aware deletion remain unimplemented or separately reviewed. Physical delete is a storage primitive, not an approved retention workflow. See [ADR 006](../adr/006-durable-matter-repository.md).

## Atomic mutation receipts (migration 0003)

When the service is composed with the SQL mutation unit of work, create, title update, conflict recording and waiver commit the matter projection change, one `matter.mutation_completed` audit event and one `matter_mutation_receipts` row in a single database transaction. Any failure before commit, including cancellation, rolls all three back.

| Store | Fields | Purpose | Classification |
| --- | --- | --- | --- |
| `matter.mutation_completed` audit payload | tenant, actor, matter and operation IDs; action; expected/result revision; prior check version; request, before/after and result-access SHA-256 hashes; UTC time | Evidence that a specific database transition committed | Linkable metadata; no names, titles, reasons or document text |
| `matter_mutation_receipts.result_access_json` | Minimal historical access result needed to return the exact original retry result: conflict check (including recorder profile name) and waiver (including reason) where the action produced them; membership/wall sets stripped; create/title receipts strip check/waiver state | Idempotent retry after response loss | Protected confidential business state, not audit metadata; never logged or publicly serialized |

Receipts are append-only (database triggers) and persist alongside the current projection, so they duplicate some protected historical facts. A receipt never grants current authority: replay re-checks current identity, role, membership and wall before the protected column is read, and denies record/waive replays when the current check or waiver differs. No retention period, deletion of receipts/backups, hold handling, encryption or authentic lawyer identity is claimed. A consistently forged privileged database write remains outside this control. Delete and membership changes are rejected in durable-transaction mode until their outcomes are integrated.

## Identity directory and HTTP boundary (migration 0004, disabled by default)

Migration 0004 implements a first, minimal part of the D-13 user directory for the authenticated `/v1` matter routes ([ADR 007](../adr/007-verified-token-identity-and-matter-api.md)). It is populated only by the local/test provisioning CLI with synthetic principals. No identity provider is selected, so no customer IdP data flows into it, and no e-mail address, IP address or token is stored.

| Store | Fields | Purpose | Classification and linkability |
| --- | --- | --- | --- |
| `identity_bindings` | `issuer`, `subject` (the identity provider's subject identifier), `tenant_id`, `actor_id`, `created_at` | Map a verified token's `(issuer, subject)` to a Verina principal; token claims grant nothing | Personal data (T3) once real: `subject` is a stable pseudonymous identifier that links to the person at the identity provider, and the row links it to the opaque actor ID in audit metadata (D-09) |
| `identity_principals` | `tenant_id`, `actor_id`, `roles`, `active`, `display_name` (nullable), `revision`, `updated_at` | Authorization source of truth (roles, deactivation) and trusted profile for named attribution | Personal data (T3): the display name identifies the user. It is retained after deactivation because historical conflict/waiver records reference it (D-03), and that retention needs a PDPA-reviewed period |

At the HTTP boundary the bearer token is verified in memory and never stored or logged. Request bodies (titles, waiver reasons) flow only into the existing protected matter columns and receipts described above. Error bodies never echo input. Authentication failures are not yet recorded (V-02 is still target design), and directory changes are not yet audit-chain events. Retention, deletion or anonymisation of bindings and principals, any cross-tenant or cross-issuer subject reuse policy, a production provisioning workflow, and the choice of identity provider (a new sub-processor or customer IdP) require PDPA counsel and security review before any real user is provisioned.

## Accounts, organizations and Supabase (migrations 0005 and 0006, ADR 009; pending PDPA counsel review)

[ADR 009](../adr/009-supabase-identity-accounts-and-postgres.md) adds a development-only path in which platform administrators create organizations and invite members through Supabase Auth, and the Verina database itself is hosted on Supabase Postgres (Free plan, Singapore). Until PDPA counsel and security approve, source tests use synthetic identities. Team-internal addresses are still real personal data and require the reviewed real-person setup gate before invitation.

| Store | Fields | Purpose | Classification and minimisation |
| --- | --- | --- | --- |
| `organizations` | opaque `id` (= tenant id), `name`, `slug`, `active`, `revision`, timestamps | Customer organization record and the switch that revokes all of its members | Business data; a sole-practitioner firm name may identify a person (T3) |
| `directory_accounts` | `tenant_id`, `actor_id`, `email` (lower-cased, unique), `invite_status`, `invited_at`, `accepted_at` | Member-management display and the one-account-one-organization rule | Personal data (T3, part of D-13). The e-mail address is stored only here, never in audit events, logs, error bodies or idempotency records |
| `platform_admins` | `issuer`, `subject`, opaque `admin_id`, `created_at` | Verina operator grant | Personal data (T3, pseudonymous subject); the bootstrap e-mail address is not stored in Verina |
| `admin_idempotency` | scope, operation id, SHA-256 actor key, action, request hash, resource id, status, audit event id | Safe retries of administrative writes | Linkable metadata; request bodies (with e-mail addresses and names) are stored only as a hash |
| `directory.changed` audit payload | chain id, acting id, action, organization and target actor ids, roles, flags, revisions, request hash, keyed subject HMAC | Accountability for directory changes (US-54) | Linkable metadata (D-09); no e-mail, display or organization names |
| `auth.failure` audit payload | reason class, route surface, keyed HMAC of `(issuer, subject)` when the token verified, suppressed count | Security monitoring (SEC M4, V-02) | Linkable metadata; no IP address, token or raw subject is stored |

**Supabase as processor (sub-processor register).** Supabase (the published DPA retrieved 14 October 2026 names Supabase Pte. Ltd; the applicable account agreement still needs confirmation) would process: authentication identities in `auth.users` (e-mail address, password hash or magic-link state, MFA factors, sign-in timestamps, and IP/user-agent in its auth logs), the invitation e-mails it sends, and, as database host, every Verina table above plus matters and audit data. Region: Singapore (the project's region). Plan: Free, which has no backups or point-in-time recovery and pauses after a week of inactivity. A data processing agreement, transfer assessment for any support or sub-processing outside Singapore, retention of `auth.users` and auth logs, and deletion on member removal are **open** and must be reviewed by PDPA counsel before real users are invited. The Supabase secret key is held only in the server environment.

The access-token `email` claim is not read by Verina. Members can be deactivated but not yet deleted; retention of `directory_accounts`, bindings and Supabase users after deactivation needs a reviewed period.

## Accounts privacy review and activation evidence (14 October 2026)

Scope: source integration of ADR 009 plus the separately reviewed connected web front door;
no live invitation, credential inspection or deployed processing assessment was performed.
The earlier migration 0004 paragraph describes its original implementation. ADR 009 adds
authentication-failure and directory audit events; it supersedes the earlier statement that
these events are absent when the accounts composition is enabled.

| Boundary | Source-observed result | Remaining evidence before real-person activation |
| --- | --- | --- |
| Account directory | Authorized platform or own-organization admins read email, display name, roles and invite status; platform grants do not confer matter access | Approved account notice/purpose, actual admin grants and privilege review |
| Global unique email | One address can belong to one organization. Authorized administrators can infer an address is already bound through `account_exists`; no other organization's identity or membership is returned | Explicit product/privacy explanation; do not describe this as zero cross-organization inference |
| Admin request hashes | Raw email/name bodies are absent from receipts/audit, but deterministic SHA-256 request/actor hashes and opaque identifiers remain linkable and may permit guessing known candidate input | Purpose-bound retention, access/export/correction/deletion and backup treatment; hashes are not anonymisation |
| Provider invitation | Supabase receives email and configured callback destination; bounded existing-user lookup reads project-level auth users transiently in server memory | Applicable DPA, sub-processor/location review, actual redirect/template configuration, email delivery and reconciliation |
| Browser/web host | Server auth uses Supabase; browser receives HttpOnly auth cookies and protected account/admin views through the configured web host | Web host's permitted commercial use, processor/region/log settings; no token/callback/email values in access or error logs |
| Deactivation | Directory authority and current replay access are rechecked; historical attribution and auth-provider users remain | Reviewed retention and provider-account revocation/deletion procedure; deactivation is not erasure |

A Singapore project region covers the primary project-data location, not exclusive support,
SMTP or web-host processing. Supabase's published DPA clause 6.1 preserves processing
exceptions. Its clauses 11.2 and Schedule 3 describe termination/functional deletion but do
not prove an application's specific member-deletion or auth-log expiry workflow.

Default Supabase SMTP only serves project-team addresses, is currently limited to two
messages per hour and has no delivery SLA. A reviewed custom SMTP service is required for
arbitrary recipients. It introduces a further processor and secret; no service is selected
by this review. Vercel Hobby is limited to personal non-commercial use; a business product
cannot infer commercial hosting permission from its existing preview deployment.

Sources (retrieved 14 October 2026): [Supabase regions](https://supabase.com/docs/guides/platform/regions),
[Supabase DPA](https://supabase.com/legal/customer-resources/data-processing-addendum) clauses 6.1,
11.2 and Schedule 3, [Supabase sub-processors](https://supabase.com/legal/customer-resources/subprocessor-list),
[SMTP restrictions](https://supabase.com/docs/guides/auth/auth-smtp),
[Vercel Hobby terms](https://vercel.com/docs/plans/hobby).

Conditional source integration can proceed subject to current CI and the Scrum Master/QA
review gate. Real-person activation remains separate: account notice and applicable terms,
actual service settings, migration/DB privileges, bounded exposure/rate controls, callback
and session safety, SMTP configuration and a real login/save/reload journey must be evidenced.
This is a draft technical privacy assessment, not human legal sign-off.