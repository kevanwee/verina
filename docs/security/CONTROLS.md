# Verina controls matrix (v0)

| | |
| --- | --- |
| Version | v0 (Sprint 0, task T0.3 / EN-4) |
| Owner | verina-security |
| Status | All controls **Planned** unless stated. Status moves Planned → In progress → Implemented → Evidenced (evidence linked) as sprints land. |
| Related | [THREAT_MODEL.md](THREAT_MODEL.md) (threat ids in the "Threats" column) · [DATA_FLOW.md](DATA_FLOW.md) |

Owner roles: ENG engineer · AI AI engineer · QA · SEC security · PDPA PDPA counsel · UX designer · PO product owner.

Evidence types: **Test** (automated test in CI) · **Config** (IaC/config file reviewed) · **Scan** (CI scanner output) · **Doc** (signed document / ADR / policy) · **Log** (audit or runtime log sample) · **Review** (recorded review in REVIEWS.md or a PR) · **Report** (external assessment).

## 1. NFR → controls

| NFR | Requirement (target) | Control id | Control | Owner | Sprint | Evidence | Threats | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NFR-1 | ZDR + no training by model providers (signed DPA/ZDR per endpoint) | C-1.1 | Model endpoint approval: security + PDPA review recorded before any provider/route is enabled | SEC/PDPA | S2 | Review, Doc | LLM-EXT-1 | Planned |
| | | C-1.2 | Signed DPA with ZDR and no-training terms per endpoint; stored with retrieval date | PDPA/PO | S2 | Doc | LLM-EXT-1 | Planned |
| | | C-1.3 | Egress allow-list contains only approved model hosts; base URL not user-configurable | AI/SEC | S1 | Config, Test | LLM-EXT-2, ORC-1 | Planned |
| | | C-1.4 | Redaction + egress guard (fail closed) on every model call | AI/PDPA | S2 | Test (PII test set), Log | ORC-2, LLM-7 | Planned |
| NFR-2 | Store/process in Singapore by default; shown per matter | C-2.1 | All stores, backups, KMS and compute pinned to SG region in IaC; policy check denies other regions | ENG | S1 | Config, Scan | DS-4 | Planned |
| | | C-2.2 | Model processing region recorded per call and displayed per matter | AI/UX | S2 | Log, Test | LLM-EXT-1 | Planned |
| | | C-2.3 | Third-party processors (monitoring, Temporal Cloud if used) reviewed for region before adoption | SEC/PDPA | S1 | Review | — | Planned |
| NFR-3 | Encryption at rest + in transit; per-tenant keys (AES-256, TLS 1.2+, CMK option) | C-3.1 | TLS 1.2+ at edge with HSTS; internal TLS/mTLS; DB TLS required | ENG | S1 | Config, Scan (TLS test) | API-9, WEB-1 | Planned |
| | | C-3.2 | Envelope encryption with per-tenant data keys via KMS; field-level for redaction map, tokens, audit payloads | ENG/SEC | S1 | Config, Test | DS-5, GOV-3, EXT-2 | Planned |
| | | C-3.3 | Customer-managed key option and crypto-shred on tenant offboarding | ENG | S8 | Doc, Test | DS-5 | Planned |
| NFR-4 | Matter-level ACL, ethical walls (no hits/previews/AI context without access) | C-4.1 | Central authorisation policy on every resource; deny by default | ENG | S1 | Test (authz matrix) | API-2, API-3, WEB-6 | Planned |
| | | C-4.2 | Postgres row-level security on tenant + matter as second layer | ENG | S1 | Test, Config | DS-1 | Planned |
| | | C-4.3 | Ethical walls enforced in search, typeahead, notifications, pgvector retrieval and orchestrator context builder | ENG/AI | S1 / S3 | Test (canary strings across matters) | API-8, ORC-3, DS-2, LLM-4 | Planned |
| | | C-4.4 | SSO (OIDC/SAML) or MFA for local accounts; session hardening (HttpOnly/Secure/SameSite, idle timeout, revoke-all) | ENG/SEC | S1 | Test, Config | API-1, IDP-1, IDP-2, WEB-1 | Planned |
| | | C-4.5 | Step-up re-authentication for attestation, sign-off, export, admin changes | ENG | S6 | Test | WEB-3, VER-4 | Planned |
| | | C-4.6 | No standing operator access to tenant content; break-glass audited | SEC | S8 | Doc, Log | OPS-1 | Planned |
| NFR-5 | PDPA access, correction, retention (per-matter retention; backup deletion ≤ 35 days) | C-5.1 | Per-matter retention policy with deletion job (content + embeddings + redaction map + exports) | ENG/PDPA | S3 | Test, Log | DS-4 | Planned |
| | | C-5.2 | Backup lifecycle ≤ 35 days in SG region | ENG | S3 | Config | DS-4 | Planned |
| | | C-5.3 | Access/correction request workflow (admin tooling + audit) | ENG/PDPA | S7 | Test, Doc | — | Planned |
| | | C-5.4 | Synthetic fixtures only in dev/test; no prod → non-prod data path | QA/SEC | S0 | Review, Config | OPS-2, SC-6 | Planned |
| NFR-6 | Append-only, tamper-evident audit (hash-chained; integrity check on export) | C-6.1 | Audit writer role INSERT-only; no UPDATE/DELETE grants | ENG | S1 | Config, Test | GOV-1 | Planned |
| | | C-6.2 | Per-tenant hash chain (record hash includes previous hash + canonical payload); chain head periodically anchored to WORM storage | ENG/SEC | S1 | Test, Review (design review by SEC) | GOV-1 | Planned |
| | | C-6.3 | Transactional outbox so business change and audit event commit atomically; sequence gap detection | ENG | S1 | Test | GOV-2 | Planned |
| | | C-6.4 | Integrity verification run on every audit pack export; failure blocks export | ENG/QA | S7 | Test | GOV-1, GOV-5 | Planned |
| NFR-7 | Log model, version, template, sources (100% of calls) | C-7.1 | Orchestrator is the only model caller; Semgrep rule fails CI on model SDK import elsewhere | AI/QA | S0 (rule) / S1 | Scan | ORC-1 | Planned |
| | | C-7.2 | Audit write is in the call path (call fails if audit fails); records model id/version, template id + hash, source ids, redaction version, guard result | AI | S1 | Test, Log | ORC-4, ORC-7 | Planned |
| | | C-7.3 | Pinned model ids; upgrade only after gold-set eval regression | AI/QA | S3 | Test (eval report) | LLM-EXT-4 | Planned |
| NFR-8 | Zero fabricated authorities exported (gate + monthly red-team) | C-8.1 | Deterministic verification checks (exists, quote match, pinpoint, in-force version); model cannot set Verified | AI | S6 | Test | VER-1 | Planned |
| | | C-8.2 | Citation-pattern scan of final export text; any citation without a ledger entry blocks export | AI/ENG | S6 | Test | LLM-6, WF-1 | Planned |
| | | C-8.3 | Export gate evaluated server-side at export time; ledger entries bound to text hashes; edits reset status | ENG/AI | S6 | Test | WF-1, VER-5 | Planned |
| | | C-8.4 | Red-team set (fake/paraphrased citations, injection) as release gate; monthly re-run | QA | S5 / S6 | Test (gate certificate) | LLM-1, LLM-6 | Planned |
| | | C-8.5 | Statute cache integrity (source URL, version date, content hash); allow-listed judgment hosts | AI/SEC | S6 | Test, Config | VER-2, VER-3 | Planned |
| NFR-9 | Clause classification ≥ 90% vs lawyer labels | C-9.1 | Gold-set harness; prompt-injection-resistant scoring (structured output, verbatim evidence quotes, deterministic post-checks) | AI/QA | S3 / S4 | Test (eval report) | LLM-1, LLM-5 | Planned |
| | | C-9.2 | Playbook versioning, two-person publish, diffed import, learning suggestions as proposals only | ENG/AI | S3 / S4 | Test, Log | LLM-5 | Planned |
| NFR-10 | 40-page review p95 < 3 min; 50-doc grid < 15 min | C-10.1 | Per-tenant queues, concurrency and resource limits so one tenant cannot starve others | ENG | S2 | Test (load) | DOC-9, API-6 | Planned |
| | | C-10.2 | Token budgets, step caps and chunking in orchestrator | AI | S3 | Test | ORC-6, LLM-10 | Planned |
| NFR-11 | 99.5% monthly in SG business hours | C-11.1 | Rate limiting, WAF, autoscaling, health checks | ENG | S1 | Config | API-6, EML-3 | Planned |
| | | C-11.2 | Model provider degradation handling (retry, queue, degraded UI) | AI/ENG | S7 | Test | LLM-EXT-3 | Planned |
| | | C-11.3 | Backups with tested restore; incident response runbook (incl. PDPA breach assessment) | ENG/SEC/PDPA | S8 | Doc, Log (restore test) | OPS-3 | Planned |
| NFR-12 | SOC 2 Type II / ISO 27001 within 12 months; annual pen test | C-12.1 | This controls matrix maintained as the control register; evidence links per control | SEC | S0 → ongoing | Doc | — | In progress (v0) |
| | | C-12.2 | CI security scanning: gitleaks, npm audit, pip-audit, Semgrep + Bandit, private/ guard, pinned Actions | QA/SEC | S0 | Scan | SC-1, SC-2, SC-3, SC-5 | Planned |
| | | C-12.3 | Third-party code/skill/plugin review and pinning (REVIEWS.md, PROVENANCE.md, CODEOWNERS on `.claude/`) | SEC | S0 / S1 | Review | SC-4 | In progress (R-001) |
| | | C-12.4 | External penetration test before pilot; findings triaged, no open Critical/High at GA gate | SEC | S8 | Report | all | Planned |
| | | C-12.5 | Security review of each new external endpoint, provider or networked dependency | SEC | ongoing | Review | SC-1, LLM-EXT-1 | Planned |
| NFR-13 | DOCX round-trip intact (30 golden files) | C-13.1 | Hardened XML parsing (no entities, no network, no external relationships) | ENG | S2 | Test (XXE corpus) | DOC-1 | Planned |
| | | C-13.2 | Zip/decompression limits; sandboxed parser/OCR with no network, non-root, resource limits | ENG/SEC | S2 | Test (bomb corpus), Config | DOC-2, DOC-4 | Planned |
| | | C-13.3 | Reject macro-enabled content; strip OLE/ActiveX/DDE; malware scan | ENG/SEC | S2 | Test | DOC-3, EML-2 | Planned |
| | | C-13.4 | Export scrubbing of internal comments, hidden text and metadata; golden tests | ENG/QA | S5 | Test | DOC-6 | Planned |
| | | C-13.5 | Original immutable with SHA-256 at ingestion | ENG | S2 | Test, Log | DOC-5 | Planned |
| NFR-14 | First review untrained < 10 min | C-14.1 | Security friction designed in: step-up and attestation flows usability-tested; ledger statuses state exactly what was checked | UX | S6 | Review (usability test) | LLM-8, VER-4 | Planned |
| NFR-15 | WCAG 2.2 AA | C-15.1 | Security-relevant UI (warnings, quarantine, gate blocks, session timeout) meets WCAG 2.2 AA, incl. timeout warnings (SC 2.2.1) | UX/QA | S1 → ongoing | Test (a11y audit) | — | Planned |
| NFR-16 | Full export (DOCX, PDF, JSON) | C-16.1 | Export scoped to one matter, authorised, step-up, audited; short-lived signed download URLs | ENG | S7 | Test, Log | GOV-5, DS-3 | Planned |
| | | C-16.2 | Untrusted text rendered safely in all exports and in the web UI (no HTML injection, no auto-loaded external links/images) | ENG/AI | S3 | Test | WEB-2, LLM-3 | Planned |

