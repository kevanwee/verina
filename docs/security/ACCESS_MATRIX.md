# Access matrix (executable)

Owner: verina-engineer; source reviews: security and QA agents; current hosted CI required | Policy version `2026-10-13.3` | Backlog: EN-7, US-3, US-23 | Decision record: [ADR 003](../adr/003-tenant-matter-authorization-boundary.md)

This table is the specification of `verina.access.policy.MatterAccessPolicy`. The test `apps/api/tests/access/test_access_matrix.py` parses every row between the markers below and asserts the policy's decision and reason code. Changing a row without changing the code (or the reverse) fails CI. Every action and every role must appear in at least one row.

Scope: reusable application boundary with in-memory and durable SQL repository adapters, tested with synthetic fixtures. Real identity provider and HTTP authentication remain unfinished. Tenant, actor and roles come only from the trusted identity adapter.

## How to read a row

- **Roles**: roles held by the principal, joined with `+`. `none` means an authenticated principal with no role. Roles compose: a knowledge lawyer who should attest holds `knowledge+lawyer`.
- **Matter**: the first token is the principal's relation to the matter:
  `member`, `non-member` (same tenant), `walled-member` (member and behind an ethical wall), `walled` (behind a wall, not a member), `other-tenant` (matter exists in another tenant), `missing` (no such matter), `none` (tenant-level action, no matter).
  Optional tokens: `conflict=pending|clear|conflict|waived` (default `clear`), `ledger=clean|unverified|unsupported|contradicted|unavailable` (default `clean`), `reason=yes|no` (default `yes`; applies to waiver and attestation), `target=other|self` (default `other`; applies to membership changes).
- **Outcome**: `allow` or `deny`. For `list_matters` and `search` with a matter, `allow` means the matter appears in results and counts; `deny` means it is filtered out inside the query.
- **Reason**: the disclosable reason code. `matter_not_accessible` is deliberately identical for missing, other-tenant, walled and non-member cases. The internal cause is recorded only in the audit event's `detail_code`.
- **Basis**: `Member-lawyer waiver` / `Member-lawyer attestation` identify the configured policy grants. `SEC` is the ADR 003 security baseline in [PUBLICATION_REVIEW.md](PUBLICATION_REVIEW.md). `Charter` is the AGENTS.md rule that nothing reaches a client until each ledger entry is verified or attested. `Proposed` marks an engineering proposal that still needs product-owner confirmation; it is enforced as written until changed.

## Evaluation order

1. The action has a role grant (deny by default).
2. Tenant-level actions and unscoped list/search check the role only.
3. Matter visibility: exists in the caller's tenant, caller not walled, caller is a member. Ethical walls override membership and every role.
4. A role held by the caller grants the action. Tenant administration grants no matter content.
5. Membership changes cannot target the caller (self-escalation).
6. The conflict gate blocks review, model context, attestation and export until a valid named UTC check record is `clear`, or its current version has a valid named reasoned waiver, independently of membership. Bare status flags do not establish readiness.
7. Waivers and attestations require a non-blank reason (at most 2000 characters).
8. Export requires every ledger entry to be verified or attested. A ledger-status failure denies.

The service re-resolves the principal and re-reads the access record on every call and when a queued review executes, so revoked membership, new walls, changed roles, deactivation and conflict changes take effect immediately.

## Matrix

