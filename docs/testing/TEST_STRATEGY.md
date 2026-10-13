# Verina test strategy

Owner: verina-qa · Status: v0 (Sprint 0, EN-2) · Last updated: 2026-10-13

This document says how Verina is tested, which checks block a merge, and what evidence certifies each release gate. It holds no confidential product strategy. Story and enabler ids (US-n, EN-n) and requirement ids (NFR-n) point into the private backlog and spec. `TRACEABILITY.md` maps each id to its tests.

## 1. Principles

1. **Tests prove acceptance criteria.** Every Given/When/Then in a story becomes at least one automated test, or a recorded manual check if automation is not possible. The test is linked to the story id (§9).
2. **Synthetic data only.** No real contracts, client names or personal data in fixtures, prompts, evals or screenshots (§8).
3. **No live model calls in the default pipeline.** Unit and integration tests use the orchestrator's fake client. Live-model evals run in a separate, manually triggered job (§5.5).
4. **Deterministic or quarantined.** A flaky test is a bug (§7).
5. **The verification invariant is tested at every layer.** Nothing unverified may reach an export. Unit tests cover the status logic, integration tests cover the export block, e2e covers the user path, and the red-team set covers adversarial input.
6. **Fast default pipeline.** The CI run that gates a merge targets under 10 minutes wall-clock. Slower suites (golden DOCX at full size, evals, e2e on several browsers) run in separate jobs or on a schedule when they outgrow the budget.

## 2. Test pyramid

| Layer | Share (target) | Tool | Location | Runs | What it covers |
| --- | --- | --- | --- | --- | --- |
| Static | n/a | ruff, mypy (strict), ESLint, `tsc`, Bandit, Semgrep, gitleaks, guard script | config in `apps/api/pyproject.toml`, `apps/web`, `.semgrep/`, `.gitleaks.toml`, `scripts/guard.py` | every push and PR | style, types, unsafe patterns, secrets, model-SDK boundary (ORC-1), confidential paths |
| Unit (api) | ~60% of tests | pytest 9, pytest-cov | `apps/api/tests/` (mirrors `src/verina/`) | every push and PR | domain logic: ledger status rules, redaction, hashing, playbook rules, orchestrator with fake client |
| Unit/component (web) | ~20% | Vitest 5, Testing Library, jsdom | `apps/web/__tests__/`, co-located `*.test.tsx` | every push and PR | components, hooks, client state, reduced-motion fallbacks |
| Integration (api) | ~12% | pytest + FastAPI TestClient (httpx2), SQLite in S0, Postgres service container from S1 | `apps/api/tests/integration/` | every push and PR | HTTP contract, authz matrix, audit chain, export gate, DB constraints and row-level security |
| Contract | small | OpenAPI schema snapshot + generated TS types in `packages/contracts` | `apps/api/tests/contract/` | every push and PR (from S1) | API and web agree on request and response shapes |
| End-to-end | ~5% | Playwright (planned S1) | `apps/web/e2e/` | PR (Chromium) + nightly (Chromium, Firefox, WebKit) | critical journeys: intake, review, ledger verify or attest, export blocked/allowed, sign-off |
| Accessibility | every e2e page | axe-core via `@axe-core/playwright`; `vitest-axe` for components | with e2e and unit | PR | WCAG 2.2 AA automated rules (NFR-15); manual keyboard + screen-reader pass per gate |
| Fidelity | fixed corpus | golden DOCX round-trip harness (EN-9) | `apps/api/tests/golden/`, corpus in `evals/golden-docx/` | PR (smoke subset) + nightly (all 30) | NFR-13: tracked changes, numbering, tables, comments survive ingest → export |
| AI evals | fixed sets | gold-set harness (EN-10), red-team harness (EN-11), PII test set | `evals/` | manual and nightly job, gate runs | NFR-8, NFR-9, redaction recall (US-7) |

The shares are a guide, not a quota. If a behaviour can be tested lower in the pyramid, test it there.

## 3. Tools and conventions

