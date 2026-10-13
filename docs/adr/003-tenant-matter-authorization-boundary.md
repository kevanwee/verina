# ADR 003: Tenant and matter authorization at the application boundary

- Status: Proposed; security and product-owner review required before implementation
- Date: 2026-10-13
- Author: Engineer agent
- Scope: Local synthetic access-domain design; no identity provider or cloud selected

## Context

The API currently exposes only `/health`. The AI orchestrator accepts an `actor` and `matter_id` from its internal caller, validates that they are non-empty, and uses them as audit identifiers. This is not authentication or authorization. Future matter endpoints need one explicit boundary before document reads, model context construction, or export.

## Proposed decision

Use composition and immutable domain values rather than a hierarchy of user subclasses. A trusted identity adapter produces a principal containing tenant and actor identifiers. A matter access policy evaluates that principal, the requested action, and a tenant-scoped matter record. Reject missing identity, wrong tenant, missing membership, and ethical-wall restrictions before reading content. Tenant administration alone must not confer matter-content access. Exact role/action permissions require review.

Endpoint handlers delegate to application services. Services authorize before reading content or calling the orchestrator. Repositories require an explicit tenant key for every lookup, including lists, search, updates and deletes. Client JSON, route IDs, headers and frontend state cannot establish tenant membership. Never return a record merely because its identifier exists.

Introduce narrow `IdentityAdapter`, `MatterRepository`, and `MatterAccessPolicy` protocols only when an application service needs them. Use in-memory adapters for synthetic tests first. Keep the existing `ModelClient`, `Redactor`, and `AuditSink` protocols; provider implementations must retain the live-transport gate. Durable audit needs a separate approved persistence decision.

An independent conflict gate must also clear before review work begins. Authorization establishes who may act; a conflict decision establishes whether the matter may proceed. Neither replaces the Verification Ledger or a server-side export gate.

## Alternatives

- Trust browser-supplied actor/tenant values: rejected because identifiers are not proof of authority.
- Scatter permission checks across route handlers: rejected because non-HTTP callers and future workers could bypass them.
- Create subclasses for each legal role: rejected because roles, memberships and restrictions can overlap and change independently.
- Select a full policy engine or identity vendor immediately: deferred until the permission matrix and operational constraints justify one.

## Consequences and review evidence

This adds a small application boundary while keeping domain code independent of HTTP, provider SDKs and database vendors. It does not establish production tenant isolation, authentication or compliance by itself.

Before adoption, security should review a roles/resources/actions matrix and forbidden transitions. Tests must exercise cross-tenant identifiers, same-tenant non-members, explicit denials, forged identity inputs, list/search leakage and alternate service callers. QA should agree expected results before implementation. PDPA counsel reviews any new identity/personal-data flow. The product owner confirms permission and conflict-waiver semantics; agents cannot grant that approval.

Related: [current architecture](../architecture/README.md), [stack](001-monorepo-and-stack.md), [AI boundary](002-ai-orchestrator.md), [security controls](../security/CONTROLS.md).
