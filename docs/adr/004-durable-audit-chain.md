# ADR 004: Durable tenant-scoped audit chain

- Status: Implemented locally; integrated review and hosted database evidence pending
- Author: Engineer agents (Claude implementation, Codex reconciliation)
- Date: 2026-10-13

## Decision

Persist registered metadata payloads in SQLAlchemy tables managed by Alembic. Use
SQLite for local synthetic development and PostgreSQL in CI. Each tenant has a
sequence and hash chain; append the event and advance its head in one transaction.
SQLite takes an immediate transaction lock; PostgreSQL locks the tenant head.
Database triggers reject event updates and deletes (and PostgreSQL truncation).

Payloads and persisted envelopes are separate: `AuditPayload` includes model-call
start/completion and access-decision payloads; `AuditEvent` is the durable envelope.
The tenant-bound sink is constructed by trusted application code. An access
payload that claims a different tenant is rejected. Audit payloads contain opaque
identifiers, hashes and approved counts, with structural validation and length
caps; these controls do not detect all personal data in arbitrary short strings.

The orchestrator persists a call-start before invoking its model-client port, then
a linked completion for success, error or cancellation. Process failure can leave
a dangling call. These are logical client-call records; provider SDK retries are
not individually visible and need a later transport-attempt design.

## Integrity and limits

`SqlAuditStore.verify_chain(tenant_id)` is the internal integrity API. It verifies
one consistent database snapshot, hashes, links, sequence and checkpoint. It is
not exposed through unauthenticated HTTP. A future administrative endpoint must
authenticate, authorize and derive the tenant from a trusted principal; the
existing health-only application does not implement that endpoint.

The optional externally held head HMAC key detects forged checkpoint changes,
including an unauthenticated tail rewind. It cannot detect restoration of an
older valid database snapshot and its old valid HMAC. Reliable rollback detection
requires independently retained, monotonic checkpoints or an external immutable
anchor. This slice does not implement that anchor, key custody, backup retention,
database privilege separation or production database deployment.
Deleting an entire tenant chain and its checkpoint is likewise indistinguishable
from a tenant that never emitted an event, without an independent existence record.

Append checks the current head against the tip and its MAC, rather than rescanning
the entire history on every write. Interior corruption is found by full integrity
verification. Application append-only methods and database triggers are defense
in depth; a database owner can remove triggers. No compliance certification or
production tamper-proof guarantee follows from this implementation.

## Validation

Tests cover restart durability, concurrent append, edit/delete/reorder/splice,
tail truncation, keyed checkpoint forgery, replay of an old valid checkpoint,
tenant binding, migration round trips and call-start/error/cancellation behavior.
The API CI matrix supplies a disposable PostgreSQL service so the same store and
migration tests run against SQLite and PostgreSQL. Local SQLite results and hosted
PostgreSQL results must be recorded separately before merge.
