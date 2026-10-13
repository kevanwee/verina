"""Application-service boundary tests (EN-7; threats API-2, API-3, API-8, DS-1)."""

import asyncio
import inspect
from collections.abc import Awaitable

import pytest
from pydantic import BaseModel

from verina.access import (
    AccessDenied,
    ActorId,
    AuthenticationError,
    ConflictStatus,
    LedgerEntryStatus,
    MatterId,
    MatterService,
    Principal,
    ReasonCode,
    Role,
    TenantId,
)
from verina.ai import AuditEmissionError
from verina.audit.events import AccessAuditEvent

from .conftest import TENANT_A, TENANT_B, World, build_world

pytestmark = pytest.mark.story("EN-7")

REASON = "Client consented in writing; synthetic reason."


def run[T](coro: Awaitable[T]) -> T:
    async def _wrap() -> T:
        return await coro

    return asyncio.run(_wrap())


def denied(world: World, coro: Awaitable[object]) -> AccessDenied:
    with pytest.raises(AccessDenied) as info:
        run(coro)
    return info.value


def last_event(world: World) -> AccessAuditEvent:
    return world.sink.access_events[-1]


# --------------------------------------------------------------- identity / forgery


def test_forged_tenant_actor_and_role_headers_are_ignored(world: World) -> None:
    principal = world.identity.authenticate(
        {
            "Authorization": "Bearer tok-a-requester",
            "X-Tenant-Id": "tenant-b",
            "X-Actor-Id": "b-partner",
            "X-Roles": "partner,tenant_admin",
        }
    )
    assert principal.tenant_id == TENANT_A
    assert principal.actor_id == ActorId("a-requester")
    assert principal.roles == frozenset({Role.REQUESTER})


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Basic tok-a-lawyer"},
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer tok-unknown"},
        {"Authorization": "Bearer tök-ünicode"},
        {"X-Actor-Id": "a-partner", "X-Tenant-Id": "tenant-a"},
    ],
)
def test_missing_or_untrusted_credentials_rejected(world: World, headers: dict[str, str]) -> None:
    with pytest.raises(AuthenticationError) as info:
        world.identity.authenticate(headers)
    assert str(info.value) == "unauthenticated"


def test_deactivated_actor_cannot_authenticate(world: World) -> None:
    world.identity.deactivate(TENANT_A, ActorId("a-lawyer"))
    with pytest.raises(AuthenticationError):
        world.identity.authenticate({"authorization": "bearer tok-a-lawyer"})


def test_principal_cannot_be_constructed_outside_the_adapter() -> None:
    with pytest.raises(TypeError):
        Principal(TenantId("tenant-a"), ActorId("a-partner"), frozenset({Role.PARTNER}))


