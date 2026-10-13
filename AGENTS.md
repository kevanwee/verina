# AGENTS.md — Verina team charter

Verina is a verified AI workbench for contract matters (Singapore law, small/mid firms and in-house teams). Every AI-generated legal assertion goes into a **Verification Ledger** and nothing reaches a client until each entry is verified against its source or attested by a named lawyer.

This file is the operating manual for every human and AI agent on the project. It is safe to commit. **Confidential material lives in `private/` (git-ignored, blocked by `.githooks/pre-commit`). Never copy its contents into committed files, code comments, commit messages, PRs or issues.**

## 1. Team

| Role | Who | Agent file | Owns |
| --- | --- | --- | --- |
| Product owner (senior legal counsel) | Human product owner | — | Product Goal, backlog order, stakeholder feedback, legal judgement, approvals |
| Scrum master | Main coordinating AI session (Claude or Codex) | — | Facilitation, coaching, impediment removal, coordinated agent delegation, handoffs, master prompt |
| Senior software engineer / tech lead | agent | `.claude/agents/verina-engineer.md` | Architecture, API, web wiring, DOCX, ADRs |
| AI/LLM engineer (added) | agent | `.claude/agents/verina-ai-engineer.md` | Orchestrator, prompts, ledger pipeline, evals |
| Senior QA (testing + CI/CD) | agent | `.claude/agents/verina-qa.md` | Test strategy, CI, gates, traceability |
| Senior cybersecurity analyst | agent | `.claude/agents/verina-security.md` | Threat model, data flow, hardening, controls |
| Senior UI/UX designer | agent | `.claude/agents/verina-designer.md` | Design system, flows, a11y, motion |
| Senior legal counsel (PDPA) | agent | `.claude/agents/verina-pdpa-counsel.md` | PDPA assessment, PII taxonomy, redaction rules, DPAs |

If an agent type is not registered in a session, spawn a general-purpose agent using the session's delegation tool and tell it: "Act as the role defined in `.claude/agents/<file>.md`; read it and follow it exactly." The role files and vendored skills apply in both Claude and Codex; record unavailable runtime hooks or capabilities in the handoff rather than claiming they ran.

## 2. Mandatory skills (PO instruction)

| Role | Must use |
| --- | --- |
| Designer | `taste-skill` (+ `minimalist-skill`, `redesign-skill`), `impeccable` (init, critique, audit; hooks on), `lenis` and `gsap` npm packages |
| PDPA counsel | LegalQuants: `lq-dpa-checklist-review`, `lq-local-first-legal-workspace`, `lq-proposition-checking`, `lq-sgcite`, `lq-bart-statutory-reference-checker`, `lq-adversarial-qc`; plugin `legalquants-transactional` |
| AI engineer | `claude-api`, `lq-proposition-checking`, `lq-sgcite`, `lq-bart-statutory-reference-checker`, `lq-text-provenance` |
| Engineer | `lq-redlines`, `lq-superdoc-redlines`, `lq-office-word-diff` (DOCX revision reference designs) |
| QA | `lq-adversarial-qc` for gate certificates |

Third-party skills are vendored in `.claude/skills/` (see `PROVENANCE.md`). Impeccable hooks and the LegalQuants plugin are enabled in `.claude/settings.json` (approved by PO, 13 Oct 2026).

## 3. Where things live

| Path | Contents | Committed? |
| --- | --- | --- |
| `private/PRODUCT_SPEC.md` | Research, requirements, NFRs, architecture | **No** |
| `private/ROADMAP.md` | Phases, sprints, gates, dates | **No** |
| `private/BACKLOG.md` | User stories, acceptance criteria, owners, points | **No** |
| `private/sprints/SPRINT-NN.md` | Sprint goal, task board, status | **No** |
| `private/handoffs/YYYY-MM-DD-HHMM-<who>-<topic>.md` | Handoffs | **No** |
| `private/MASTER_PROMPT.md` | Paste into a fresh session to resume | **No** |
| `docs/adr/`, `docs/security/`, `docs/compliance/`, `docs/design/`, `docs/testing/` | Engineering docs (no confidential strategy) | Yes |
| `apps/api`, `apps/web`, `packages/`, `evals/` | Code | Yes |

## 4. Working agreement

