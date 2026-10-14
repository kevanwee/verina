# Accounts API contract v1 (SM-defined, shared by API and web slices)

All routes under the existing /v1 router, same auth (Bearer access token from Supabase), same generic error style as ADR 007 (401 + WWW-Authenticate, uniform 404, 409, 422, 428, 503, no input echo). Mutating POST/PATCH require `Idempotency-Key` (UUID). JSON only, 16 KiB cap.

## Identity
- `GET /v1/me`
  - Valid token, bound and active: `200 {"linked": true, "actor_id", "display_name", "organization": {"id","name","slug"}, "roles": [..], "platform_admin": bool}`
  - Valid token, platform admin with no organization: `200 {"linked": true, "organization": null, "roles": [], "platform_admin": true, ...}`
  - Valid token but no binding, or principal/org deactivated: `200 {"linked": false}` (no other fields). This is the ONLY route that accepts an unbound valid token; every other route keeps 401.
  - Invalid/missing token: 401.

## Platform admin (requires platform_admin grant; non-admins get uniform 404)
- `GET /v1/admin/organizations` -> `{"organizations":[{"id","name","slug","active","member_count"}]}`
- `POST /v1/admin/organizations` `{"name": 1..120, "slug": ^[a-z0-9](-?[a-z0-9]){1,39}$}` -> 201 `{"id","name","slug","active":true}`; duplicate slug 409 `slug_taken`
- `GET /v1/admin/organizations/{org_id}` -> org object
- `PATCH /v1/admin/organizations/{org_id}` `{"name"?, "active"?}` -> org object

## Members (platform admin for any org; tenant_admin for own org only; anyone else uniform 404)
- `GET /v1/organizations/{org_id}/members` -> `{"members":[{"actor_id","display_name","email","roles":[..],"active","invite_status":"pending"|"accepted"}]}`
- `POST /v1/organizations/{org_id}/members` `{"email","display_name": 1..120, "roles": non-empty subset of [partner,lawyer,requester,knowledge,tenant_admin]}` -> 201 member object. Server sends a Supabase invite (magic link) and binds (issuer, supabase user id) to the new actor immediately. Email already bound to any org -> 409 `account_exists`.
- `PATCH /v1/organizations/{org_id}/members/{actor_id}` `{"roles"?, "active"?, "display_name"?}` -> member object. Removing tenant_admin from / deactivating the last active tenant_admin -> 409 `last_admin`. tenant_admin cannot grant platform admin (not a role anyway).
- `POST /v1/organizations/{org_id}/members/{actor_id}/resend-invite` -> 202

## Notes
- Email is stored in the Verina directory only as needed for member management display (PDPA: minimal; document in DATA_INVENTORY). Supabase auth.users holds the auth identity.
- Platform admin grant lives in its own table keyed by (issuer, subject), bootstrapped only by CLI (`python -m verina.access.provision bootstrap-platform-admin --email ...` which invites/looks up the Supabase user) and refuses if one exists.

## Implementation clarifications (API slice, ADR 009)

These refine, and do not change, the shapes above. Decision record: [ADR 009](../adr/009-supabase-identity-accounts-and-postgres.md).

- Routes exist only when `VERINA_MATTERS_API_ENABLED=true` (the `/v1` switch).
- `GET /v1/me` for an org-less platform admin: `actor_id` and `display_name` are `null`. A platform admin whose organization or principal is deactivated is still `linked: true` with `organization: null`.
- Organization object: `POST` returns `{"id","name","slug","active"}` exactly; `GET` and `PATCH` return the full object `{"id","name","slug","active","member_count"}` (as in the list). `member_count` counts all principals of the organization, including deactivated ones. Lists are capped at 1000 items (no pagination yet).
- Member object: `email` is `null` and `invite_status` is `"accepted"` for principals provisioned by the local CLI (they have no invitation). `roles` are sorted. `PATCH` returns the full member object.
- `PATCH` with no fields (or only `null`s) is `422 validation_failed`. Unknown fields are refused (422).
- `POST .../resend-invite` takes no body (an empty `{}` JSON body is accepted and ignored) and returns `202 {}`. Additional errors: `404 not_found` for a member without an invitation (CLI principal), `409 invite_already_accepted`, `409 member_inactive`, `409 organization_inactive`.
- `POST .../members` additional errors: `409 organization_inactive` (deactivated organization), `429 rate_limited` (per-account invite limit or Supabase rate limit; `Retry-After` set), `503 unavailable` (Supabase unreachable or not configured).
- `409 idempotency_key_reused`: the same `Idempotency-Key` with a different actor, action or body in the same scope. Missing or malformed key: `400 bad_request`. A replay returns the current state of the resource with the original status code.
- `401` with body `{"error":"insufficient_user_authentication"}` (and an RFC 9470 `WWW-Authenticate` challenge, `acr_values="aal2"`) when `VERINA_AUTH_ADMIN_REQUIRE_AAL2=true` and a platform admin presents an `aal1` token. Off by default. Clients that do not forward `WWW-Authenticate` should switch on the body `error` code.
- `429 {"error":"rate_limited"}` with `Retry-After` on any `/v1` route after repeated authentication failures from one client address.
- Errors are always `{"error": <code>}`; bodies, e-mail addresses and names are never echoed.