### 3.1 API (Python)
- **pytest** with `--strict-markers`. Tests import the app through `create_app(Settings(env="test"))`.
- **Coverage** with pytest-cov, line and branch, `fail_under = 85` in `[tool.coverage.report]`. This is the single source of the threshold, and CI fails below it. Coverage shows what is untested. It does not show that the tests are good, so reviewers still check assertions.
- **Starlette TestClient** uses `httpx2` (dev extra). The older `httpx` fallback raised a `StarletteDeprecationWarning`, which is fixed.
- **Fixtures** are factories in `tests/factories.py` (from S1) that produce synthetic tenants, matters, documents and ledger entries.
- **Time and randomness** are injected (clock and id providers), never read globally, so tests are deterministic.

### 3.2 Web (TypeScript)
- **Vitest** with jsdom and Testing Library. Query by role and accessible name, not by test ids, unless no accessible handle exists.
- **Browser APIs that jsdom lacks** (`matchMedia`, `IntersectionObserver`, `ResizeObserver`) are stubbed once in `vitest.setup.ts`. Motion libraries (GSAP, Lenis) must also run under `prefers-reduced-motion: reduce` in tests.
- **Coverage thresholds for web** are added in S1, once real components exist. Starting target: 80% lines on `app/components` and `lib`.

### 3.3 End-to-end (planned S1)
- **Playwright** against `next start` and `uvicorn` with a seeded synthetic database. No external network: SSO and LawNet lookups and model calls hit local fakes.
- Each spec runs an axe scan on every page it visits and fails on any serious or critical violation.
- Traces and screenshots are kept as CI artefacts for failures only, and must contain synthetic data only.

### 3.4 Golden DOCX suite (EN-9, Gate 1)
- The corpus holds 30 synthetic contracts with tracked changes from several authors, multi-level numbering, tables, comments, headers and footers, fields and cross-references. Each file has a `manifest.json` entry that records its features and provenance (generator script or author, "synthetic").
- The harness ingests each file, exports it with no edits, and diffs the normalised OOXML parts (document, numbering, comments, styles). For each file it also checks that inserting a redline keeps every pre-existing revision and its author (US-6, US-15).
- Pass condition: zero unexpected diffs on all 30 files. Any accepted normalisation, such as `rsid` attributes, is listed in the harness and reviewed by ENG and QA.

### 3.5 AI evaluation harnesses (EN-10, EN-11)
- **Gold set (EN-10):** 200 synthetic Singapore-law commercial clauses with lawyer labels. The harness reports overall and per-category agreement, a confusion matrix, model and prompt-template versions, and the hashes of the inputs.
- **Red-team set (EN-11):** at least 100 items: fabricated cases, wrong pinpoints, misquoted or repealed statute sections, paraphrased citations that evade extraction, and prompt injection in document text. The metric that matters is the **count of fabricated or unverified authorities that reach an export**, which must be zero.
- **PII test set (Gate 1):** synthetic documents seeded with NRIC/FIN, phone numbers, addresses, bank accounts and personal names in Singapore formats, using the PDPA counsel's taxonomy. The harness measures redaction recall per category on the logged prompt and checks that re-identification restores the original text.
- Evals record model id, template id and version, dataset version and seed. A run without that metadata does not count as gate evidence.

### 3.6 Security tests
- An **authz matrix** (EN-7, from S1) is generated from the roles × resources × actions table. Every cell has a test, and cross-tenant or no-matter-access cases must fail closed (NFR-4, API-2, DS-1).
- **Audit-chain tamper tests** (EN-8) edit, delete or reorder events and expect verification to fail.
- **Prompt-injection corpus** (from S5) is part of the red-team set (LLM-1).
- The static scanners are listed in §6.

## 4. Warnings policy (pytest)

`apps/api/pyproject.toml` sets:

```toml
filterwarnings = ["default", "error:::verina.*", "error:::tests.*"]
```

- A warning raised in our own modules (`verina.*`, `tests.*`) fails the test run. This includes a third-party deprecation whose `stacklevel` points at our call site, because then our code is the thing that has to change.
- Any other third-party warning is shown in the summary but does not fail the run. QA reviews the warnings summary at each gate and raises an issue for anything that will break on the next upgrade.
- The filter was checked on 2026-10-13 with a throwaway test: a warning attributed to `tests` failed the run, and one attributed to another module passed with a warning.

## 5. CI pipeline

