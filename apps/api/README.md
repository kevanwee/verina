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
bindings locally. Both the routes and provisioning are refused unless `VERINA_ENV` is
explicitly set to `local` or `test`; the settings default is not enough:

```bash
python -m verina.access.provision principal --tenant t-demo --actor a-lawyer --roles lawyer --display-name "Synthetic Lawyer"
python -m verina.access.provision bind --issuer https://idp.example.test/ --subject synthetic-sub-1 --tenant t-demo --actor a-lawyer
python -m verina.access.provision deactivate --tenant t-demo --actor a-lawyer
```

Mutations require an `Idempotency-Key` (UUID) header; updates, conflict checks and waivers
also require `If-Match` with the revision from the previous `ETag`.