<!-- matrix:start -->
| ID | Roles | Matter | Action | Outcome | Reason | Basis |
| --- | --- | --- | --- | --- | --- | --- |
| M01 | lawyer | other-tenant | read_matter | deny | matter_not_accessible | SEC, DS-1 |
| M02 | partner | other-tenant conflict=conflict | waive_conflict | deny | matter_not_accessible | SEC, Member-lawyer waiver |
| M03 | partner | other-tenant | export_to_client | deny | matter_not_accessible | SEC, DS-1 |
| M04 | lawyer | missing | read_matter | deny | matter_not_accessible | SEC, API-2 |
| M05 | lawyer | non-member | read_matter | deny | matter_not_accessible | SEC, API-2 |
| M06 | lawyer | non-member | list_matters | deny | matter_not_accessible | SEC, API-8 |
| M07 | lawyer | non-member | search | deny | matter_not_accessible | SEC, API-8 |
| M08 | partner | non-member | export_to_client | deny | matter_not_accessible | SEC |
| M09 | lawyer | non-member conflict=conflict | waive_conflict | deny | matter_not_accessible | Member-lawyer waiver |
| M10 | lawyer | non-member | attest_entry | deny | matter_not_accessible | Member-lawyer attestation |
| M11 | partner | non-member | build_model_context | deny | matter_not_accessible | SEC |
| M12 | requester | non-member | read_matter | deny | matter_not_accessible | SEC |
| M13 | knowledge | non-member | read_matter | deny | matter_not_accessible | SEC |
| M14 | knowledge | non-member | attest_entry | deny | matter_not_accessible | Member-lawyer attestation |
| M15 | tenant_admin | non-member | read_matter | deny | matter_not_accessible | SEC |
| M16 | tenant_admin | non-member | build_model_context | deny | matter_not_accessible | SEC |
| M17 | tenant_admin | non-member | search | deny | matter_not_accessible | SEC, API-8 |
| M18 | tenant_admin | member | read_matter | deny | role_not_permitted | SEC |
| M19 | tenant_admin | member conflict=conflict | waive_conflict | deny | role_not_permitted | Member-lawyer waiver |
| M20 | tenant_admin | member | attest_entry | deny | role_not_permitted | Member-lawyer attestation |
| M21 | tenant_admin | none | manage_tenant | allow | allowed | SEC |
| M22 | tenant_admin | none | list_matters | deny | role_not_permitted | SEC |
| M23 | lawyer | none | manage_tenant | deny | role_not_permitted | SEC |
| M24 | partner | none | manage_tenant | deny | role_not_permitted | SEC |
| M25 | lawyer | none | list_matters | allow | allowed | SEC |
| M26 | none | none | list_matters | deny | role_not_permitted | SEC |
| M27 | none | member | read_matter | deny | role_not_permitted | SEC |
| M28 | lawyer | member | read_matter | allow | allowed | SEC |
| M29 | lawyer | member | list_matters | allow | allowed | SEC |
| M30 | lawyer | member | search | allow | allowed | SEC |
| M31 | lawyer | member | update_matter | allow | allowed | Proposed |
| M32 | lawyer | member | build_model_context | allow | allowed | SEC |
| M33 | lawyer | member | review | allow | allowed | SEC |
| M34 | lawyer | member | delete_matter | deny | role_not_permitted | Proposed |
| M35 | partner | member | delete_matter | allow | allowed | Proposed |
| M36 | lawyer | member conflict=conflict | waive_conflict | allow | allowed | Member-lawyer waiver |
| M37 | partner | member conflict=conflict | waive_conflict | allow | allowed | Member-lawyer waiver |
| M38 | lawyer | member conflict=conflict reason=no | waive_conflict | deny | reason_required | Member-lawyer waiver |
| M39 | lawyer | member conflict=pending | waive_conflict | deny | conflict_not_waivable | Member-lawyer waiver |
| M40 | lawyer | member conflict=clear | waive_conflict | deny | conflict_not_waivable | Member-lawyer waiver |
| M41 | lawyer | member conflict=waived | waive_conflict | deny | conflict_not_waivable | Member-lawyer waiver |
| M42 | requester | member conflict=conflict | waive_conflict | deny | role_not_permitted | Member-lawyer waiver |
| M43 | knowledge | member conflict=conflict | waive_conflict | deny | role_not_permitted | Member-lawyer waiver |
| M44 | knowledge+lawyer | member conflict=conflict | waive_conflict | allow | allowed | Member-lawyer waiver |
| M45 | lawyer | member | attest_entry | allow | allowed | Member-lawyer attestation |
| M46 | partner | member | attest_entry | allow | allowed | Member-lawyer attestation |
| M47 | lawyer | member reason=no | attest_entry | deny | reason_required | Member-lawyer attestation |
| M48 | requester | member | attest_entry | deny | role_not_permitted | Member-lawyer attestation |
| M49 | knowledge | member | attest_entry | deny | role_not_permitted | Member-lawyer attestation |
| M50 | knowledge+lawyer | member | attest_entry | allow | allowed | Member-lawyer attestation |
| M51 | requester | member | read_matter | deny | role_not_permitted | SEC |
| M52 | requester | member | search | deny | role_not_permitted | SEC |
| M53 | requester | member | review | deny | role_not_permitted | SEC |
| M54 | requester | member | build_model_context | deny | role_not_permitted | SEC |
| M55 | requester | member | update_matter | deny | role_not_permitted | Proposed |
| M56 | knowledge | member | read_matter | allow | allowed | Proposed |
| M57 | knowledge | member | review | deny | role_not_permitted | Proposed |
| M58 | lawyer | member conflict=pending | review | deny | conflict_not_cleared | SEC, US-3 |
| M59 | partner | member conflict=pending | build_model_context | deny | conflict_not_cleared | SEC, US-3 |
| M60 | lawyer | member conflict=conflict | review | deny | conflict_not_cleared | SEC, US-3 |
| M61 | lawyer | member conflict=waived | review | allow | allowed | Member-lawyer waiver, US-3 |
| M62 | lawyer | member conflict=pending | read_matter | allow | allowed | Proposed |
| M63 | lawyer | member conflict=pending | attest_entry | deny | conflict_not_cleared | Member-lawyer attestation, Proposed |
| M64 | lawyer | member conflict=pending | export_to_client | deny | conflict_not_cleared | SEC |
| M65 | partner | walled-member | read_matter | deny | matter_not_accessible | SEC, API-8 |
| M66 | partner | walled-member | review | deny | matter_not_accessible | SEC |
| M67 | partner | walled-member | search | deny | matter_not_accessible | SEC, API-8 |
| M68 | lawyer | walled-member conflict=conflict | waive_conflict | deny | matter_not_accessible | SEC, Member-lawyer waiver |
| M69 | lawyer | walled-member | attest_entry | deny | matter_not_accessible | SEC, Member-lawyer attestation |
| M70 | partner | walled-member | manage_membership | deny | matter_not_accessible | SEC |
| M71 | lawyer | walled | read_matter | deny | matter_not_accessible | SEC |
| M72 | lawyer+tenant_admin | walled-member | read_matter | deny | matter_not_accessible | SEC |
| M73 | lawyer | member | export_to_client | allow | allowed | SEC, Charter |
| M74 | lawyer | member ledger=unsupported | export_to_client | deny | ledger_unresolved | SEC |
| M75 | partner | member ledger=contradicted | export_to_client | deny | ledger_unresolved | SEC |
| M76 | lawyer | member ledger=unverified | export_to_client | deny | ledger_unresolved | Charter |
| M77 | partner | member ledger=unavailable | export_to_client | deny | ledger_status_unavailable | SEC |
| M78 | requester | member | export_to_client | deny | role_not_permitted | SEC |
| M79 | partner | member target=other | manage_membership | allow | allowed | Proposed |
| M80 | partner | member target=self | manage_membership | deny | self_escalation | SEC |
| M81 | lawyer | member target=other | manage_membership | deny | role_not_permitted | Proposed |
| M82 | tenant_admin | non-member target=self | manage_membership | deny | matter_not_accessible | SEC |
| M83 | lawyer+tenant_admin | member | read_matter | allow | allowed | SEC |
| M84 | requester | member | read_status | allow | allowed | SEC |
| M85 | requester | non-member | read_status | deny | matter_not_accessible | SEC |
| M86 | requester | walled-member | read_status | deny | matter_not_accessible | SEC |
| M87 | requester | member | list_matters | deny | role_not_permitted | SEC |
| M88 | lawyer | none | create_matter | allow | allowed | Synthetic foundation proposal |
| M89 | requester | none | create_matter | deny | role_not_permitted | Synthetic foundation proposal |
| M90 | tenant_admin | none | create_matter | deny | role_not_permitted | Synthetic foundation proposal |
| M91 | lawyer | member conflict=pending | record_conflict_check | allow | allowed | Synthetic foundation proposal |
| M92 | requester | member | record_conflict_check | deny | role_not_permitted | SEC |
| M93 | knowledge | member | record_conflict_check | deny | role_not_permitted | SEC |
| M94 | lawyer | non-member | record_conflict_check | deny | matter_not_accessible | SEC |
| M95 | partner | walled-member | record_conflict_check | deny | matter_not_accessible | SEC |
| M96 | lawyer | other-tenant | record_conflict_check | deny | matter_not_accessible | SEC |
<!-- matrix:end -->

