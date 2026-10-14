# Verina API

FastAPI service. Python 3.12+ (developed on 3.14).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows; use .venv/bin/python on macOS/Linux
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy
.venv/Scripts/python -m uvicorn verina.main:create_app --factory --reload
```

Configuration is read from environment variables prefixed `VERINA_` (see `.env.example`).

## Authenticated matter API (disabled by default)

`VERINA_MATTERS_API_ENABLED=true` registers `/v1/matters` routes that verify bearer tokens
against a configured static JWKS and resolve tenant, actor and roles from the Verina identity
directory ([ADR 007](../../docs/adr/007-verified-token-identity-and-matter-api.md)). Apply
migrations first (`python -m alembic upgrade head`), then seed synthetic principals and
bindings locally. Local static-JWKS use requires `VERINA_ENV` explicitly set to `local` or `test`; the settings
default is not enough. The reviewed Supabase development profile adds the configuration gate
described below; staging and production remain refused:

```bash
python -m verina.access.provision principal --tenant t-demo --actor a-lawyer --roles lawyer --display-name "Synthetic Lawyer"
python -m verina.access.provision bind --issuer https://idp.example.test/ --subject synthetic-sub-1 --tenant t-demo --actor a-lawyer
python -m verina.access.provision deactivate --tenant t-demo --actor a-lawyer
```

Mutations require an `Idempotency-Key` (UUID) header; updates, conflict checks and waivers
also require `If-Match` with the revision from the previous `ETag`.

## Accounts on the Supabase development project (ADR 009)

The same switch also registers `/v1/me`, `/v1/admin/organizations*` and
`/v1/organizations/{id}/members*` ([contract](../../docs/api/ACCOUNTS_CONTRACT.md),
[ADR 009](../../docs/adr/009-supabase-identity-accounts-and-postgres.md)). To run against the
Supabase dev project (Free plan, Singapore):

1. **Collect two secrets in the Supabase dashboard** (never paste them into chat, issues or
   commits):
   - *Connect* -> *Session pooler* connection string (IPv4; the free direct connection is
     IPv6-only). It looks like
     `postgresql://postgres.<ref>:<password>@<pooler-host>:5432/postgres`.
   - *Project Settings* -> *API Keys* -> a **secret** key (`sb_secret_...`).
2. **Create `apps/api/.env`** (git-ignored; the repo guard refuses to commit it). Copy the
   "Supabase development project" block from `.env.example`, uncomment it, and fill in:
   - `VERINA_DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@<pooler-host>:5432/postgres?sslmode=require`
     (percent-encode special characters in the password; keep `sslmode=require`; do not use
     the transaction pooler on port 6543);
   - `VERINA_SUPABASE_SECRET_KEY=sb_secret_...`;
   - `VERINA_AUDIT_HEAD_KEY=` a fresh random value of at least 32 bytes
     (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Keep it: losing it
     makes the existing audit heads unverifiable.
3. **In Supabase** *Authentication* -> *URL Configuration*, add the invite redirect
   (`http://localhost:3000/auth/callback`, or whatever `VERINA_AUTH_INVITE_REDIRECT_URL` is) to
   the redirect allow list. The built-in mailer sends only 2 e-mails per hour; configure
   custom SMTP before inviting more people.
4. **Apply migrations** (from `apps/api`, with the `.env` in place):

   ```bash
   .venv/Scripts/python -m alembic upgrade head
   ```

   Migration 0006 enables RLS and revokes the Supabase Data API roles (`anon`,
   `authenticated`) from every Verina table, so the public anon key cannot read them.
5. **Bootstrap the platform administrator** (once; refuses if one exists):

   ```bash
   .venv/Scripts/python -m verina.access.provision bootstrap-platform-admin --email you@example.com
   ```

   Supabase e-mails an invitation; accept it to set up the account. The address is not stored
   in Verina.
6. **Start the API in development**:

   ```bash
   .venv/Scripts/python -m uvicorn verina.main:create_app --factory --port 8000
   ```

   With the PO's Supabase access token, `GET /v1/me` returns `"platform_admin": true`. Create
   an organization with `POST /v1/admin/organizations`, then invite its first `tenant_admin`
   with `POST /v1/organizations/{id}/members`.

Free plan caveats: the project pauses after a week without activity (resume it in the
dashboard; the API answers 503 meanwhile), there are no backups or point-in-time recovery, and
the database is limited to 500 MB. Treat the dev database as disposable and keep synthetic
data only until security and PDPA reviews approve real users.