Workflow file: `.github/workflows/ci.yml`. To run its blocking checks locally, use `scripts/check.sh` (Git Bash, macOS, Linux) or `scripts/check.ps1` (Windows PowerShell). Both run guard → api → web → security, keep going after a failure, and print a summary. `--install` / `-Install` runs `npm ci` and the pip install first, as CI does. Local runs use the installed Python version rather than CI's two-version matrix. Gitleaks and Semgrep are skipped with an explicit summary if unavailable; an exit code of zero with skips does not establish those scanner results. CI and both local scripts additionally run the informational full npm audit. Local success does not establish hosted CI or branch-protection status.

| Job | Runs on | Steps | Blocks merge |
| --- | --- | --- | --- |
| `guard` | ubuntu-24.04, Python 3.12 | `scripts/guard.py`: checks tracked and untracked-not-ignored files, case-insensitively; blocks `private/`, `samples-real/`, `.env`, `.env.*`, `*.env`, `*.pem`, `*.key`, `*.p12`, `*.pfx` and `id_rsa`-style SSH keys. `.env.example` is allowed only outside confidential roots. Also requires the hook and enforces model SDK imports within `apps/api/src/verina/ai/` (ORC-1) | yes |
| `api` | matrix Python 3.12 and 3.14 | `pip install -e .[dev]`, ruff check, ruff format --check (api and `scripts/`), mypy strict, pytest with coverage ≥ 85% | yes |
| `web` | Node 24 | `npm ci` at root, lint, type-check, Vitest, `next build` | yes |
| `security` | ubuntu-24.04 | gitleaks 8.30.1 (CLI, SHA-256 verified, full history, `.gitleaks.toml`); `npm audit --audit-level=high --omit=dev`; full `npm audit` (informational); `pip-audit` on the API environment; Bandit on `apps/api/src`; Semgrep 1.180.0 with project rules in `.semgrep/` (offline, no metrics) | yes, except the informational audit |

Hardening of the pipeline itself (SC-5):
- Every action is pinned by full commit SHA, with the tag in a trailing comment: `actions/checkout` v7.0.1, `actions/setup-python` v7.0.0, `actions/setup-node` v7.1.0.
- `permissions: contents: read` at workflow level, and no job asks for more. No secrets are referenced. `persist-credentials: false` is set on every checkout.
- `concurrency` cancels superseded runs on the same ref, and every job has a `timeout-minutes` limit.
- `IMPECCABLE_HOOK_DISABLED=1` is set in CI and in the local scripts (REVIEWS.md R-001 item 7).
- Gitleaks is downloaded as a pinned release and checked against a recorded SHA-256 rather than through the marketplace action. This avoids the action's licence-key requirement for organisation accounts and an extra third-party action. Update the version and the hash together.
- Semgrep is installed into its own venv, so its large dependency tree is not part of the `pip-audit` scope for the product.

### 5.1 Dependency audit decision
- **npm:** the implemented blocking check is `npm audit --audit-level=high --omit=dev`, which covers production dependencies only. A full audit re-run on 2026-10-13 reports 5 high dependency entries, all in the dev-only lint chain (`eslint-config-next` → `@next/eslint-plugin-next` → `fast-glob` → `micromatch` → `braces`); these reflect one underlying advisory and its affected dependents. No patched braces version is listed in the [official advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm); the npm registry reports 3.0.3 as the latest version on this date. An override to 3.0.4 would reference an unavailable package, not remediate it. The audit's suggested fix changes `eslint-config-next` to v14, outside the current Next 16 toolchain. The production-only blocking scope is a QA proposal pending security disposition and any required PO decision; it is not a risk acceptance. Existing controls: the full audit remains informational in CI, lockfile installs (`npm ci`), and a re-check at every gate. High findings remain release-blocking under AGENTS.md until remediated or the PO records a decision.
- **Python:** `pip-audit` audits the installed API environment (runtime and dev extras) and skips the editable `verina` package itself. There is no lockfile yet (ADR 001). Hash-pinned requirements are planned when the dependency set settles (SC-1).

### 5.2 Required checks and branch protection (B-9)
After a hosted workflow run, protect `main` and confirm the required check names from that run. The workflow currently declares `guard (private/, secrets files, hooks, ORC-1)`, `api (Python 3.12)`, `api (Python 3.14)`, `web (Node 24)` and `security (gitleaks, npm audit, pip-audit, bandit, semgrep)`. Add CODEOWNERS after real reviewer handles are known; do not invent GitHub accounts for role names. Branch protection is a repository setting and requires admin access; source publication does not establish it.

