# ADR 007: Verified-token identity, Verina-owned directory and the /v1 matter route contract

Status: Proposed for security and QA review. Disabled by default; no identity provider is selected and no production activation follows from this decision.

## Context

The matter service (ADR 003, 005, 006) and atomic outcomes (migration 0003) were reachable only from application code with a synthetic in-memory identity adapter. A usable product needs real authentication and an HTTP contract, but the identity provider is not chosen and no provider account may be provisioned at this stage. The authentication layer must therefore be provider-neutral, zero cost, and unable to let token contents grant authority.

## Decision

### Token verification (`verina.access.tokens`)

- PyJWT with the `crypto` extra (pinned, pip-audit clean) verifies signatures. The allowlist is asymmetric only: `RS256`, `ES256`, `EdDSA`. `none`, every `HS*` algorithm and any other algorithm are refused before signature verification, which closes algorithm-confusion attacks where a public key is used as an HMAC secret.
- Keys come only from configuration: a static public JWKS supplied as inline JSON or a local file (`VERINA_AUTH_JWKS`). Every key must declare a unique `kid` and an allowed `alg` matching its key type and curve; private members, symmetric keys, non-signing keys and RSA keys below 2048 bits are rejected at startup. The token header must name a known `kid`, and its `alg` must equal that key's declared `alg`. Header-supplied key material or key URLs (`jwk`, `jku`, `x5u`, `x5c`) and `crit` extensions are refused.
- Claims: exact `iss`; `aud` equal to the configured audience (or an array containing it, RFC 7519 4.1.3); `exp`, `iat` and `sub` required; `nbf` honoured when present; numeric dates must be finite numbers; clock leeway bounded to 0-120 s (default 30); `exp - iat` bounded (default 3600 s, configurable 60-86400). Tokens over 8 KiB, non-ASCII or not in compact three-segment form are refused. Every failure raises one detail-free error.
- A fetching JWKS client is deliberately not added. Key rotation is a configuration change and restart. A fetcher is follow-up work and must have an HTTPS-only URL, connect/read timeouts, a response size limit, a cache with bounded refresh, and no fetch per request or per unknown `kid`.

### Verina-owned directory (`verina.access.sql_identity`, migration 0004)

- The token contributes only the verified `(issuer, subject)` pair. `identity_bindings (issuer, subject) -> (tenant_id, actor_id)` maps it to a principal, and `identity_principals (tenant_id, actor_id)` holds roles, active state, the trusted display profile and a revision. Token role, tenant, group, scope or e-mail claims and request headers are never read.
- `authenticate` refuses unknown bindings and inactive principals. Malformed directory rows fail closed. `current` re-reads the principal row on every call. `profile` returns the retained profile after deactivation (historical attribution only).
- Inside a durable mutation the repository binds its transaction connection (`verina.db.bind_connection`), and the directory re-check runs on that same transaction. On PostgreSQL the principal row is read `FOR SHARE`, so a concurrent deactivation waits until the mutation commits. On SQLite, `BEGIN IMMEDIATE` already serialises writers. Without this binding a second SQLite write transaction would wait on the first.
- Provisioning is a local/test-only function and CLI (`python -m verina.access.provision`). There is no self-signup and no HTTP administration route. Directory changes are not yet written to the audit chain.

### Revocation semantics (exactly what is and is not covered)

Covered: a deactivation or role change committed to the shared database is seen by the next service authorization check in any process using that database. This applies between requests, between the pre-audit and post-audit checks within a request, and inside the mutation transaction itself, where a deactivated principal's change rolls back with no matter change, completed event or receipt. Unbinding a subject stops new authentications.

Not covered: identity-provider session or token revocation (a token for an active binding stays usable until `exp`); data already returned to a caller; a read whose response is being serialised when deactivation commits; unbinding does not end a request that has already authenticated, because `current` is keyed by tenant and actor (deactivation is the revocation control); directory changes made outside this database; and no MFA or assurance-level claim is checked.

### Route contract (`verina.api.matters`)

- Routes are registered only when `VERINA_MATTERS_API_ENABLED=true`. Enabling without an issuer, audience and valid JWKS (and outside local/test, an `https://` issuer) fails application startup. Health-only remains the default, and the public preview and web app are unchanged. No CORS is added; existing security headers apply.
- `POST /v1/matters` `{title}`, `GET /v1/matters/{id}`, `PATCH /v1/matters/{id}` `{title}`, `POST /v1/matters/{id}/conflict-checks` `{result: CLEAR|CONFLICT}`, `POST /v1/matters/{id}/conflict-waivers` `{reason}`. Each request builds a `MatterService` in durable mode (shared engine for SQL repository, audit store, mutation unit of work and directory) with the audit sink bound to the authenticated tenant. Review/model work, uploads, delete and membership changes are not exposed.
- `GET` returns `{matter_id, revision, title, conflict_status, status}` with an `ETag` to content-reader roles (`read_matter`), and otherwise the requester projection `{matter_id, status}` (`read_status`) without a revision.
- Every mutation requires `Idempotency-Key` (canonical UUID), which becomes the service `operation_id`. Non-create mutations require `If-Match` with the integer revision (quoted or bare), which becomes `expected_revision`. Responses carry the committed `revision` (read from the verified receipt metadata for that operation) and `ETag`, and only the fields listed in the route docstring. Waiver reasons, profile names and request bodies are never echoed.
- Header choice: a missing or malformed `Idempotency-Key` returns **400** (following the IETF idempotency-key draft); a missing `If-Match` returns **428 Precondition Required** (RFC 6585); a malformed, weak, list or `*` `If-Match` returns 400; a stale revision returns 409 `revision_mismatch`.
- Errors are generic JSON `{"error": <code>}`. 401 carries `WWW-Authenticate: Bearer realm="verina"` (plus `error="invalid_token"` when a credential was presented). Every matter-route denial, including member role/profile denial, returns the same 404 body as a missing, other-tenant, walled or non-member matter. 403 is used only for the collection-level create denial. 409 covers stale revision, changed conflict state, non-waivable state and idempotency-key reuse with a different request. 413/415/422 cover a body over 16 KiB, non-JSON content and validation failures. Storage, directory or audit failures return 503 and fail closed. Reason codes are mapped centrally, and a completeness test covers every code.
- Request models forbid extra fields, use strict types and bound lengths. The body is read with a streaming 16 KiB limit and parsed by Pydantic, not by framework defaults that echo input. The route layer logs no tokens, titles, reasons or bodies.

## Consequences and unfinished work

The service graph can now be exercised over HTTP with real asymmetric signatures, including on PostgreSQL in hosted CI. Tests generate signing keys at test time; no private key is committed.

Open: IdP selection and onboarding (with whoever operates it), a reviewed JWKS fetcher, audit events for authentication failures and directory changes, rate limiting and abuse controls, production provisioning and tenant-admin workflows, MFA/assurance requirements, request/trace IDs, moving blocking database calls off the event loop (they currently run on it), CORS for the web client, and a decision on whether member role denials should be 403. No production-readiness, compliance or assurance claim follows from this ADR.