## 2. Cross-cutting baseline controls (not tied to a single NFR)

| Control id | Control | Owner | Sprint | Evidence | Status |
| --- | --- | --- | --- | --- | --- |
| B-1 | Security headers on web and API: CSP (nonce, no `unsafe-inline`/`unsafe-eval`, `frame-ancestors 'none'`, `img-src 'self'`, `connect-src 'self'` + API), HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin`, `Permissions-Policy` minimal, `Cache-Control: no-store` on matter views | ENG/SEC | S1 | Test (header check), Scan | Planned |
| B-2 | No third-party scripts, fonts, analytics or CDNs on authenticated pages | ENG/UX | S1 | Test (CSP report-only → enforce) | Planned |
| B-3 | Secrets only in the cloud secret manager; `.env.example` only in repo; pre-commit + gitleaks | SEC/QA | S0 | Scan, Config | In progress (pre-commit exists) |
| B-4 | Structured logging with field allow-list; no document text or prompts in app logs; PII scrubber on telemetry | ENG | S1 | Test (canary) | Planned |
| B-5 | Egress proxy with host allow-list for all workloads; SSRF protections (deny private and metadata ranges) | ENG/SEC | S1 | Config, Test | Planned |
| B-6 | Prompt-injection boundary: document/playbook/statute text only in delimited data blocks; structured outputs; tools matter-bound and side-effect free | AI | S3 | Test (injection corpus) | Planned |
| B-7 | Email intake: per-tenant tokenised address, SPF/DKIM/DMARC checks, sender allow-list, quarantine | ENG | S2 | Test | Planned |
| B-8 | OAuth integrations with minimum scopes and encrypted token storage | ENG/SEC | S7 | Review, Test | Planned |
| B-9 | Branch protection on `main`, required CI checks, CODEOWNERS (SEC on `.claude/`, `.githooks/`, `docs/security/`, orchestrator, auth, audit) | QA/SEC | S0 / S1 | Config | Planned |

## 3. Sprint 0 observed implementation (SEC-1)

[R-002](REVIEWS.md#r-002--ai-orchestrator-skeleton-and-external-model-call-boundary) records the actual skeleton boundary. C-1.1/C-1.3: live provider transport disabled; endpoint approval/allow-list remain planned. C-1.4: partial regex redaction implemented, complete detector and final-payload guard planned. C-7.1: guard tests pass locally; Semgrep rules corrected and YAML/regex checked, hosted scanner pending; static patterns do not constitute network isolation. C-7.2: post-call completion emission and sink-failure output withholding tested; durable start, source/route provenance, cancellation and retry-attempt audit remain planned. B-4: application summaries and SDK request-log suppression tested with canaries; comprehensive diagnostics review remains planned. C-12.2: full npm audit retains an unresolved dev-only High advisory; informational status is not risk acceptance. R-001's PO acceptances remain unchanged.

## 4. Change log

| Version | Date | Change | Author |
| --- | --- | --- | --- |
| v0 | 2026-10-13 | Initial matrix NFR-1..16 → controls | verina-security |
