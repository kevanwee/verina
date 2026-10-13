# ADR 007: Verified-token identity, Verina-owned directory and the /v1 matter route contract

Status: Accepted after PR #10 security and QA review (merge after fixes), for local/test enablement only. Disabled by default; no identity provider is selected and no production activation follows from this decision.

## Context

The matter service (ADR 003, 005, 006) and atomic outcomes (migration 0003) were reachable only from application code with a synthetic in-memory identity adapter. A usable product needs real authentication and an HTTP contract, but the identity provider is not chosen and no provider account may be provisioned at this stage. The authentication layer must therefore be provider-neutral, zero cost, and unable to let token contents grant authority.

## Decision

### Token verification (`verina.access.tokens`)

- PyJWT with the `crypto` extra (pinned, pip-audit clean) verifies signatures. The allowlist is asymmetric only: `RS256`, `ES256`, `EdDSA`. `none`, every `HS*` algorithm and any other algorithm are refused before signature verification, which closes algorithm-confusion attacks where a public key is used as an HMAC secret.
- Keys come only from configuration: a static public JWKS supplied as inline JSON or a local file (`VERINA_AUTH_JWKS`). Every key must declare a unique `kid` and an allowed `alg` matching its key type and curve; private members, symmetric keys, non-signing keys and RSA keys below 2048 bits are rejected at startup. The token header must name a known `kid`, and its `alg` must equal that key's declared `alg`. Header-supplied key material or key URLs (`jwk`, `jku`, `x5u`, `x5c`) and `crit` extensions are refused.
- Claims: exact `iss`; strict `aud`: the configured audience as a string or a single-element array. A multi-audience array is refused unless every other value is in `VERINA_AUTH_EXTRA_AUDIENCES` (empty by default). PyJWT checks that the audience is present. Verina enforces the strict rule itself because PyJWT's `strict_aud` would also refuse single-element arrays, which RFC 7519 permits. The audience must be an API identifier, never an OAuth `client_id`, so ID tokens issued to a client cannot be replayed as API tokens; `exp`, `iat` and `sub` required; `nbf` honoured when present; numeric dates must be finite numbers; clock leeway bounded to 0-120 s (default 30); `exp - iat` bounded (default 3600 s, configurable 60-86400). Tokens over 8 KiB, non-ASCII or not in compact three-segment form are refused. Every failure raises one detail-free error.
- A fetching JWKS client is deliberately not added. Key rotation is a configuration change and restart. A fetcher is follow-up work and must have an HTTPS-only URL, connect/read timeouts, a response size limit, a cache with bounded refresh, and no fetch per request or per unknown `kid`.

### Verina-owned directory (`verina.access.sql_identity`, migration 0004)

- The token contributes only the verified `(issuer, subject)` pair. `identity_bindings (issuer, subject) -> (tenant_id, actor_id)` maps it to a principal, and `identity_principals (tenant_id, actor_id)` holds roles, active state, the trusted display profile and a revision. Token role, tenant, group, scope or e-mail claims and request headers are never read.
- `authenticate` refuses unknown bindings and inactive principals. Malformed directory rows fail closed. `current` re-reads the principal row on every call. `profile` returns the retained profile after deactivation (historical attribution only).
- Inside a durable mutation the repository binds its transaction connection (`verina.db.bind_connection`), and the directory re-check runs on that same transaction. The unit of work runs the service authorizer under `require_bound_connection`, so if no bound connection is active the identity read fails closed (`IdentityUnavailableError`, HTTP 503) instead of opening a separate transaction. On PostgreSQL the principal row is read `FOR SHARE`, so a concurrent deactivation waits until the mutation commits. On SQLite, `BEGIN IMMEDIATE` already serialises writers. Without this binding a second SQLite write transaction would wait on the first.
- Provisioning is a local/test-only function and CLI (`python -m verina.access.provision`). It requires `VERINA_ENV` to be explicitly set to `local` or `test`; the settings default does not count. There is no self-signup and no HTTP administration route. Directory changes are not yet written to the audit chain.

### Revocation semantics (exactly what is and is not covered)

Covered: a deactivation or role change committed to the shared database is seen by the next service authorization check in any process using that database. This applies between requests, between the pre-audit and post-audit checks within a request, and inside the mutation transaction itself, where a deactivated principal's change rolls back with no matter change, completed event or receipt. Unbinding a subject stops new authentications.

Not covered: identity-provider session or token revocation (a token for an active binding stays usable until `exp`); data already returned to a caller; a read whose response is being serialised when deactivation commits; unbinding does not end a request that has already authenticated, because `current` is keyed by tenant and actor (deactivation is the revocation control); directory changes made outside this database; and no MFA or assurance-level claim is checked.

### Route contract (`verina.api.matters`)