### 5.3 Time budget
The jobs run in parallel. The default pipeline targets under 10 minutes wall-clock; hosted duration has not yet been measured. If it goes over 10 minutes, move the slowest non-critical suite to a separate job while retaining all merge-blocking checks.

### 5.4 Planned additions

| Sprint | Addition |
| --- | --- |
| S1 | Postgres service container; authz matrix; audit-chain tests; Playwright + axe job (Chromium); web coverage thresholds; Dependabot or Renovate; CODEOWNERS; PROVENANCE hash check for `.claude/` (REVIEWS.md R-001 item 5) |
| S2 | Golden DOCX smoke subset per PR plus nightly full corpus; PII test-set harness |
| S3–S4 | Gold-set eval job (manual or nightly, live model with an environment-scoped secret, never on fork PRs) |
| S5–S6 | Red-team harness and prompt-injection corpus; export-gate e2e |
| S7–S8 | Performance tests (NFR-10), audit-pack integrity e2e, pen-test regression tests |

### 5.5 Live-model evals (when they exist)
These run in a separate workflow (`evals.yml`) on `workflow_dispatch` and schedule only. They use a GitHub environment with required reviewers and a scoped model key. They never run on `pull_request` from forks, and their output artefacts contain synthetic data only.

## 6. Static and security checks summary

| Check | Tool | Scope | Threat or control |
| --- | --- | --- | --- |
| Secrets in history | gitleaks | whole git history | SC-2, ORC-8, B-3 |
| Secrets at commit time | `.githooks/pre-commit` | staged files | SC-2, SC-3 |
| Confidential or secret paths | `scripts/guard.py` | tracked + untracked-not-ignored paths from `git ls-files --cached --others --exclude-standard` | SC-3 |
| Model SDK outside orchestrator | `scripts/guard.py` + Semgrep rule | Python and TS/JS | ORC-1, C-7.1 |
| HTML injection sink | Semgrep `verina-dangerously-set-inner-html` | TS/JS | WEB-2 |
| Python SAST | Bandit | `apps/api/src` | DS-6 and general |
| Vulnerable dependencies | `npm audit` (prod), `pip-audit` | lockfile and API env | SC-1 |
| Pipeline integrity | SHA-pinned actions, read-only token | workflow | SC-5 |

## 7. Flaky-test policy

- A test that passes and fails on the same commit is flaky, and **a flaky test is a bug**.
- Whoever sees it first opens an issue labelled `flaky`, with the failing run link and the seed or trace.
- Quarantine only with a reference to that issue: `@pytest.mark.skip(reason="flaky: #<issue>")` or `test.skip("flaky: #<issue>")`. Never delete the test, add a bare skip, or wrap it in a retry without an issue. A quarantine without an issue reference fails review.
- Quarantined tests are listed in the gate certificate. More than 2 open quarantines, or any quarantine of a Gate-critical test (export gate, ledger status, redaction, authz, audit chain), blocks gate certification.
- The owner fixes the test within the sprint. Automatic retries (`--reruns`, Playwright `retries`) are allowed only in nightly e2e, and a pass on retry is still reported as flaky.
- Typical causes to look for: real time or timezone, unordered collections, shared state between tests, network access, animation timing (use reduced motion in tests), and randomness without a seed.

## 8. Synthetic-fixture policy

- Every fixture is synthetic: invented parties, people, addresses and identifiers. NRIC/FIN and phone values use reserved or obviously fake patterns that still match the detectors. For example, generate NRIC-format strings with a valid checksum from a fixed seed, and never copy a real one.
- No real client documents, no documents from a lawyer's real matters, and no public court filings that name private individuals. `samples-real/` is git-ignored, and the guard blocks it.
- Each corpus (golden DOCX, gold set, red-team, PII set) has a manifest that records how every item was produced (generator script, template, or author) and the label "synthetic". Items without provenance are removed.
- Public statute text (SSO) may be used verbatim as reference material, with source URL and version date recorded.
- Screenshots, Playwright traces and eval outputs in CI artefacts must come from synthetic data only.
- When in doubt, verina-pdpa-counsel decides. A suspected real-data fixture is treated as an incident: remove it, purge it from history before any push, and record it in a handoff.