def test_service_methods_accept_no_tenant_or_actor_argument() -> None:
    for name, method in inspect.getmembers(MatterService, inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        params = set(inspect.signature(method).parameters)
        assert not params & {"tenant", "tenant_id", "actor", "actor_id", "roles"}, name


def test_non_principal_caller_rejected(world: World) -> None:
    forged = object()
    error = denied(world, world.service.get_matter(forged, "m-alpha"))  # type: ignore[arg-type]
    assert error.reason_code is ReasonCode.UNAUTHENTICATED
    assert world.repo.calls == []


# ------------------------------------------------------------------ cross-tenant


def test_cross_tenant_get_is_indistinguishable_from_missing(world: World) -> None:
    lawyer = world.p("a-lawyer")
    cross = denied(world, world.service.get_matter(lawyer, "m-bravo"))
    missing = denied(world, world.service.get_matter(lawyer, "m-does-not-exist"))
    no_access = denied(world, world.service.get_matter(world.p("a-outsider"), "m-alpha"))
    assert cross.reason_code is ReasonCode.MATTER_NOT_ACCESSIBLE
    assert str(cross) == str(missing) == str(no_access) == "access denied: matter_not_accessible"
    details = [e.detail_code for e in world.sink.access_events]
    assert details == ["matter_not_found", "matter_not_found", "not_member"]


def test_same_matter_id_in_two_tenants_resolves_by_trusted_tenant(world: World) -> None:
    a = run(world.service.get_matter(world.p("a-lawyer"), "m-shared"))
    b = run(world.service.get_matter(world.p("b-partner"), "m-shared"))
    assert a.content.title == "Tenant A shared-id matter"
    assert b.content.title == "Tenant B shared-id matter"


def test_cross_tenant_list_search_count_exclude_other_tenant(world: World) -> None:
    lawyer = world.p("a-lawyer")
    listed = [m.matter_id.value for m in run(world.service.list_matters(lawyer))]
    assert listed == ["m-alpha", "m-beta", "m-gamma", "m-shared"]
    assert run(world.service.count_matters(lawyer)) == 4
    hits = [m.matter_id.value for m in run(world.service.search_matters(lawyer, "liability"))]
    assert hits == ["m-alpha", "m-gamma"]  # tenant B's "Liability cap" never matches
    b_listed = [m.matter_id.value for m in run(world.service.list_matters(world.p("b-partner")))]
    assert b_listed == ["m-bravo", "m-shared"]


def test_cross_tenant_update_and_delete_denied_and_unchanged(world: World) -> None:
    partner = world.p("a-partner")
    assert denied(world, world.service.update_title(partner, "m-bravo", "pwned")).reason_code is (
        ReasonCode.MATTER_NOT_ACCESSIBLE
    )
    assert denied(world, world.service.delete_matter(partner, "m-bravo")).reason_code is (
        ReasonCode.MATTER_NOT_ACCESSIBLE
    )
    record = world.repo.get(TENANT_B, MatterId("m-bravo"))
    assert record is not None and record.content.title == "Bravo secret review"


# ------------------------------------------------------- same-tenant non-members


def test_non_member_denied_before_any_content_read(world: World) -> None:
    outsider = world.p("a-outsider")
    for call in (
        world.service.get_matter(outsider, "m-alpha"),
        world.service.build_model_context(outsider, "m-alpha"),
        world.service.submit_review(outsider, "m-alpha"),
        world.service.export_to_client(outsider, "m-alpha"),
        world.service.attest_entry(outsider, "m-alpha", "entry-1", REASON),
    ):
        assert denied(world, call).reason_code is ReasonCode.MATTER_NOT_ACCESSIBLE
    assert "get" not in world.repo.calls
    assert world.runner.contexts == []


def test_non_member_lists_and_counts_nothing(world: World) -> None:
    outsider = world.p("a-outsider")
    assert run(world.service.list_matters(outsider)) == []
    assert run(world.service.count_matters(outsider)) == 0
    assert run(world.service.search_matters(outsider, "review")) == []
    assert [e.result_count for e in world.sink.access_events] == [0, 0, 0]


# ---------------------------------------------------------------- tenant admin


def test_tenant_admin_has_no_content_access_even_with_membership(world: World) -> None:
    admin = world.p("a-admin")  # listed as a member of m-alpha, holds only tenant_admin
    assert denied(world, world.service.get_matter(admin, "m-alpha")).reason_code is (
        ReasonCode.ROLE_NOT_PERMITTED
    )
    assert denied(world, world.service.get_matter(admin, "m-beta")).reason_code is (
        ReasonCode.MATTER_NOT_ACCESSIBLE
    )
    assert denied(world, world.service.build_model_context(admin, "m-alpha")).reason_code is (
        ReasonCode.ROLE_NOT_PERMITTED
    )
    assert denied(world, world.service.list_matters(admin)).reason_code is (
        ReasonCode.ROLE_NOT_PERMITTED
    )
    assert denied(world, world.service.search_matters(admin, "liability")).reason_code is (
        ReasonCode.ROLE_NOT_PERMITTED
    )
    assert "get" not in world.repo.calls
    run(world.service.authorize_tenant_administration(admin))
    assert last_event(world).decision == "allow"


def test_lawyer_cannot_administer_tenant(world: World) -> None:
    error = denied(world, world.service.authorize_tenant_administration(world.p("a-partner")))
    assert error.reason_code is ReasonCode.ROLE_NOT_PERMITTED


# --------------------------------------------------------------- ethical walls


def test_ethical_wall_overrides_partner_membership(world: World) -> None:
    walled = world.p("a-walled")  # partner, member of m-alpha, behind its wall
    for call in (
        world.service.get_matter(walled, "m-alpha"),
        world.service.build_model_context(walled, "m-alpha"),
        world.service.export_to_client(walled, "m-alpha"),
        world.service.grant_membership(walled, "m-alpha", "a-outsider"),
    ):
        error = denied(world, call)
        assert error.reason_code is ReasonCode.MATTER_NOT_ACCESSIBLE
        assert "wall" not in str(error)
    assert {e.detail_code for e in world.sink.access_events} == {"ethical_wall"}
    assert run(world.service.list_matters(walled)) == []
    assert run(world.service.search_matters(walled, "liability")) == []


# ------------------------------------------------------------- conflict gate


def test_pending_conflict_blocks_review_and_model_work(world: World) -> None:
    lawyer = world.p("a-lawyer")
    for call in (
        world.service.submit_review(lawyer, "m-gamma"),
        world.service.build_model_context(lawyer, "m-gamma"),
    ):
        assert denied(world, call).reason_code is ReasonCode.CONFLICT_NOT_CLEARED
    assert world.runner.contexts == []
    assert "get" not in world.repo.calls
    assert run(world.service.get_matter(lawyer, "m-gamma")).content.title == "Gamma licence review"


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_waiver_without_reason_rejected(world: World, reason: str) -> None:
    error = denied(world, world.service.waive_conflict(world.p("a-lawyer"), "m-beta", reason))
    assert error.reason_code is ReasonCode.REASON_REQUIRED
    assert world.access(TENANT_A, "m-beta").conflict_status is ConflictStatus.CONFLICT


def test_waiver_by_non_member_or_non_lawyer_rejected(world: World) -> None:
    assert denied(
        world, world.service.waive_conflict(world.p("a-outsider"), "m-beta", REASON)
    ).reason_code is (ReasonCode.MATTER_NOT_ACCESSIBLE)
    assert denied(
        world, world.service.waive_conflict(world.p("a-admin"), "m-beta", REASON)
    ).reason_code is (ReasonCode.MATTER_NOT_ACCESSIBLE)
    assert denied(
        world, world.service.waive_conflict(world.p("b-partner"), "m-beta", REASON)
    ).reason_code is (ReasonCode.MATTER_NOT_ACCESSIBLE)
    assert world.access(TENANT_A, "m-beta").conflict_status is ConflictStatus.CONFLICT


def test_member_lawyer_waiver_is_recorded_audited_and_unblocks_review(world: World) -> None:
    lawyer = world.p("a-lawyer")  # also recorded the conflict hit
    waiver = run(world.service.waive_conflict(lawyer, "m-beta", f"  {REASON}  "))
    assert waiver.waived_by == ActorId("a-lawyer")
    assert waiver.reason == REASON
    assert waiver.same_actor_as_conflict_recorder is True
    access = world.access(TENANT_A, "m-beta")
    assert access.conflict_status is ConflictStatus.WAIVED and access.waiver == waiver

    event = last_event(world)
    assert (event.action, event.decision, event.actor) == ("waive_conflict", "allow", "a-lawyer")
    assert event.same_actor_as_conflict_recorder is True
    assert event.reason_sha256 is not None and len(event.reason_sha256) == 64
    assert REASON not in event.model_dump_json()

    job = run(world.service.submit_review(lawyer, "m-beta"))
    assert run(world.service.execute_review(job)) == "reviewed m-beta for a-lawyer"


def test_partner_waiver_flags_different_actor(world: World) -> None:
    waiver = run(world.service.waive_conflict(world.p("a-partner"), "m-beta", REASON))
    assert waiver.same_actor_as_conflict_recorder is False
    second = denied(world, world.service.waive_conflict(world.p("a-lawyer"), "m-beta", REASON))
    assert second.reason_code is ReasonCode.CONFLICT_NOT_WAIVABLE


# ----------------------------------------------------------- self-escalation


def test_self_escalation_attempts_denied(world: World) -> None:
    svc = world.service
    cases = [
        (svc.grant_membership(world.p("a-admin"), "m-beta", "a-admin"), "matter_not_accessible"),
        (svc.grant_membership(world.p("a-partner"), "m-alpha", "a-partner"), "self_escalation"),
        (svc.grant_membership(world.p("a-lawyer"), "m-alpha", "a-outsider"), "role_not_permitted"),
        (
            svc.grant_membership(world.p("a-requester"), "m-alpha", "a-requester"),
            "role_not_permitted",
        ),
        (svc.grant_membership(world.p("a-walled"), "m-alpha", "a-walled"), "matter_not_accessible"),
        (
            svc.grant_membership(world.p("a-partner"), "m-alpha", "not a valid id!"),
            "target_required",
        ),
        (
            svc.grant_membership(world.p("b-partner"), "m-alpha", "b-partner"),
            "matter_not_accessible",
        ),
    ]
    for call, reason in cases:
        assert denied(world, call).reason_code.value == reason
    assert ActorId("a-admin") not in world.access(TENANT_A, "m-beta").members


def test_partner_can_add_another_member(world: World) -> None:
    run(world.service.grant_membership(world.p("a-partner"), "m-alpha", "a-outsider"))
    record = run(world.service.get_matter(world.p("a-outsider"), "m-alpha"))
    assert record.matter_id == MatterId("m-alpha")


# ------------------------------------------------- revocation at execution time


@pytest.mark.parametrize(
    ("revoke", "reason"),
    [
        ("membership", ReasonCode.MATTER_NOT_ACCESSIBLE),
        ("wall", ReasonCode.MATTER_NOT_ACCESSIBLE),
        ("conflict", ReasonCode.CONFLICT_NOT_CLEARED),
        ("role", ReasonCode.ROLE_NOT_PERMITTED),
        ("deactivate", ReasonCode.UNAUTHENTICATED),
        ("deleted", ReasonCode.MATTER_NOT_ACCESSIBLE),
    ],
)
def test_queued_review_re_evaluated_at_execution(revoke: str, reason: ReasonCode) -> None:
    world = build_world()
    actor = ActorId("a-lawyer")
    job = run(world.service.submit_review(world.p("a-lawyer"), "m-alpha"))
    members = world.access(TENANT_A, "m-alpha").members
    if revoke == "membership":
        world.set_access(TENANT_A, "m-alpha", members=members - {actor})
    elif revoke == "wall":
        world.set_access(TENANT_A, "m-alpha", walled=frozenset({actor}))
    elif revoke == "conflict":
        world.set_access(TENANT_A, "m-alpha", conflict_status=ConflictStatus.PENDING)
    elif revoke == "role":
        world.identity.set_roles(TENANT_A, actor, [Role.REQUESTER])
    elif revoke == "deactivate":
        world.identity.deactivate(TENANT_A, actor)
    else:
        assert world.repo.delete(
            TENANT_A,
            MatterId("m-alpha"),
            expected_revision=world.access(TENANT_A, "m-alpha").revision,
        )

    assert denied(world, world.service.execute_review(job)).reason_code is reason
    assert world.runner.contexts == []
    assert last_event(world).decision == "deny"


def test_queued_review_executes_with_fresh_authority(world: World) -> None:
    job = run(world.service.submit_review(world.p("a-lawyer"), "m-alpha"))
    assert run(world.service.execute_review(job)) == "reviewed m-alpha for a-lawyer"
    (context,) = world.runner.contexts
    assert (context.tenant_id, context.actor_id) == (TENANT_A, ActorId("a-lawyer"))
    assert [d.document_id for d in context.documents] == ["doc-1"]
    assert [e.decision for e in world.sink.access_events] == ["allow", "allow", "allow"]


def test_stale_principal_uses_current_roles(world: World) -> None:
    stale = world.p("a-lawyer")
    world.identity.set_roles(TENANT_A, ActorId("a-lawyer"), [Role.REQUESTER])
    assert denied(world, world.service.build_model_context(stale, "m-alpha")).reason_code is (
        ReasonCode.ROLE_NOT_PERMITTED
    )
    world.identity.deactivate(TENANT_A, ActorId("a-lawyer"))
    assert denied(world, world.service.list_matters(stale)).reason_code is (
        ReasonCode.UNAUTHENTICATED
    )
    assert last_event(world).detail_code == "principal_inactive"


# ------------------------------------------------------- attestation and export


def test_attestation_by_member_lawyer_with_reason(world: World) -> None:
    att = run(world.service.attest_entry(world.p("a-lawyer"), "m-alpha", " entry-7 ", REASON))
    assert (att.entry_id, att.attested_by, att.reason) == ("entry-7", ActorId("a-lawyer"), REASON)
    assert last_event(world).reason_sha256 is not None


@pytest.mark.parametrize(
    ("actor", "reason", "expected"),
    [
        ("a-lawyer", "", ReasonCode.REASON_REQUIRED),
        ("a-requester", REASON, ReasonCode.ROLE_NOT_PERMITTED),
        ("a-knowledge", REASON, ReasonCode.ROLE_NOT_PERMITTED),
        ("a-admin", REASON, ReasonCode.ROLE_NOT_PERMITTED),
        ("a-outsider", REASON, ReasonCode.MATTER_NOT_ACCESSIBLE),
    ],
)
def test_attestation_denials(world: World, actor: str, reason: str, expected: ReasonCode) -> None:
    error = denied(world, world.service.attest_entry(world.p(actor), "m-alpha", "entry-7", reason))
    assert error.reason_code is expected


def test_attestation_requires_entry_id(world: World) -> None:
    with pytest.raises(ValueError, match="entry_id"):
        run(world.service.attest_entry(world.p("a-lawyer"), "m-alpha", "  ", REASON))


@pytest.mark.parametrize(
    "status",
    [LedgerEntryStatus.UNSUPPORTED, LedgerEntryStatus.CONTRADICTED, LedgerEntryStatus.UNVERIFIED],
)
def test_export_denied_with_unresolved_ledger_entries(
    world: World, status: LedgerEntryStatus
) -> None:
    world.ledger.set(TENANT_A, MatterId("m-alpha"), {LedgerEntryStatus.VERIFIED: 5, status: 1})
    error = denied(world, world.service.export_to_client(world.p("a-partner"), "m-alpha"))
    assert error.reason_code is ReasonCode.LEDGER_UNRESOLVED


def test_export_allowed_when_ledger_resolved(world: World) -> None:
    world.ledger.set(
        TENANT_A,
        MatterId("m-alpha"),
        {
            LedgerEntryStatus.VERIFIED: 5,
            LedgerEntryStatus.ATTESTED: 2,
            LedgerEntryStatus.UNSUPPORTED: 0,
        },
    )
    clearance = run(world.service.export_to_client(world.p("a-lawyer"), "m-alpha"))
    assert clearance.cleared_for == ActorId("a-lawyer")


# ----------------------------------------------------------- mutations / misc


def test_update_and_delete_by_authorized_members(world: World) -> None:
    run(world.service.update_title(world.p("a-lawyer"), "m-alpha", "  Renamed  "))
    assert run(world.service.get_matter(world.p("a-lawyer"), "m-alpha")).content.title == "Renamed"
    with pytest.raises(ValueError, match="title"):
        run(world.service.update_title(world.p("a-lawyer"), "m-alpha", " "))
    assert denied(
        world, world.service.delete_matter(world.p("a-lawyer"), "m-alpha")
    ).reason_code is (ReasonCode.ROLE_NOT_PERMITTED)
    run(world.service.delete_matter(world.p("a-partner"), "m-alpha"))
    assert world.repo.get(TENANT_A, MatterId("m-alpha")) is None


@pytest.mark.parametrize("bad", ["", "../m-alpha", "m alpha", "x" * 500, "m-alpha\x00"])
def test_malformed_matter_ids_denied_without_echoing_input(world: World, bad: str) -> None:
    error = denied(world, world.service.get_matter(world.p("a-partner"), bad))
    assert error.reason_code is ReasonCode.MATTER_NOT_ACCESSIBLE
    assert last_event(world).matter_id is None
    assert world.repo.calls == []


# ------------------------------------------------------------------- audit


def test_every_decision_audited_without_content(world: World) -> None:
    svc, p = world.service, world.p
    run(svc.get_matter(p("a-lawyer"), "m-alpha"))
    run(svc.list_matters(p("a-lawyer")))
    run(svc.search_matters(p("a-lawyer"), "liability"))
    run(svc.build_model_context(p("a-lawyer"), "m-alpha"))
    run(svc.waive_conflict(p("a-partner"), "m-beta", REASON))
    denied(world, svc.get_matter(p("a-outsider"), "m-alpha"))
    denied(world, svc.get_matter(p("a-lawyer"), "m-bravo"))

    events = world.sink.access_events
    assert len(events) == len(world.sink.access_events) == 7
    assert [e.decision for e in events] == ["allow"] * 5 + ["deny"] * 2
    for event in events:
        blob = event.model_dump_json()
        for secret in ("Alpha supply", "Liability cap", "Bravo secret", REASON, "liability"):
            assert secret not in blob
        assert event.tenant_id == "tenant-a"
        assert event.policy_version
    assert events[-1].matter_id == "m-bravo" and events[-1].detail_code == "matter_not_found"


class _BrokenSink:
    async def emit(self, event: BaseModel) -> None:
        raise RuntimeError("audit store offline (synthetic)")


def test_audit_failure_fails_closed(world: World) -> None:
    world.service._sink = _BrokenSink()
    with pytest.raises(AuditEmissionError):
        run(world.service.waive_conflict(world.p("a-lawyer"), "m-beta", REASON))
    assert world.access(TENANT_A, "m-beta").conflict_status is ConflictStatus.CONFLICT
    with pytest.raises(AuditEmissionError):
        run(world.service.build_model_context(world.p("a-lawyer"), "m-alpha"))
    assert "get" not in world.repo.calls
    with pytest.raises(AuditEmissionError):
        run(world.service.get_matter(world.p("a-outsider"), "m-alpha"))