- **Scrum accountabilities:** the specialist roles above contribute as Developers to one team. The Product Owner orders the Product Backlog; Developers size work and own/adapt the Sprint Backlog; the Scrum Master facilitates and removes impediments. Agent dispatch is runtime coordination, not a management hierarchy. See `docs/process/SCRUM_WORKING_AGREEMENT.md`.
- **Cadence:** 2-week sprints. Sprint 0 is setup (13–16 Oct 2026). Planning at sprint start, review + retro at end, written to the sprint file.
- **Flow of a story:** PO-approved story → designer flow (UI stories) → PDPA/security review if it touches personal data or external endpoints → build with tests → QA verifies acceptance criteria → PO accepts.
- **Branching:** protect `main` when repository settings permit; feature branches `us-<id>-<slug>`; small PRs. Record actual protection status rather than assuming it. Agents commit/push only when authorized; the current PO request authorizes creating the private repository and publishing scoped role commits. Serialize Git index/branch operations in a shared checkout; use separate worktrees once a base commit exists. Automation authors must be identified as agents.
- **Data:** synthetic fixtures only. No real client documents in the repo or in prompts during development.
- **Model calls:** only through `apps/api/src/verina/ai/` (orchestrator); every call audit-logged.
- **Blocking rules:** unredacted personal data to an external model, a Critical/High security finding, or a failed gate blocks release until the PO records a decision.

## 5. Definition of Done (every task)

The canonical, shared quality commitment is `docs/process/DEFINITION_OF_DONE.md`. Acceptance criteria describe each item's behavior; the Definition of Done describes the quality required of the integrated Increment. Unfinished work returns to the Product Backlog and is never counted as Done or presented as a usable Increment.

1. Acceptance criteria met, with inspectable evidence tied to the exact revision.
2. Integrated lint, type-check, tests and applicable build green; required hosted CI checks green. Skipped checks and local-only passes do not satisfy hosted evidence.
3. Required security, PDPA and design reviews evidenced; unresolved release-blocking findings visible.
4. Architecture/docs/traceability updated where behavior or a decision changed.
5. Confidentiality guard passes; scoped changes reviewed; **handoff written** and sprint board updated. PO feedback/acceptance and release authorization are recorded separately from technical quality, never invented.

## 6. Handoff template (mandatory after every task or session)

File: `private/handoffs/YYYY-MM-DD-HHMM-<agent>-<topic>.md`

```markdown
# Handoff — <agent> — <topic>
Date: YYYY-MM-DD HH:MM SGT · Sprint: NN · Stories/tasks: <ids>

## Done
- <what changed, with file paths>

## Evidence
- <tests run + result, screenshots, eval scores, commands>

## Decisions (and why)
- <decision> — <reason> (ADR link if any)

## Open issues / risks
- <issue> — owner — severity

## Needs from others
- <role>: <request>

## Next steps
1. <the very next action a fresh session should take>
```

The scrum master also keeps `private/handoffs/LATEST.md` pointing to the newest handoffs and the current state in five lines.

## 7. Commands (verified 13 Oct 2026 on Windows 11, Node 24, Python 3.14)

Run from the repo root unless a `cd` is shown. On macOS/Linux use `.venv/bin/python` instead of `.venv/Scripts/python`.

| Purpose | Command |
| --- | --- |
| Install web deps | `npm install` |
| Web dev server | `npm run dev:web` (http://localhost:3000) |
| Web tests (Vitest) | `npm run test:web` |
| Web lint (ESLint) | `npm run lint:web` |
| Web type-check | `npm run typecheck:web` |
| Web production build | `npm run build:web` |
| API venv + install | `cd apps/api && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"` |
| API tests | `cd apps/api && .venv/Scripts/python -m pytest` (coverage: add `--cov`) |
| API lint + format check | `cd apps/api && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .` |
| API type-check | `cd apps/api && .venv/Scripts/python -m mypy` |
| API dev server | `cd apps/api && .venv/Scripts/python -m uvicorn verina.main:create_app --factory --reload` (GET /health) |
| All checks (same as CI) — Git Bash / macOS / Linux | `bash scripts/check.sh` (add `--install` to run `npm ci` + pip install first) |
| All checks (same as CI) — Windows PowerShell | `powershell -ExecutionPolicy Bypass -File scripts\check.ps1` (add `-Install`) |
| Repo guard only (private/, secret files, hook, model-SDK boundary) | `apps/api/.venv/Scripts/python scripts/guard.py` |
| API security scans | `cd apps/api && .venv/Scripts/python -m bandit -c pyproject.toml -r src && .venv/Scripts/python -m pip_audit --skip-editable` |
| npm audit (blocking scope) | `npm audit --audit-level=high --omit=dev` |

gitleaks and semgrep are optional locally: the check scripts use them if they are on PATH (or `SEMGREP=<path>`) and otherwise skip them with a message. CI always runs both. CI workflow: `.github/workflows/ci.yml`; strategy, gates and policies: `docs/testing/TEST_STRATEGY.md`.