## Forbidden transitions and service-level checks

These are asserted by `apps/api/tests/access/test_matter_service.py` rather than by single policy rows:

- Forged `X-Tenant-Id`, `X-Actor-Id` or `X-Roles` headers are ignored; service methods accept no tenant or actor argument.
- Cross-tenant get, list, search, count, update and delete fail or return nothing; repository writes under a foreign tenant key are rejected.
- A nonexistent matter and an inaccessible one raise the identical error.
- Authorization happens before any content read or review-runner (orchestrator) call.
- Revoked membership, a new ethical wall, a reopened conflict, removed roles or a deactivated actor deny a queued review at execution.
- Every decision (allow or deny) emits an `access.decision` audit event with actor, action, decision and reason code; no titles, document text or reason text. A failing audit sink fails the action closed.
- A waiver records the waiving lawyer, time, reason, and whether the same actor recorded the conflict hit, for sign-off visibility (Member-lawyer waiver compensating control proposed by security; not a block).

## Integration limits and release boundary

Requesters have a separate `read_status` action and projection containing an opaque matter ID and coarse readiness only. They cannot read content, titles, search hits, conflict details, waiver reasons or ledger entries through the content service. Knowledge specialists remain explicitly scoped matter members; legal decisions require a lawyer role.

Authorization is rechecked after awaited audit emission and collections are queried again before returning. This closes the demonstrated event-loop revocation race. SQL reads and mutations also bind storage revisions; external identity revocation and completed mutation audit still need integrated transactional controls. No claim of atomic production authorization is made. Audit events represent authorization decisions, not confirmation that a subsequent mutation succeeded. The audit count describes the pre-audit query; a returned collection may be smaller after a concurrent revocation.

