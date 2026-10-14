# ADR 009: Supabase identity, accounts and organizations, and Supabase Postgres

Status: Proposed (engineering), for the **development** environment only. Needs verina-security review (new external endpoints: Supabase JWKS and Auth admin API) and verina-pdpa-counsel review (member e-mail addresses; Supabase as processor) before any real person is invited. Staging and production remain refused by code.

Builds on [ADR 007](007-verified-token-identity-and-matter-api.md). HTTP contract: [docs/api/ACCOUNTS_CONTRACT.md](../api/ACCOUNTS_CONTRACT.md). Story: US-47 (accounts and organizations), US-54 (directory audit).

## Context

The product owner wants a usable product: a Verina platform administrator creates customer organizations and ties user accounts to them, and users sign in. ADR 007 deliberately chose no identity provider and accepted only a static JWKS in local/test. The PO has now created a Supabase project (Free plan, Singapore region) for development, which supplies both authentication (Supabase Auth, ES256 access tokens) and a managed PostgreSQL database.

## Decision

### 1. Identity provider: Supabase Auth, verified locally

- Tokens are verified by Verina, not by calling Supabase per request. Keys come from the project's JWKS (`https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`) through a new bounded fetcher (`verina.access.jwks_fetcher`), closing the ADR 007 follow-up:
  - HTTPS only; no credentials, query or fragment; the JWKS host and port must equal the issuer's host and port; redirects are not followed and environment proxies are ignored.
  - `200` + JSON media type, streamed with a 64 KiB cap, then the same per-key validation as a static set (asymmetric allowlist, `kid`/`alg` required, public keys only).
  - TTL cache (default 600 s). An unknown `kid` triggers a refetch, but any refetch is rate-limited (default one per 30 s) and single-flight (concurrent callers wait for the in-flight fetch). There is never a fetch per request.
  - If refreshing fails, the last good set is used until `max_stale` (default 6 h) after it was fetched; then, and before the first success, verification raises `KeySourceUnavailable` and the API answers **503**, not 401.
  - `VERINA_AUTH_JWKS` (static) and `VERINA_AUTH_JWKS_URL` are mutually exclusive.
- `VERINA_AUTH_PROFILE=supabase` adds deny-only claim rules: `role` must be `authenticated` (refuses the anon and service-role keys, which are also JWT-shaped in legacy projects), `is_anonymous` must not be true, `sub` must be a UUID, `aal` must be `aal1` or `aal2`. Issuer `https://<ref>.supabase.co/auth/v1` and audience `authenticated` are configured exactly (strict audience as in ADR 007).
- `aal` is reported for step-up only. `VERINA_AUTH_REQUIRE_AAL2` requires MFA on every token; `VERINA_AUTH_ADMIN_REQUIRE_AAL2` requires it only when acting as a platform administrator (answered with an RFC 9470 `401 insufficient_user_authentication` challenge). **Both default to false** so the development project works before MFA enrolment; turning on the admin flag is a precondition for any non-development use.
- Token claims never grant tenant, role or admin status. `email` and `role` claims are not read for authorization.

### 2. Accounts and organizations model

- `organizations` (migration 0005): opaque `id` (`org_<uuid hex>`) that **is** the tenant id used by principals, matters and the audit chain; `name`; unique `slug` (`^[a-z0-9](-?[a-z0-9]){1,39}$`); `active`; `revision`; timestamps. Existing tenants are backfilled with an active organization each.
- Organization deactivation is enforced in `SqlIdentityAdapter.authenticate` and `current`: both join the principal to an *active* organization row (missing row fails closed). Every member fails authentication on the next request, and inside a matter mutation the organization row is held `FOR SHARE` (PostgreSQL) like the principal row.
- `directory_accounts` extends the ADR 007 directory minimally with the member e-mail address (unique, lower-cased) and `invite_status` (`pending`/`accepted`). Together with the `(issuer, subject)` binding primary key this enforces **one account, one organization**: inviting an address or a Supabase user that is already bound anywhere returns `409 account_exists`.
- Invitation: the server calls Supabase `POST /auth/v1/invite` (which creates the user and e-mails a link, or returns 422 for an already-confirmed user, in which case Verina looks the user up), then, in one transaction, creates the principal, the pending account, the binding and the audit event. The first `GET /v1/me` with that user's token marks the invitation accepted. There is no self-signup: a Supabase user who signs up independently gets `{"linked": false}`.
- No outbox: if the database transaction fails after Supabase sent the invite, the person has a Supabase user but no Verina binding; retrying with the same `Idempotency-Key` re-invites (Supabase re-sends or returns the same user) and binds.

### 3. Platform administrator versus organization administrator

