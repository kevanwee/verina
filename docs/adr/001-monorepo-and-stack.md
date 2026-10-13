# ADR 001: Monorepo layout and base stack

- Status: Accepted
- Date: 2026-10-13
- Deciders: Tech lead (engineer agent), scrum master; PO informed

## Context

Verina needs a web workspace, an API with document processing and AI orchestration, shared data contracts, and evaluation sets. The team is small and mostly AI agents working in parallel, so one repository with clear ownership boundaries keeps changes reviewable. The development machine is Windows 11 with Node 24, npm 11 and Python 3.14; Docker and uv are not available.

## Decisions

1. **One repository, npm workspaces.** Root `package.json` declares workspaces `apps/web` and `packages/*`. npm ships with Node, so no extra tool (pnpm, Turborepo) is needed yet. Root scripts `dev:web`, `test:web`, `lint:web`, `typecheck:web` and `build:web` proxy to the web workspace.
2. **Web: Next.js (App Router) + TypeScript + ESLint**, scaffolded with `create-next-app` (Next 16.4). No Tailwind: the design system uses CSS custom properties (tokens) owned by the designer. Tests use Vitest + Testing Library + jsdom.
3. **API: Python + FastAPI**, package `verina` in a `src/` layout under `apps/api`, built with an app factory (`verina.main:create_app`). Settings come from environment variables via `pydantic-settings` (prefix `VERINA_`). Tooling: pytest (+ pytest-cov), ruff (lint + format), mypy in strict mode.
4. **Python compatibility: 3.12+.** `requires-python = ">=3.12"`, ruff and mypy target 3.12, and `.python-version` says 3.12 so CI uses the oldest supported version. Local development runs on 3.14; all current dependencies install from wheels on 3.14. CI should test on 3.12 and 3.14.
5. **Python environment: stdlib `venv` + pip** at `apps/api/.venv`, editable install `pip install -e ".[dev]"`. Dependencies use compatible ranges (for example `fastapi>=0.143,<0.144`) until a lockfile tool is adopted.
6. **Data: Postgres + pgvector is the target store.** Docker is unavailable locally, so unit tests use SQLite where possible. Postgres-specific behaviour (pgvector, append-only audit constraints) will be tested in CI service containers or a cloud dev database. Code must not depend on SQLite-only behaviour.
7. **Durable workflows: Temporal is deferred to Sprint 1/2.** The review workflow starts as an explicit state machine in the API; Temporal is adopted once long-running and retryable steps (email intake, multi-document review) arrive.
8. **AI calls are isolated.** Subpackage `verina.ai` hosts the orchestrator; no other module calls a model SDK directly, and every call is audit-logged. Placeholder subpackages `audit`, `matters`, `documents` and `ledger` mark the domain boundaries.
9. **Baseline HTTP hardening from day one.** A middleware sets security headers on every response; OpenAPI docs are served only in `local`/`test` environments.

## Consequences

- One `npm install` at the root sets up the web app; the API is set up separately with venv + pip.
- Without a Python lockfile, builds are reproducible only within the pinned minor ranges; revisit when CI lands (EN-2).
- `eslint-config-next` 16.4 pulls in a `braces`/`micromatch` chain that `npm audit` flags as high severity. It is a dev-time lint dependency and not shipped to browsers; track it in the dependency audit gate.
- Starlette 1.7 deprecates `httpx` for its `TestClient` in favour of `httpx2`; tests pass with a deprecation warning. Revisit when FastAPI's test client guidance settles.
