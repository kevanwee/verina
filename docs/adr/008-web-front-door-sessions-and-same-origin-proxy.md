# ADR 008: Web front door: connected-mode gate, server-side Supabase sessions and a same-origin API proxy

Status: Proposed (engineer). Needs security review (new external dependency on Supabase Auth, new same-origin proxy endpoint) and PDPA review (member email display in the admin console) before any non-local enablement. Local/test enablement only, in line with ADR 007.

## Context

ADR 007 gave the API verified-token identity and a `/v1` contract, with no CORS and no identity provider chosen. The PO has since chosen Supabase Auth (email one-time link or code, no passwords) and an accounts contract (`GET /v1/me`, platform-admin organization routes, member management) is being added to the API. The web app must sign people in, call the API with their token, and offer account and administration screens, without changing the public synthetic preview (`/`, `/workbench`, `/workbench/intake`) deployed at verina-tau.vercel.app.

## Decision

### Connected mode is a deployment setting, read at request time

- `lib/connected/config.ts` returns a configuration only when `VERINA_CONNECTED=1` and `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` and `VERINA_API_BASE_URL` are all present and valid (https, or http for loopback only; no credentials, query or fragment in URLs). Anything missing or malformed turns connected mode off (fail closed); a warning names the variables, never their values.
- Variables are read through an object passed in, not `process.env.NAME` member expressions, so a build without them cannot inline `undefined` and a runtime with them still works. `npm run build:web` succeeds with no connected variables.
- `proxy.ts` (Next 16's renamed middleware) runs only on connected routes plus `/workbench/intake`. With connected mode off every connected route is a 404 (`/api/v1/*` answers JSON 404), and `/workbench/intake` passes straight through to the unchanged preview page: no session is read and nothing is fetched. A regression test renders the preview pages with connected variables set and asserts no `fetch`, and a source scan asserts no preview file imports connected or Supabase code.
- With connected mode on, the proxy rewrites `/workbench/intake[/id]` to an internal route (`/intake-connected`); direct requests to the internal path are always 404. Every connected page and handler also checks the configuration itself after `connection()`, so nothing connected is prerendered at build time (regression test).

### Sessions: server-side only, httpOnly cookies, provider behind one contract

- `@supabase/ssr` 0.12.7 and `@supabase/supabase-js` 2.117.2 are pinned exactly. `lib/connected/auth/supabase.ts` is the only file that imports them; `lib/connected/auth/provider.ts` defines the provider-neutral contract and is the single swap point.
- There is no browser Supabase client. Auth cookies are forced to `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` everywhere except `next dev`. The browser never holds a token; `getAccessToken` exists only on the server. The browser auth surface (`getSession`, `signIn({returnTo})`, `reauthenticate`, `onIdentityChange`) learns only "signed in or not" and an opaque SHA-256-derived subject tag from `/auth/session`.
- Sign-in sends an email link and code with `shouldCreateUser: false` (accounts exist only when an administrator adds a member) and reports "sent" for unknown addresses (no enumeration). `reauthenticate` opens sign-in in a separate window and resolves over a `BroadcastChannel`, so page memory and frozen idempotency keys survive; if the window is blocked it falls back to a full-page sign-in.
- `/auth/callback` accepts a PKCE `code` or a `token_hash` with type `email`, `magiclink` or `invite` only. Its destination comes only from a short-lived httpOnly `returnTo` cookie set by the sign-in action and validated against an exact same-origin path allowlist; query parameters can never choose where the browser goes (open-redirect tests). The response carries `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.
- `/sign-out` is POST-only and same-origin-only, revokes the session at the provider (`scope: local`) and clears every auth cookie even if the provider is unreachable.

### Same-origin API proxy instead of CORS

- `/api/v1/[...path]` forwards only the ADR 007 matter routes and the accounts-contract routes, with their exact methods; id segments must match the API's identifier pattern. Everything else is a uniform 404 and never reaches the API.
- The bearer token is attached server-side from the session. Only `Content-Type` (JSON), `Idempotency-Key` and `If-Match` are forwarded; cookies, any browser `Authorization` and forwarding headers are dropped. Responses keep `Content-Type`, `ETag` and `Retry-After` only, always with `Cache-Control: private, no-store`, never CORS headers.
- 16 KiB request cap (declared length and streamed), 256 KiB response cap, 15 s upstream timeout (504), network failure 502, upstream redirects refused (a redirect could carry the token elsewhere), cross-site requests 403 (`Sec-Fetch-Site`, falling back to `Origin` for mutations), no session 401 without an upstream call. Nothing in the proxy logs bodies, tokens or header values.
- Clients treat 502 and 504 as "unconfirmed" and retry with the same `Idempotency-Key`; at most two silent retries happen, for fast network failures only.

### Interface rules that follow from the contract

- Navigation entries come from `GET /v1/me`, which is parsed defensively (unknown roles dropped, malformed bodies treated as unavailable). The API still enforces every route; the web only hides what it cannot use.
- Every mutation freezes one `Idempotency-Key` per user action; retry re-sends identical bytes. Changes are shown only after the server confirms them (lists are re-read).

## Consequences

- The public preview's behaviour and build output are unchanged; the proxy runs on `/workbench/intake` but is a pass-through when connected mode is off.
- Supabase project settings become part of the security boundary: redirect allowlist, email templates (`token_hash` links for invites), OTP length and expiry, JWT lifetime (900 s or less recommended per ADR 007) and asymmetric signing keys so the API's static JWKS can verify tokens.
- Open: no CSP nonce yet (ADR 007 EN-7 still applies); rate limiting on `/api/v1` and on sign-in beyond Supabase's own; audit events for sign-in and directory changes (ADR 007 M4); session expiry warning ahead of time (WCAG 2.2.1) is not implemented because the provider does not expose expiry to the browser in this design.
