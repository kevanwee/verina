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

## Local connected accounts (development only)

The public preview stays disconnected. These steps do not authorize client data or
hosted activation.

1. Copy the root `.env.example` to ignored `apps/web/.env.local`. Fill it locally;
   use a Supabase publishable/anon key, never a service-role/secret key.
2. In Supabase Authentication > URL Configuration set Site URL to
   `http://localhost:3000` and allow exactly `http://localhost:3000/auth/callback`.
   Do not use wildcard redirects. Enable email, disable public signup/anonymous sign-in,
   and configure asymmetric signing with JWT lifetime at most 900 seconds.
3. Apply reviewed API migrations and bootstrap the application directory administrator
   using the accounts API instructions. An Auth account alone grants no application role.
   Start the API with development authentication settings and reviewed project JWKS.
4. Set the local connected flag to 1; run `npm run dev:web`, open `/sign-in`, enter a
   provisioned synthetic development account and press Send sign-in code. Use the email
   code or expected link. Links first show Confirm sign-in; Continue to Verina is a
   same-origin POST. A scanner GET cannot consume the link.
5. Verify account permissions and matter save/reload against the API/database, including
   after an API restart. Keep the public deployment disconnected until the hosted gate
   is evidenced. Shared limiting, CAPTCHA, custom SMTP, script CSP and privacy review
   remain required. No resource upgrade or live model is enabled here.

The configured public origin must match the browser's exact origin. HTTPS is required
except for local loopback. Restart the development server after changing variables.
Never put configuration secrets into chat, screenshots, commits or issues.
