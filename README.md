# Verina

Verified AI workbench for contract review.

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
