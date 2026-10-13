# Traceability: backlog ids → tests

Owner: verina-qa · Updated in the same PR as the tests it lists · Last updated: 2026-10-13 (S0)

This table holds ids and short titles only. Acceptance criteria live in the private backlog. Test-id convention and tagging rules are in `TEST_STRATEGY.md` §9. Suites: `api` = pytest unit, `int` = API integration, `web` = Vitest, `e2e` = Playwright (+ axe), `golden` = DOCX round-trip harness, `eval-gold` / `eval-redteam` / `eval-pii` = eval harnesses, `static` = guard, Semgrep, gitleaks and other scanners.

Status values: **Planned** (no test yet) · **Partial** (some criteria covered) · **Passing** (all criteria covered and green in CI) · **Failing** · **Quarantined (#issue)**.

## Enablers

| Id | Short title | Sprint | Planned tests / suites | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| EN-1 | Monorepo skeleton | S0 | `api-EN-1-01..03` (`tests/test_health.py`: health 200, security headers, docs off in production); `web-EN-1-01` (`__tests__/page.test.tsx`) | 0 | Partial (API and web tests pass locally; hosted CI pending) |
| EN-2 | CI pipeline + local check | S0 | `static-EN-2-01` (`tests/test_guard.py`: blocked paths, private/.env.example precedence, ignored-but-tracked private file, missing hook, SDK imports) and `tests/test_precommit.py` (real staged-content/path guard in isolated Git repositories); `static-EN-2-02` gitleaks; `static-EN-2-03` npm audit + pip-audit; `static-EN-2-04` Bandit + Semgrep; workflow validated by actionlint | 0 | Partial (local checks pass with Gitleaks/Semgrep skipped; hosted CI and scanner execution pending) |
| EN-3 | Design system v0 + motion providers | S0 | Implemented: `__tests__/page.test.tsx` (heading smoke), `__tests__/ledger-status.test.tsx` (ledger status render and accessibility attributes); planned: motion/reduced-motion, light/dark token assertions and axe e2e | 0 | Partial (18 web tests pass locally; motion/a11y checks and hosted CI pending) |
| EN-4 | Threat model + data flow + controls v0 | S0 | Document review (no automated test); controls feed `static-*` and `int-*` rows | 0 | n/a (doc) |
| EN-5 | PDPA assessment + PII taxonomy | S0 | `api-EN-5-01` taxonomy JSON schema-valid; detectors feed `eval-pii` | 1 | Planned |
| EN-6 | AI orchestrator skeleton + audit hook | S0–S1 | `api-EN-6-*` (`tests/ai/`): every call path records model, version, template id, input hash; fake client and real SDK with explicit in-process mock transport; `static-EN-2-01`/Semgrep ORC-1 rule | 0 | Partial (orchestrator tests pass locally; hosted CI pending) |
| EN-7 | Tenancy, authn, RBAC, matter ACL | S1 | `int-EN-7-*` generated authz matrix; cross-tenant and no-access fail closed | 1 | Planned |
| EN-8 | Hash-chained audit log | S1 | `api-EN-8-01` chain verifies; `api-EN-8-02..04` edit, delete, reorder break verification; `int-EN-8-01` integrity API | 1 | Planned |
| EN-9 | Golden DOCX corpus + harness | S1–S2 | `golden-EN-9-01..30` round-trip diff = 0 per file | 1 | Planned |
| EN-10 | 200-clause gold set | S3 | `eval-gold-EN-10` agreement report | 2, 4 | Planned |
| EN-11 | Red-team set | S5 | `eval-redteam-EN-11` exported-fabrication count = 0 | 3, 4 | Planned |

## User stories

| Id | Short title | Sprint | Planned tests / suites | Gate | Status |
| --- | --- | --- | --- | --- | --- |
| US-1 | Intake by forwarded email | S2 (web form S1) | `int-US-1-01..03`; `e2e-US-1-01` (web form) | — | Planned |
| US-2 | Auto-tier Green / Yellow / Red | S3 | `api-US-2-*` with fake model; `eval-gold` tier subset | 2 | Planned |
| US-3 | Conflict check before work | S1 | `int-US-3-01..02`; `e2e-US-3-01` | — | Planned |
| US-4 | Requester status view | S8 | `int-US-4-01` (no privileged fields); `e2e-US-4-01` + axe | — | Planned |
| US-5 | Scanned PDF → clause structure | S2 | `api-US-5-*`; `golden` PDF fixtures | 1 | Planned |
| US-6 | Keep counterparty tracked changes | S2 | `golden-US-6-01` (counterparty revisions intact + attributed) | 1 | Planned |
| US-7 | Redact personal data before AI calls | S2 | `api-US-7-*`; `eval-pii-US-7` (recall per category, re-identification) | 1 | Planned |
| US-8 | Playbook rules (standard / fallback / walk-away) | S3 | `int-US-8-*`; `e2e-US-8-01` | — | Planned |
| US-9 | Import Word playbook | S4 | `api-US-9-*` (synthetic DOCX playbooks) | — | Planned |
| US-10 | Review stamped with playbook version | S3 | `int-US-10-01` | 2 | Planned |
| US-11 | Clause scored with quoted text | S3 | `api-US-11-*` property test: every finding quote exists verbatim in source | 2 | Planned |
| US-12 | Missing protections flagged | S4 | `api-US-12-*`; `eval-gold` missing-clause subset | 2 | Planned |
| US-13 | Multi-document grid | S4 | `int-US-13-*`; `e2e-US-13-01`; perf check (NFR-10) | 4 | Planned |
| US-14 | Override with reason | S4 | `int-US-14-01..02`; `e2e-US-14-01` | — | Planned |
| US-15 | Redlines as real tracked changes | S5 | `golden-US-15-*` (opens in Word, lawyer author, no AI metadata) | — | Planned |
| US-16 | Explanatory comments by tone | S5 | `api-US-16-*` with fake model | — | Planned |
| US-17 | First-draft advice memo | S5 | `api-US-17-*`; every proposition creates a ledger entry | 3 | Planned |
| US-18 | Plain-English client summary | S7 | `api-US-18-*` (length, glossary checks) | — | Planned |
| US-19 | Every assertion becomes a ledger entry | S5 | `api-US-19-*`; `eval-redteam` extraction recall | 3 | Planned |
| US-20 | Statute citations auto-checked | S6 | `int-US-20-*` against local SSO fake; `eval-redteam` | 3 | Planned |
| US-21 | Unlinked case citation = Unsupported | S6 | `api-US-21-01..02`; `eval-redteam` | 3 | Planned |
| US-22 | Export blocked until ledger clean | S6 | `int-US-22-01..03`; `e2e-US-22-01` | 3 | Planned |
| US-23 | Lawyer attestation with reason | S6 | `int-US-23-01..02`; `e2e-US-23-01` | 3 | Planned |
| US-24 | Sign-off view with diffs + ledger summary | S7 | `web-US-24-*`; `e2e-US-24-01` + axe | 4 | Planned |
| US-25 | Red matters need partner sign-off | S7 | `int-US-25-01..02` | 4 | Planned |
| US-26 | Return with comments | S7 | `int-US-26-01`; `e2e-US-26-01` | — | Planned |
| US-27 | AI-use disclosure per matter | S7 | `int-US-27-01`; `web-US-27-*` | 4 | Planned |
| US-28 | Tamper-evident audit pack | S7 | `int-US-28-01` (integrity verified); depends on EN-8 | 4 | Planned |
| US-29 | Firm AI policy enforced | S7 | `int-US-29-01..02` (AI disabled for disallowed matter type) | 4 | Planned |
| US-30 | Playbook suggestions from overrides | S8 | `api-US-30-*` | — | Planned |

## Cross-cutting (NFR) suites

| NFR | Suite | Gate |
| --- | --- | --- |
| NFR-4 access | `int-EN-7-*` authz matrix | 1 |
| NFR-6 audit | `api-EN-8-*`, `int-US-28-01` | 1, 4 |
| NFR-7 AI governance | `api-EN-6-*`, `static` ORC-1 rule | 0, 1 |
| NFR-8 zero fabricated authorities | `eval-redteam-EN-11` | 3, 4 |
| NFR-9 clause accuracy | `eval-gold-EN-10` | 2, 4 |
| NFR-10 performance | perf suite (S7–S8) | 4 |
| NFR-13 DOCX fidelity | `golden-EN-9-*` | 1 |
| NFR-15 accessibility | axe in `e2e-*`, manual pass | 4 |