- **Platform admin**: Verina operator. Grant lives only in `platform_admins (issuer, subject)`, never in a claim, and is created only by `python -m verina.access.provision bootstrap-platform-admin --email ...`, which refuses if any platform admin exists and runs only with `VERINA_ENV` explicitly `local`, `test` or `development`. A platform admin may have no organization. Platform admins manage every organization and its members; they get no matter access from the grant.
- **Tenant admin** (`tenant_admin` role, ADR 003): manages members of their own organization only. Removing the role from, or deactivating, the last active tenant admin of an organization is refused (`409 last_admin`). Neither role can create platform admins over HTTP.
- Every other caller gets the uniform `404 not_found` on these routes; an invalid or unlinked token gets 401 everywhere except `GET /v1/me`.
- Authority is re-read before protected reads, idempotent replay and writes, using the exact current identity binding, current roles and organization state or platform grant. PostgreSQL holds these authority rows with `FOR SHARE` through the transaction; a stale resolved caller cannot replay protected results or initiate an invitation after revocation. Invitation calls run with the tenant chain and authority locks held. The bounded network call therefore extends the database transaction; provider delivery still requires reconciliation if subsequent local persistence fails. `/v1/me` refreshes current roles, binding and active state, and invitation acceptance commits with its audit event in the same transaction.

### 4. Idempotency and audit

- Mutations require `Idempotency-Key`. A dedicated append-only `admin_idempotency (scope, operation_id)` table records actor key (SHA-256 of issuer and subject), action, request hash, resulting resource id, status and the audit event id. Replays return the *current* representation of that resource with the original status; a different actor, action or body returns `409 idempotency_key_reused`. The matter receipts table was not reused: its schema, revision step constraint and verification are matter-specific, and administrative payloads contain e-mail addresses that must not be stored in a receipt.
- Every organization, member, invitation and platform-admin write commits with a registered metadata-only `directory.changed` event in the same transaction. Organization and member events go to the organization's chain; platform-level events (bootstrap) and authentication failures go to the dedicated system chain `_verina_system` (the leading underscore cannot start a `TenantId`, so it never collides with an organization). Organization creation locks the system chain head first to serialize creation. Events never contain e-mail addresses, names or organization names; a target `(issuer, subject)` appears only as `hmac-sha256` with a key derived (HMAC, domain-separated) from `VERINA_AUDIT_HEAD_KEY`.
- Authentication failures (SEC M4): `auth.failure` events with reason class (`missing_credential`, `token_rejected`, `unbound`, `principal_inactive`, `organization_inactive`, ...), the route surface, and the keyed subject HMAC only when the token itself verified. Writes are rate-limited (60 burst, 1/s); suppressed failures are counted in the next event. An audit outage never changes the 401.
- The local provisioning CLI now audits each write in the tenant chain.

### 5. Rate limits (SEC L5, partial)

Per-process token buckets: authentication failures per client address (20 burst, one per 3 s, then `429 rate_limited` with `Retry-After` before authenticating) and invitations plus resends per account (10 burst, one per minute). Limits of this approach: each worker process has its own buckets (the effective limit scales with workers and resets on restart), and the client key is the socket peer, which behind a reverse proxy is the proxy unless trusted forwarded headers are configured. A shared limiter or edge/WAF control is required before multi-instance or internet exposure. Supabase's built-in e-mail sender allows only **2 e-mails per hour** per project; the default sender also refuses recipients who are not members of the Supabase project team. Configure reviewed custom SMTP before inviting arbitrary Verina members, regardless of volume.

### 6. Supabase Postgres and the Data API lock-down (migration 0006)

- Supabase exposes the `public` schema through its Data API (PostgREST) to the roles `anon` and `authenticated`, and its default privileges grant those roles access to new tables. The anon key is public, so unprotected Verina tables would be readable and writable from the internet.
- Migration 0006 runs only on PostgreSQL and only when either role exists. It enables row level security on every Verina table with **no policies**, revokes all table and trigger-function privileges from both roles (trigger functions also from `PUBLIC`; triggers still fire because EXECUTE is checked only at `CREATE TRIGGER`), and revokes their default privileges for future tables, sequences and functions created by the migrating role. Downgrade disables RLS and does not restore any grant.
- **RLS is not FORCEd.** The API connects as the table owner (`postgres`). `FORCE ROW LEVEL SECURITY` applies policies to the owner too; with no policies it would deny the application every row. The owner is trusted application code; the control targets the Data API roles. A later least-privileged application role will need explicit policies or `BYPASSRLS` (security review). As belt and braces the PO can also remove `public` from the exposed schemas in the Supabase API settings.
- CI evidence (`tests/audit/test_supabase_lockdown.py`): creates `anon`/`authenticated` with Supabase-like default grants on the disposable PostgreSQL service, runs all migrations, and asserts both roles get `42501 insufficient_privilege` for SELECT, INSERT and DELETE on every Verina table, that RLS is enabled and not forced, that a new table is not granted to them, and that the owner still appends and verifies the audit chain. A guard test fails if a new table is not listed in the lock-down.
- Connections: always `sslmode=require` (Supabase notes that drivers default to `prefer`). The free direct connection (`db.<ref>.supabase.co:5432`) is IPv6-only; on IPv4 networks use the **session pooler** (`<pooler-host>:5432`, user `postgres.<ref>`) for both migrations and the API. Do not use the transaction pooler (6543): it does not support the session state and prepared statements SQLAlchemy/psycopg use, and migrations need a session.

