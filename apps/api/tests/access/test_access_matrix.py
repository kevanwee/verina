"""Executes each row of docs/security/ACCESS_MATRIX.md as a policy assertion (EN-7).

The markdown table is the specification. This test parses it, builds the principal through
the trusted identity adapter and the matter state described by the row, and asserts the
policy's outcome and reason code.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from verina.access import (
    GRANTS,
    Action,
    ActorId,
    ConflictStatus,
    InMemoryIdentityAdapter,
    LedgerEntryStatus,
    MatterAccess,
    MatterAccessPolicy,
    MatterId,
    MatterRecord,
    ReasonCode,
    Role,
    TenantId,
)
from verina.access.domain import DenialDetail

pytestmark = pytest.mark.story("EN-7")

MATRIX_PATH = Path(__file__).resolve().parents[4] / "docs" / "security" / "ACCESS_MATRIX.md"
TENANT = TenantId("tenant-a")
OTHER_TENANT = TenantId("tenant-b")
ACTOR = ActorId("actor-under-test")
MATTER = MatterId("m-matrix")

RELATIONS = {"member", "non-member", "walled-member", "walled", "other-tenant", "missing", "none"}
NOT_VISIBLE_DETAIL = {
    "non-member": DenialDetail.NOT_MEMBER,
    "walled-member": DenialDetail.ETHICAL_WALL,
    "walled": DenialDetail.ETHICAL_WALL,
    "other-tenant": DenialDetail.TENANT_MISMATCH,
    "missing": DenialDetail.MATTER_NOT_FOUND,
}


@dataclass(frozen=True)
class Row:
    id: str
    roles: tuple[Role, ...]
    relation: str
    options: dict[str, str]
    action: Action
    allowed: bool
    reason: ReasonCode
    basis: str


def _parse() -> list[Row]:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    match = re.search(r"<!-- matrix:start -->(.*?)<!-- matrix:end -->", text, re.DOTALL)
    assert match, "matrix markers missing"
    rows: list[Row] = []
    for line in match.group(1).strip().splitlines()[2:]:  # skip header and separator
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 7, line
        row_id, roles, matter, action, outcome, reason, basis = cells
        relation, *opts = matter.split()
        assert relation in RELATIONS, line
        assert outcome in {"allow", "deny"}, line
        rows.append(
            Row(
                id=row_id,
                roles=() if roles == "none" else tuple(Role(r) for r in roles.split("+")),
                relation=relation,
                options=dict(o.split("=", 1) for o in opts),
                action=Action(action),
                allowed=outcome == "allow",
                reason=ReasonCode(reason),
                basis=basis,
            )
        )
    return rows


ROWS = _parse()


class _Ledger:
    def __init__(self, state: str) -> None:
        self.state = state

    def entry_status_counts(
        self, tenant_id: TenantId, matter_id: MatterId
    ) -> dict[LedgerEntryStatus, int]:
        if self.state == "unavailable":
            raise RuntimeError("ledger store offline (synthetic)")
        counts = {LedgerEntryStatus.VERIFIED: 3, LedgerEntryStatus.ATTESTED: 1}
        if self.state != "clean":
            counts[LedgerEntryStatus(self.state)] = 1
        return counts


def _matter(row: Row) -> MatterAccess | None:
    if row.relation in {"missing", "none"}:
        return None
    members = {ACTOR} if row.relation in {"member", "walled-member"} else set()
    walled = {ACTOR} if row.relation in {"walled-member", "walled"} else set()
    return MatterAccess(
        OTHER_TENANT if row.relation == "other-tenant" else TENANT,
        MATTER,
        members=frozenset(members | {ActorId("someone-else")}),
        walled=frozenset(walled),
        conflict_status=ConflictStatus(row.options.get("conflict", "clear")),
    )


@pytest.mark.parametrize("row", ROWS, ids=[r.id for r in ROWS])
def test_matrix_row(row: Row) -> None:
    identity = InMemoryIdentityAdapter()
    principal = identity.register("tok-matrix", TENANT.value, ACTOR.value, row.roles)
    policy = MatterAccessPolicy(_Ledger(row.options.get("ledger", "clean")))
    reason = (
        "Synthetic reason recorded by the lawyer."
        if row.options.get("reason", "yes") == "yes"
        else "  "
    )
    target = ACTOR if row.options.get("target", "other") == "self" else ActorId("new-member")

    decision = policy.decide(
        principal, row.action, _matter(row), reason=reason, target_actor=target
    )

    assert (decision.allowed, decision.reason_code) == (row.allowed, row.reason), row
    if row.reason is ReasonCode.MATTER_NOT_ACCESSIBLE:
        assert decision.detail is NOT_VISIBLE_DETAIL[row.relation]
    else:
        assert decision.detail is None


def test_matrix_covers_every_action_and_role() -> None:
    assert {r.action for r in ROWS} == set(Action)
    assert {role for r in ROWS for role in r.roles} == set(Role)
    assert set(GRANTS) == set(Action), "every action needs an explicit grant entry"


def test_matrix_ids_unique_and_po_decisions_cited() -> None:
    ids = [r.id for r in ROWS]
    assert len(ids) == len(set(ids))
    waive_or_attest = [r for r in ROWS if r.action in {Action.WAIVE_CONFLICT, Action.ATTEST_ENTRY}]
    assert waive_or_attest
    for row in waive_or_attest:
        expected = (
            "Member-lawyer waiver"
            if row.action is Action.WAIVE_CONFLICT
            else "Member-lawyer attestation"
        )
        assert expected in row.basis, row.id


def test_matrix_allows_waive_and_attest_only_for_member_lawyers() -> None:
    """Every allowed waiver/attestation requires matter membership and a lawyer role."""
    for row in ROWS:
        if row.action in {Action.WAIVE_CONFLICT, Action.ATTEST_ENTRY} and row.allowed:
            assert row.relation == "member", row.id
            assert {Role.LAWYER, Role.PARTNER} & set(row.roles), row.id


def test_unscoped_matter_action_denied_without_detail_leak() -> None:
    identity = InMemoryIdentityAdapter()
    principal = identity.register("t", TENANT.value, ACTOR.value, [Role.PARTNER])
    decision = MatterAccessPolicy(_Ledger("clean")).decide(principal, Action.READ_MATTER, None)
    assert decision.reason_code is ReasonCode.MATTER_NOT_ACCESSIBLE


def test_decide_rejects_non_principal() -> None:
    policy = MatterAccessPolicy(_Ledger("clean"))
    forged = object()
    decision = policy.decide(forged, Action.READ_MATTER, None)  # type: ignore[arg-type]
    assert decision.reason_code is ReasonCode.UNAUTHENTICATED


def test_overlong_reason_rejected() -> None:
    identity = InMemoryIdentityAdapter()
    principal = identity.register("t", TENANT.value, ACTOR.value, [Role.LAWYER])
    access = MatterAccess(
        TENANT, MATTER, members=frozenset({ACTOR}), conflict_status=ConflictStatus.CONFLICT
    )
    decision = MatterAccessPolicy(_Ledger("clean")).decide(
        principal, Action.WAIVE_CONFLICT, access, reason="x" * 2001
    )
    assert decision.reason_code is ReasonCode.REASON_REQUIRED


def test_negative_ledger_count_blocks_export() -> None:
    class Weird:
        def entry_status_counts(
            self, tenant_id: TenantId, matter_id: MatterId
        ) -> dict[LedgerEntryStatus, int]:
            return {LedgerEntryStatus.UNSUPPORTED: -1}

    identity = InMemoryIdentityAdapter()
    principal = identity.register("t", TENANT.value, ACTOR.value, [Role.LAWYER])
    access = MatterAccess(
        TENANT, MATTER, members=frozenset({ACTOR}), conflict_status=ConflictStatus.CLEAR
    )
    decision = MatterAccessPolicy(Weird()).decide(principal, Action.EXPORT_TO_CLIENT, access)
    assert decision.reason_code is ReasonCode.LEDGER_STATUS_UNAVAILABLE


def test_matter_record_exposes_ids() -> None:
    access = MatterAccess(TENANT, MATTER)
    from verina.access import MatterContent

    record = MatterRecord(access, MatterContent("t"))
    assert (record.tenant_id, record.matter_id) == (TENANT, MATTER)