- Routes are registered only when `VERINA_MATTERS_API_ENABLED=true`. Startup fails (`MattersApiConfigError`) unless `VERINA_ENV` is explicitly set (present in the settings' `model_fields_set`, from the environment or init) to `local` or `test`, and an issuer, audience and valid JWKS are configured. The default `env="local"` is not sufficient, and staging/production are refused in this slice. Health-only remains the default, and the public preview and web app are unchanged. No CORS is added; existing security headers apply.
- `POST /v1/matters` `{title}`, `GET /v1/matters/{id}`, `PATCH /v1/matters/{id}` `{title}`, `POST /v1/matters/{id}/conflict-checks` `{result: CLEAR|CONFLICT}`, `POST /v1/matters/{id}/conflict-waivers` `{reason}`. Each request builds a `MatterService` in durable mode (shared engine for SQL repository, audit store, mutation unit of work and directory) with the audit sink bound to the authenticated tenant. Review/model work, uploads, delete and membership changes are not exposed.
- `GET` returns `{matter_id, revision, title, conflict_status, status}` with an `ETag` to content-reader roles (`read_matter`), and otherwise the requester projection `{matter_id, status}` (`read_status`) without a revision.
- Every mutation requires `Idempotency-Key` (canonical UUID), which becomes the service `operation_id`. Non-create mutations require `If-Match` with the integer revision (quoted or bare), which becomes `expected_revision`. Responses carry the committed `revision` (read from the verified receipt metadata for that operation) and `ETag`, and only the fields listed in the route docstring. Waiver reasons, profile names and request bodies are never echoed.
- Header choice: a missing or malformed `Idempotency-Key` returns **400** (following the IETF idempotency-key draft); a missing `If-Match` returns **428 Precondition Required** (RFC 6585); a malformed, weak, list or `*` `If-Match` returns 400; a stale revision returns 409 `revision_mismatch`.
- Deviation: draft-ietf-httpapi-idempotency-key-header section 2.7 suggests 422 when a key is reused with a different payload. Verina returns 409 `idempotency_key_reused`. Here 422 is reserved for body validation of the current request, while key reuse is a state conflict with an earlier committed operation. A distinct, stable 409 code lets clients tell "fix your input" apart from "this key is spent; generate a new one". Revisit if a client library depends on the draft code.
- Errors are generic JSON `{"error": <code>}`. 401 carries `WWW-Authenticate: Bearer realm="verina"` (plus `error="invalid_token"` when a credential was presented). Every matter-route denial, including member role/profile denial, returns the same 404 body as a missing, other-tenant, walled or non-member matter. 403 is used only for the collection-level create denial. 409 covers stale revision, changed conflict state, non-waivable state and the caller's own idempotency key reused for a different request. On matter routes, a key whose stored receipt belongs to another actor returns the uniform 404 instead, so the route never confirms that the key or its matter exists. Create keeps 409, because no matter is addressed. 413/415/422 cover a body over 16 KiB, non-JSON content and validation failures. Storage, directory or audit failures return 503 and fail closed. Reason codes are mapped centrally, and a completeness test covers every code.
- Request models forbid extra fields, use strict types and bound lengths. Titles and waiver reasons are NFC-normalised. Unicode categories Cc, Cf, Zl and Zp (for example U+202E bidi override, U+200B zero-width space, U+2028/2029 separators) are refused with a generic 422; only newline and tab (`\n`, `\t`) are allowed, and only in reasons. The body is read with a streaming 16 KiB limit and parsed by Pydantic, not by framework defaults that echo input. The route layer logs no tokens, titles, reasons or bodies.

### Security review decisions (PR #10)

- Uniform 404 is kept for every matter-route denial, including a member's role or profile denial. 403 is only for collection-level create.
- Strict audience (above) with an empty-by-default extra-audience allowlist.
- `typ` stays optional (`JWT`, `at+jwt`, `application/at+jwt` accepted when present). A future flag to require `at+jwt` (RFC 9068) should be enabled once the chosen IdP issues it.
- Recommended production token lifetime is 900 s or less. The 3600 s default is for local/test only and must be lowered in any non-local enablement review.
- `jwk`, `jku`, `x5u`, `x5c` and `crit` headers remain refused.

### Enablement gate (must be closed before any non-local enablement)

- **M2:** blocking database calls run on the event loop inside async routes; offload them to a worker thread or an async driver.
- **M4:** audit events for authentication failures and identity-directory changes.
- **L5:** rate limiting and abuse controls on `/v1/*`.
- **L4:** configuration review confirming `auth_audience` is an API identifier, never a client_id.
- Plus: the env gate must be revisited explicitly (staging/production are refused by code today), a production lifetime of 900 s or less, and a reviewed JWKS fetcher or rotation runbook.

## Consequences and unfinished work

The service graph can now be exercised over HTTP with real asymmetric signatures, including on PostgreSQL in hosted CI. Tests generate signing keys at test time; no private key is committed.

Open: IdP selection and onboarding (with whoever operates it), a reviewed JWKS fetcher, audit events for authentication failures and directory changes, rate limiting and abuse controls, production provisioning and tenant-admin workflows, MFA/assurance requirements, request/trace IDs, moving blocking database calls off the event loop (they currently run on it), CORS for the web client, an explicit connection-passing refactor to replace the context-bound connection, a hash-pinned lockfile, and a two-session PostgreSQL race test. No production-readiness, compliance or assurance claim follows from this ADR.
