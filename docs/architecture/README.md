# Architecture map

Owner: engineer agent. Code inspection: 2026-10-13. These views describe the repository skeleton and explicitly marked proposals. They do not certify a deployment or client-data protection.

Open [the offline diagram viewer](index.html) for rendered diagrams. Editable `.mmd` sources and standalone `.svg` exports sit beside this file. Mermaid flowcharts carry C4 semantics through explicit person/system/container/component labels; this avoids dependence on Mermaid's experimental C4 renderer. Solid relationships describe current connections; dashed relationships describe proposed connections. A C4 container is an application or data store, not a Docker requirement.

| View | Audience and question | Editable source | Export |
| --- | --- | --- | --- |
| C1 context | Everyone: who uses Verina, which external systems are intended? | [context](c1-context.mmd) | [SVG](c1-context.svg) |
| C2 containers | Engineering/operations: which applications run separately? | [containers](c2-containers.mmd) | [SVG](c2-containers.svg) |
| C3 API components | Developers/security: where are current API responsibilities? | [API components](c3-api-components.mmd) | [SVG](c3-api-components.svg) |
| C4 code | Developers: which interchangeable interfaces already exist? | [classes](c4-orchestrator-classes.mmd) | [SVG](c4-orchestrator-classes.svg) |
| AI call sequence | Developers/QA: what happens before output is returned, including errors? | [sequence](ai-call-sequence.mmd) | [SVG](ai-call-sequence.svg) |

## What exists

- [FastAPI factory](../../apps/api/src/verina/main.py) mounts `/health`, settings and [response security headers](../../apps/api/src/verina/security.py). No public model, matter, upload, authentication or export route exists.
- The web application renders synthetic ledger data. UI export blocking illustrates the intended workflow; it is not a server-side authorization or delivery control. Landing-page changes do not create backend integration.
- [Orchestrator](../../apps/api/src/verina/ai/orchestrator.py) is an internal, tested module. It resolves a role and a versioned template, redacts variables/document titles/text with a shared mapping, constructs separate untrusted document blocks, calls its injected client, emits completion metadata, and only then returns re-identified output.
- [AnthropicClient](../../apps/api/src/verina/ai/client.py) permits only explicit in-process mock transport. Live transport and injected SDK/HTTP clients are rejected before construction. Fake clients support synthetic tests. This is an application control, not a sandbox against malicious local Python.
- [InMemoryAuditSink](../../apps/api/src/verina/ai/audit.py) stores events in a mutable list. [AIAuditEvent](../../apps/api/src/verina/audit/events.py) carries metadata and hashes; it does not persist documents/prompts/output. Opaque actor/matter identifiers can still be sensitive. There is no durable start event, per-attempt chain or restart persistence.
- `matters`, `documents`, and `ledger` API packages are placeholders. No database, object store, worker, cloud region or identity provider is provisioned by this repository.

## Useful object-oriented principles

The current orchestrator already uses interface-based polymorphism through Python `Protocol`: callers depend on `ModelClient.complete`, `Redactor.redact/reidentify`, and `AuditSink.emit`, rather than their concrete implementations. `FakeModelClient` and mock-only `AnthropicClient` satisfy the same structural contract without a shared inheritance hierarchy. `RegexRedactor` and `NoOpRedactor` likewise implement one protocol. Constructor injection makes behavior replaceable in tests while keeping sequencing in one owner.

Encapsulation keeps the redaction mapping within a call. Frozen request/response value objects make data contracts explicit, although freezing a dataclass alone does not make every nested value deeply immutable. Composition is preferable to subclasses for independent concerns such as tenant memberships, permissions and conflict clearance. Test alternatives against the same behavior contract; do not add inheritance solely to populate a diagram.

Isomorphism describes a structure-preserving correspondence; it is not a standard object-oriented mechanism. If browser/API models must correspond later, use an explicit shared contract and serialization checks. Do not assume identical field names prove equivalent semantics.

## Planned boundaries and unresolved risks

[ADR 001](../adr/001-monorepo-and-stack.md) identifies Postgres as the target and defers durable workflow infrastructure. [ADR 003](../adr/003-tenant-matter-authorization-boundary.md) proposes identity, tenant-scoped repository and matter-authorization interfaces; it is not accepted or implemented. Storage/cloud selection, conflict decisions, ethical walls, document parsing and durable audit remain separate reviewable slices.

Regex redaction currently covers checksum-valid NRIC/FIN, email and explicit `+65` phone patterns; it cannot establish complete anonymization. Policy can choose the no-op redactor in synthetic tests. Live activation requires the independent egress guard, reviewed provider route/terms and durable audit controls described in [ADR 002](../adr/002-ai-orchestrator.md) and [security review R-002](../security/REVIEWS.md).

The [security data-flow document](../security/DATA_FLOW.md) is a design-time target with planned storage, gateways and authority connectors. Its target network topology must not be interpreted as this repository's observed deployment. For the current implemented boundary, use these diagrams and R-002. C1 external actors describe intended product context; they do not establish live identity integration or authority retrieval.

## Keep the diagrams useful

Update the relevant source when an endpoint is mounted, a service boundary changes, a store is provisioned, or a release gate changes. Check code paths and actual calls before changing a dashed edge to solid. A reviewer should trace a diagram label to a module or an explicitly proposed ADR. Keep C3/C4 focused on the risky call boundary; do not expand every utility into its own component.

Render one source with the pinned CLI below; repeat for the other sources. The tool is downloaded into npm's cache and is not an application runtime dependency.

```powershell
npm exec --yes --package=@mermaid-js/mermaid-cli@11.12.0 -- mmdc -i docs/architecture/c1-context.mmd -o docs/architecture/c1-context.svg -b transparent -t neutral
```

Validate all five sources through the renderer, inspect exports for clipping/overlap, and check relative links before committing. The offline viewer makes no network requests and uses local SVGs.