## 9. Traceability and test ids

- Every test that proves an acceptance criterion is tagged with the story or enabler id:
  - pytest: `@pytest.mark.story("US-7")` (the marker is registered in `pyproject.toml`; strict markers reject typos).
  - Vitest and Playwright: the id is the first word of the test or describe title, for example `describe("US-22 export gate", ...)`.
- Planned test ids in `TRACEABILITY.md` use the form `<suite>-<id>-<nn>`, for example `api-US-22-01` or `e2e-US-22-01`.
- `TRACEABILITY.md` is updated in the same PR that adds or changes the tests. Under the Definition of Done, a story is not done until its row shows passing tests in CI.

## 10. Release gates

QA certifies each gate in a handoff that includes an `lq-adversarial-qc` certificate. The criteria below are the test-evidence part of each gate. Business criteria stay with the PO.

| Gate | When | Test criteria (all must hold) | Evidence |
| --- | --- | --- | --- |
| Gate 0: Setup exit | end of S0 | CI green on the skeleton across all four jobs; local check scripts green; guard shown to fail on planted confidential paths and a planted model-SDK import | CI run link, script output, this document |
| Gate 1: Ingestion fidelity and redaction | end of S2 | Golden DOCX harness reports 0 unexpected diffs on all 30 files (NFR-13, EN-9); US-6 counterparty revisions intact and attributed after ingest and export; PII test set shows no personal identifiers in logged prompts and correct re-identification (US-7), with per-category recall reported; authz matrix and audit-chain suites green (EN-7, EN-8); no open Critical or High security finding on ingestion | harness report, eval report with model and template versions, CI run, security sign-off |
| Gate 2: Review quality | end of S4 | Gold-set clause agreement ≥ 85% on the 200-clause set (NFR-9 interim; ≥ 90% at Gate 4), with per-category breakdown; every finding has a verbatim quote that exists in the source (US-11 property test); playbook version stamped on every review (US-10) | eval report, CI run |
| Gate 3: Verification | end of S6 | **Zero** fabricated or unverified authorities exported across the whole red-team set (NFR-8, EN-11); export blocked while any blocking ledger entry exists (US-22 integration and e2e); unlinked case citations never auto-verified (US-21); prompt-injection items do not change risk scores (LLM-1) | red-team report, CI run, e2e trace |
| Gate 4: GA decision | end of S8 | Gold-set agreement ≥ 90% (NFR-9); red-team still at zero fabricated exports on a fresh run; no open Critical or High security finding (SEC) or failed PDPA item; WCAG 2.2 AA: axe clean and manual keyboard and screen-reader pass on critical journeys (NFR-15); performance budget met (NFR-10); audit pack integrity verified end to end (US-28); speed benchmark result recorded for the PO | full regression run, eval reports, pen-test closure, a11y report |

A gate fails if any criterion fails, if a gate-critical test is quarantined, or if evidence lacks the version metadata in §3.5. A failed gate blocks release until the PO records a decision (AGENTS.md §4).

## 11. Roles

- **verina-qa:** this strategy, CI, harness wiring, traceability and gate certificates.
- **Story owners:** write the unit and integration tests with the code. QA reviews them against the acceptance criteria.
- **verina-ai-engineer:** eval datasets and metrics. QA wires them into CI and certifies the runs.
- **verina-security:** scanner rules (`.semgrep/`, `.gitleaks.toml` allowlist), and the triage of audit findings.
- **verina-pdpa-counsel:** the PII taxonomy for the PII test set, and fixture-provenance disputes.

## 12. Delivery and test-evidence review

See DELIVERY_PLAN.md for the proposed staged delivery workflow and TEST_EVIDENCE_REVIEW.md for the acceptance-test review standard. Neither document establishes hosted CI, deployment or release readiness. CI runs for main, us-* feature branch pushes and pull requests; duplicated push/PR evidence refers to the same commit, not two independent reviews.

The shared quality commitment is [Definition of Done v1](../process/DEFINITION_OF_DONE.md). PO acceptance, a Sprint Review, deployment and release authorization remain distinct. Until hosted checks and applicable reviews are evidenced, local passing work is ready for review rather than Done.