### 7. Enablement gate

`VERINA_ENV=development` is now accepted, in addition to explicit `local`/`test`, **only** when issuer, audience, an HTTPS `VERINA_AUTH_JWKS_URL`, the audit head HMAC key (`VERINA_AUDIT_HEAD_KEY`) and an explicitly configured `VERINA_DATABASE_URL` are all set. Staging and production are still refused. The settings default `env` never counts.

### 8. Supabase Free plan limits (accepted for development only)

- Projects pause after one week of inactivity and must be resumed in the dashboard; the API then returns 503 until the database is reachable.
- No automated backups and no point-in-time recovery: the development database is disposable. Do not hold anything that cannot be recreated.
- 500 MB database size per project; 50,000 monthly active users; 2 active projects.
- Built-in e-mail: 2 per hour (see section 5).

### Supabase references (checked 14 Oct 2026)

- Auth admin API and invite endpoint: Supabase Auth OpenAPI specification, `POST /invite` (`email`, `data`; 200 returns the user, 422 "User already exists and has confirmed their address") and `GET /admin/users` (`page`, `per_page`): https://github.com/supabase/auth/blob/master/openapi.yaml ; client behaviour (`redirectTo` sent as the `redirect_to` query parameter): https://github.com/supabase/supabase-js/blob/master/packages/core/auth-js/src/GoTrueAdminApi.ts and `src/lib/fetch.ts`; reference page: https://supabase.com/docs/reference/javascript/auth-admin-inviteuserbyemail
- API keys ("send publishable and secret keys on the `apikey` header, not on `Authorization: Bearer`"; secret keys are not JWTs): https://supabase.com/docs/guides/api/api-keys . Verina sends the secret on `apikey` and adds `Authorization: Bearer` only for a legacy JWT `service_role` key.
- Auth rate limits (2 e-mails per hour with the built-in provider): https://supabase.com/docs/guides/auth/rate-limits
- Connections (direct IPv6, session pooler IPv4, transaction pooler limitations, `sslmode=require`): https://supabase.com/docs/guides/database/connecting-to-postgres
- Plan limits (pause after 1 week, no backups or PITR on Free, 500 MB): https://supabase.com/pricing

## Consequences

- The PO can run the API in `development` against the Supabase project, bootstrap a platform admin, create organizations and invite members; the web slice builds against the contract.
- New external endpoints (JWKS fetch, Auth admin API) and a new processor (Supabase, Singapore) holding authentication identities and the directory database. Security and PDPA reviews are required before inviting real people.
- The secret key is a full-privilege credential for the Supabase project. It lives only in the ignored `apps/api/.env` (or a secret manager), is a `SecretStr`, and is never logged or sent to the browser.

## Open

Shared rate limiting; trusted-proxy client addresses; MFA enforcement on by default; outbox for invite side effects; member removal and e-mail change; pagination of member and organization lists (capped at 1000); a least-privileged database role with RLS policies; an independent audit anchor; retention of directory accounts and bindings; custom SMTP; production enablement review (staging/production remain refused).

## Privacy source review (14 October 2026)

The accounts source and metadata boundaries have a conditional privacy review for gated
source integration. This is not permission to invite real people or process client matter
data. [DATA_INVENTORY](../compliance/DATA_INVENTORY.md) records the source-observed account
holdings and the unresolved activation evidence. A project region is not a guarantee that
all support, email, web-host or sub-processor processing remains in Singapore.

Supabase's [published DPA](https://supabase.com/legal/customer-resources/data-processing-addendum)
(Version 1, 1 August 2026, retrieved 14 October 2026) names Supabase Pte. Ltd. Clause 6.1
provides regional primary storage/processing subject to exceptions; it does not establish
exclusive regional processing. Confirm the account's applicable agreement and processing
schedule, sub-processors and support/SMTP locations before real-person activation.
[Default SMTP](https://supabase.com/docs/guides/auth/auth-smtp) is project-team restricted,
best effort and not intended for production. An existing email address is not evidence
that the invitation was delivered. Provider side effects may precede a failed local commit.