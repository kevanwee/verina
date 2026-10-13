# ADR 005: Local/test synthetic matter and conflict recording

Status: Accepted for the bounded application foundation; production provisioning remains proposed.

## Context

The access foundation already isolates tenants and matter membership, refreshes identity before work, and gates review on conflict status. A status flag alone cannot establish named recording or distinguish the check that a waiver concerns. Synthetic fixtures must demonstrate attribution without manufacturing historical lawyer decisions.

## Decision

Extend the existing application service with lawyer/partner creation and matter-member lawyer/partner conflict recording. Creation derives tenant, actor and opaque matter ID from trusted application context, starts pending, and grants only creator membership. Requester assignment and submission remain separate work.

The synthetic identity adapter issues bounded, retrievable profile snapshots. Display names are presentation evidence and never grant authority. Recorded checks bind the typed matter ID, result, recorder, trusted profile snapshot, UTC time and positive integer check version. Replacement increments the version and removes the old waiver. Waivers bind the same matter and current recorded hit version, with trusted profile, actor, UTC time, reason and self-recorder visibility. Member-lawyer self-waivers remain permitted.

Readiness requires structurally valid, consistent recorded facts. Raw strings, Boolean versions, missing profiles, non-UTC timestamps, bare status flags, cross-matter evidence and stale waivers fail closed. Historical profile snapshots remain attributable after identity rename or deactivation; current identity and authority still control every new operation.

Canonical metadata-only access audit decisions precede mutation. After awaited audit, the service rechecks current authority. Recording and waiver also compare check/status/waiver snapshots and reject concurrent changes rather than silently rebinding the intended operation. Mutation then runs synchronously without another await in the process-local repository.

## Consequences and limits

No authenticated route, upload, public synthetic token issuer or model transport is enabled. The API remains health-only. Requester status exposes an opaque ID and coarse conflict-stage state; `ready` is not complete ledger coverage or client-delivery approval.

Matter/check/profile state remains process-local. SQL audit can survive restart while matter facts disappear. An allow decision does not certify a completed repository mutation; failed writes can leave an allow event. Durable history, atomic completed outcomes, multiworker concurrency controls, historical identity persistence, declined lifecycle and real authentication remain unfinished. Later durable integration must replace the process-local race guarantee with transactional authorization and revision checks.

Existing test fixtures explicitly construct invented checks and synthetic profiles. The application never backfills a named clearance from a legacy status flag. Document ingestion and original-byte provenance are outside this foundation.

Validation is tracked in `docs/testing/TRACEABILITY.md`; integration acceptance still requires current hosted checks and recorded source review.
