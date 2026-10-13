# ADR 006: Durable matter projection with optimistic revisions

Status: Accepted for repository integration; production activation remains separate.

## Context

Application matter state previously disappeared on process restart even when authorization audit events survived. The product needs persistent matters and recorded conflict evidence, with tenant isolation and stale-write protection. A durable repository alone does not establish real authentication or a complete legal-evidence lifecycle.

## Decision

Use the existing SQLAlchemy engine and Alembic migration path for SQLite locally and PostgreSQL in hosted tests. Migration 0002 adds a composite tenant/matter key, positive storage revision and separate access/content JSON columns. Existing audit tables and append-only triggers remain independent.

Closed versioned JSON schemas validate bounded values, strict integer revisions, UTC times, identity and target binding, conflict/waiver consistency, duplicate fields and document IDs. Malformed stored rows raise a generic error without raw payloads. Historical profile snapshots are reconstructed internally from validated storage as presentation evidence; this does not create a current authenticated principal, professional identity proof or role grant. Database writes and credentials remain a trust boundary. Structural validation cannot detect a privileged writer replacing a record with a fully consistent forged history; this projection is not tamper-proof evidence of an actual lawyer act.

`get_access` selects access state without document/title content. Collection visibility is evaluated on tenant-scoped access state before content selection, matching or counting. Content retrieval holds a transaction lock, compares the expected access snapshot, and selects content by that same storage revision. The access JSON contains protected profile names and waiver reasons; it is confidential authorization state, not public or anonymous metadata.

Updates compare the caller's expected revision in the SQL WHERE clause and atomically increment it. Deletes require an expected revision. There is no retry against the latest revision, which could silently overwrite intervening decisions. The in-memory adapter follows the same revision contract. The application service supplies the authorized access snapshot when retrieving content and the authorized revision when deleting.

SQL bound parameters are hidden by default and repository database errors are generic. This reduces error/log disclosure; it does not configure a complete operational logging policy or protect against explicitly unsafe engine overrides.

## Consequences and unfinished work

Restart now preserves typed matter content, membership/walls, current conflict checks, waivers and historical profiles. Tests use invented fixtures on both supported database dialects. This is reusable product persistence code; it does not activate real-data processing, public HTTP/authentication, blob ingestion or provider calls.

Storage revision CAS protects against lost updates and stale authorized content reads. It does not atomically bind external identity changes, legal ledger output revisions or separate audit decisions to completed mutations. A shared transaction/outbox, durable completed outcomes/history, identity lifecycle, authenticated API, operational database roles/RLS, encryption/key management, retention/backup and hold-aware deletion remain required work. Physical repository deletion is not a production retention or legal-hold workflow. No compliance, human legal sign-off or production-readiness claim follows from migration success.

Acceptance evidence is mapped in `docs/testing/TRACEABILITY.md`; current hosted PostgreSQL checks and source review remain required before merge.
