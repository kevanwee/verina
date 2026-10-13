# Verina

> **Experiment:** exploring Scrum principles with AI agents working as a collaborative software team.

Verina is an experimental AI workbench for contract review. The current prototype uses synthetic examples and mock AI clients. It is not a production legal service; live model calls and client-data processing remain disabled.

The [team process](docs/process/README.md) records the shared Definition of Done, planning and review practices. Architecture and landing-page refinements are developed through role-attributed commits and reviewable pull requests. Confidential planning, handoffs and supplied reference documents remain outside this repository.

## Layout

| Path | Contents |
| --- | --- |
| `apps/web` | Next.js + TypeScript web workspace |
| `apps/api` | FastAPI service (Python 3.12+) |
| `packages/` | Shared contracts (JSON schemas) |
| `evals/` | Evaluation sets (synthetic data only) |
| `docs/` | ADRs and engineering docs |

## Quick start

Requires Node 24 / npm 11 and Python 3.12+.

```bash
npm install                 # installs web workspace
npm run dev:web             # http://localhost:3000
npm run test:web

cd apps/api
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # .venv/bin/python on macOS/Linux
.venv/Scripts/python -m pytest
```

Contributors (human or AI): read [AGENTS.md](AGENTS.md) first.