Unknown or malformed ledger status fails closed. An explicitly checked empty ledger is represented by a known status with zero entries, never by an absent record or empty mapping. A future durable ledger must bind coverage and attestation to the exact document/output revision. Current attestation and export objects are authorization scaffolding: they do not persist legal attestation or deliver a client artifact.

The current identity adapter remains synthetic. Repository adapters include process-local memory and durable SQL current projections; no public matter service, HTTP auth, uploaded client documents or live model transport is enabled. The public synthetic preview remains a separate release boundary.


## Local/test synthetic recording foundation

`create_matter` and `record_conflict_check` are application methods only. The API remains health-only. Creation is limited to current lawyer/partner roles with a trusted synthetic profile, derives tenant/actor/opaque ID, starts pending, and grants membership only to the creator. This is a controlled engineering default, not production provisioning policy or requester submission.

A conflict record snapshots its trusted profile, UTC time, CLEAR/CONFLICT result and positive integer version and typed target matter ID. Evidence from one matter cannot unlock another. Replacing it increments the version and removes the prior waiver. Waivers retain member-lawyer authority including visible self-waivers, and bind to the current recorded hit and matter. Check/status/waiver changes during awaited audit reject recording or waiver with `conflict_changed`; the caller must refresh and explicitly retry rather than silently act on another check. Readiness rejects inconsistent/raw/missing provenance, stale waivers and malformed time/version. Names do not grant authority; historical profile snapshots remain valid after rename/deactivation, while new actions always use current identity.

Requester `ready` means ready at the conflict stage only, not resolved ledger, reviewed advice or approved delivery. No recorder/title/reason appears in this projection or access audit payload. Audit decisions remain permission evidence; repository failure after allow is not a successful mutation receipt. The memory adapter remains process-local; the SQL adapter persists current matter/check/profile state across restart. Neither adapter implements complete historical legal evidence or atomic completed outcomes. Durable history, revision-bound matter transactions/outcomes, declined lifecycle, real IdP/HTTP, requester assignment and client uploads remain unfinished.


## Durable repository projection

The SQL repository selects access facts separately from title/document content and applies tenant visibility before collection content reads. The protected access column includes historical names and waiver reasons; it is not public audit metadata. Authorized content reads bind the full access snapshot and storage revision. All updates and physical deletes compare an expected storage revision, rejecting stale operations without automatic retry. Storage revision is independent of the conflict-check version.

Current matter/check/waiver/profile state survives restart through closed JSON schemas and Alembic. Malformed or inconsistent stored facts fail closed with generic errors. These guarantees do not complete authentic identity, shared mutation/audit outcomes, immutable conflict history, multiworker identity revocation, operational RLS, encryption or hold-aware retention. The API remains health-only. See ADR 006 for the current reusable repository boundary.
