# Source publication review

Date: 2026-10-13 · Reviewer: security agent · Evidence mode: repository code and synthetic tests

## Decision and limits

No credential or confidential-file blocker was found in the reviewed source-publication candidate snapshot. Publishing these scoped sources to the authorized private repository is acceptable; this is not authorization to deploy, process client data, or enable external model calls. The reviewed baseline was `3c75be7` plus 263 tracked/nonignored working-tree candidate files. Subsequent edits and the final staged set require the coordinator's final guard and secret scan; this report does not cover future files automatically.

The full npm development-tool advisory remains a release gate issue under R-002. It does not itself prevent sharing synthetic source code. Existing R-001 product-owner risk acceptances remain in force; no new acceptance is inferred. Hosted CI and repository protection require separate observed evidence.

### Public visibility follow-up

The product owner subsequently requested public repository visibility and an explicit AI-agent Scrum experiment note. The coordinating agent rechecked the published refs and final staged files before that visibility change. This records the user's source-publication authorization, not a new security-agent review or production approval. The earlier security review remains bounded to its stated snapshot. Private plans, handoffs, supplied PDFs and extracts remain excluded; subsequent committed changes must pass the same guards and secret scan.

## Publication evidence

- `scripts/guard.py`: pass, 263 candidate paths; configured hook path `.githooks`.
- Gitleaks: no leaks found in a local copy of exactly those candidate files, approximately 3.63 MB. Ignored confidential files and downloaded reference PDFs were excluded. Default detection rules plus the existing two exact prose false positives were used; results were redacted. This is a bounded heuristic scan, not proof that every possible secret is absent.
- `pytest apps/api/tests/ai/test_client.py apps/api/tests/test_guard.py apps/api/tests/test_precommit.py -q`: **80 passed**, including live-transport rejection, diagnostic canaries, ignored-but-tracked confidential paths and actual staged-hook cases.
- Candidate paths and new architecture/landing content inspected. No supplied PDF, source extract, private roadmap, backlog or handoff was present among candidate files. Public process documents describe original working practices and cite reference publishers.
- The case-insensitive confidential-root rule precedes the `.env.example` exception. A confidential-root example file cannot escape the guard; a normal example environment file can.

## Implemented boundary and disclosure

The API mounts only `/health`; internal AI calls have no public HTTP route. `AnthropicClient` rejects default/live transports, injected SDK clients and injected HTTP clients. Only an exact in-process mock transport is allowed; the fresh HTTP client disables environment proxies. The reviewed provider diagnostic logger is filtered, and canary tests check that document text and keys do not enter diagnostic capture. This does not sandbox arbitrary local Python or exhaustively establish every dependency's network behavior.

| Local state | Location | Sensitivity and lifecycle | Evidence |
| --- | --- | --- | --- |
| Demo clauses and identities | Web source fixtures | Invented content; remove/change source to change the demo | `apps/web/lib/sample-ledger.ts` |
| Rendered requests, redaction map, output | Process memory | Synthetic test inputs; lifetime of process/call; no secure-erasure guarantee | AI client/orchestrator/redaction modules |
| Audit metadata | In-memory sink and configured log handlers | Actor/matter identifiers can be sensitive; sink is mutable and lost on restart; host log retention unspecified | AI audit/orchestrator modules |
| Provider credentials | Environment/configuration wrapper | Not encrypted by `SecretStr`; host backup/secret management remains an operational concern | API settings/client modules |

| Destination | Trigger/payload | Credential and retention | Control/evidence state |
| --- | --- | --- | --- |
| Model provider | Intended request serialization; synthetic mock only | Synthetic key in tests; real provider terms not established for client data | Observed application gate blocks live transport |
| Google font service | Next font build downloads; font assets served by the application | No matter payload in reviewed font configuration; remote service retention not reviewed | Observed `next/font/google` configuration; full build/host network capture not performed |
| Developer tooling/registries | Installs, configured hooks, updates | Tool-specific network behavior and R-001 acceptances | Separate development boundary; not a claim of no egress |
| Diagram viewer | Opens local SVG assets | No credentials or external fetch in reviewed viewer | Observed HTML uses local resources |

Plain-language disclosure: this checkpoint displays invented examples and uses fake or in-process mock AI clients. It does not implement production confidentiality, authentication, tenant isolation, complete anonymization, durable audit or client delivery. No confidential matter should be processed based on this source review. Overall confidence: **Medium**; code and mock evidence reviewed, exhaustive runtime/dependency network behavior `not_observed_not_excluded`.

## Architecture and landing review

The architecture README and diagrams mark stores, identity, authority connectors and network model transport as proposed/disabled. They distinguish caller identifiers from authentication, completion metadata from durable audit, and UI export illustration from server enforcement. The landing page states prototype, synthetic examples, read-only operation, no uploads and no live AI checks; its delivery gate is explicitly intended. No live-security or PDPA-compliance assurance was found in those new artifacts.

Historical target data-flow text still says no code exists; treat it as target design, as the architecture README instructs. Refresh that metadata when the next implemented flow lands. This documentation drift is Low severity, owner SEC, due Sprint 1; it is not a publication confidentiality blocker.

## ADR 003 security feedback for planning

The proposed composition/protocol boundary is sound for a synthetic first slice, but the ADR is not accepted merely by this review. Before implementation, record action outcomes in a matrix and have QA assert them at service and repository boundaries:

| Principal/resource condition | Action | Required baseline |
| --- | --- | --- |
| Missing/untrusted identity or mismatched tenant | Any matter operation | Deny before content lookup; derive tenant from trusted adapter |
| Same-tenant actor without matter membership | Read/search/list/export | Deny content and filter lists/counts; do not disclose existence via lookup differences |
| Tenant administrator without explicit matter membership | Matter content or model context | Deny; administration must not imply content access |
| Member subject to an ethical-wall restriction | Any restricted matter action | Explicit restriction overrides role permission |
| Authorized member with pending conflict clearance | Review/model work | Deny independently of membership; waiver requires separately authorized named decision |
| Authorized member with unresolved ledger entries | Client export | Deny on the server regardless of UI state; attestation/review rights need explicit PO decisions |
| Revoked membership or changed wall/conflict status | Queued/background work | Re-evaluate at execution and sensitive transitions; cached prior permission is insufficient |

Cover forged route/body/header identifiers, alternate non-HTTP callers, search/count leakage, wrong-tenant updates/deletes, conflict-waiver privilege and attempted self-escalation. Design audit events for denied actions without copying document content; record trusted actor, action and decision provenance. Identity provider, persistence and production assurance remain separate reviewed decisions. Exact role grants and waiver semantics belong to the product owner; no grant is invented here.
