"""Closed, versioned JSON storage codec; never creates current identity authority."""

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from verina.access.domain import (
    ActorId,
    ActorProfile,
    ConflictCheckRecord,
    ConflictStatus,
    ConflictWaiver,
    MatterAccess,
    MatterContent,
    MatterDocument,
    MatterId,
    TenantId,
    _issue_profile,
    conflict_is_ready,
    conflict_record_is_valid,
    is_utc_time,
)

Name = Annotated[StrictStr, Field(min_length=1, max_length=120)]
Identifier = Annotated[StrictStr, Field(min_length=1, max_length=128)]
Positive = Annotated[StrictInt, Field(gt=0)]


class StoredMatterError(RuntimeError):
    """Stored data is invalid; the exception never exposes field values."""

    def __init__(self) -> None:
        super().__init__("invalid stored matter")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Profile(_Closed):
    tenant_id: Identifier
    actor_id: Identifier
    display_name: Name


class _Check(_Closed):
    matter_id: Identifier
    result: Literal["clear", "conflict"]
    recorded_by: Identifier
    recorded_at: Annotated[StrictStr, Field(max_length=40)]
    version: Positive
    recorder_profile: _Profile


class _Waiver(_Closed):
    matter_id: Identifier
    check_version: Positive
    actor_profile: _Profile
    waived_by: Identifier
    reason: Annotated[StrictStr, Field(min_length=1, max_length=2000)]
    waived_at: Annotated[StrictStr, Field(max_length=40)]
    same_actor_as_conflict_recorder: StrictBool


class _Access(_Closed):
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    tenant_id: Identifier
    matter_id: Identifier
    revision: Positive
    members: Annotated[list[Identifier], Field(max_length=1000)]
    walled: Annotated[list[Identifier], Field(max_length=1000)]
    conflict_status: Literal["pending", "clear", "conflict", "waived"]
    conflict_recorded_by: Identifier | None
    conflict_check: _Check | None
    waiver: _Waiver | None


class _Document(_Closed):
    document_id: Identifier
    title: Annotated[StrictStr, Field(min_length=1, max_length=200)]
    text: Annotated[StrictStr, Field(max_length=1_000_000)]


class _Content(_Closed):
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    title: Annotated[StrictStr, Field(min_length=1, max_length=200)]
    documents: Annotated[list[_Document], Field(max_length=100)]


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if not is_utc_time(result):
        raise StoredMatterError()
    return result


def _profile(value: _Profile) -> ActorProfile:
    # This is historical presentation evidence from validated repository storage,
    # not credential authentication, account provisioning or a Principal issuer.
    return _issue_profile(TenantId(value.tenant_id), ActorId(value.actor_id), value.display_name)


def _validate_access(access: MatterAccess) -> None:
    if type(access.revision) is not int or access.revision < 1:
        raise StoredMatterError()
    if access.conflict_status is ConflictStatus.PENDING:
        if any(
            v is not None
            for v in (access.conflict_check, access.waiver, access.conflict_recorded_by)
        ):
            raise StoredMatterError()
    elif access.conflict_status is ConflictStatus.CONFLICT:
        if not conflict_record_is_valid(access) or access.waiver is not None:
            raise StoredMatterError()
    elif not conflict_is_ready(access):
        raise StoredMatterError()


def _json(raw: str, maximum: int) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw) > maximum:
        raise StoredMatterError()

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise StoredMatterError()
            result[key] = value
        return result

    result = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise StoredMatterError()
    return result


def decode_access(raw: str, tenant: TenantId, matter: MatterId, revision: int) -> MatterAccess:
    """Validate every stored fact and bind it to the row's tenant/matter/revision."""
    try:
        if not isinstance(tenant, TenantId) or not isinstance(matter, MatterId):
            raise StoredMatterError()
        if type(revision) is not int or revision < 1:
            raise StoredMatterError()
        value = _Access.model_validate(_json(raw, 500_000))
        if value.schema_version != 1 or type(value.schema_version) is not int:
            raise StoredMatterError()
        if (
            value.tenant_id != tenant.value
            or value.matter_id != matter.value
            or value.revision != revision
        ):
            raise StoredMatterError()
        if len(set(value.members)) != len(value.members) or len(set(value.walled)) != len(
            value.walled
        ):
            raise StoredMatterError()
        check = None
        if value.conflict_check is not None:
            c = value.conflict_check
            check = ConflictCheckRecord(
                MatterId(c.matter_id),
                ConflictStatus(c.result),
                ActorId(c.recorded_by),
                _time(c.recorded_at),
                c.version,
                _profile(c.recorder_profile),
            )
        waiver = None
        if value.waiver is not None:
            w = value.waiver
            waiver = ConflictWaiver(
                MatterId(w.matter_id),
                w.check_version,
                _profile(w.actor_profile),
                ActorId(w.waived_by),
                w.reason,
                _time(w.waived_at),
                w.same_actor_as_conflict_recorder,
            )
        access = MatterAccess(
            tenant,
            matter,
            frozenset(ActorId(v) for v in value.members),
            frozenset(ActorId(v) for v in value.walled),
            ConflictStatus(value.conflict_status),
            ActorId(value.conflict_recorded_by) if value.conflict_recorded_by is not None else None,
            waiver,
            check,
            value.revision,
        )
        _validate_access(access)
        return access
    except (ValueError, TypeError, RecursionError):
        raise StoredMatterError() from None


def encode_access(access: MatterAccess) -> str:
    try:
        _validate_access(access)
        c = access.conflict_check
        w = access.waiver

        def profile(value: ActorProfile) -> dict[str, str]:
            return {
                "tenant_id": value.tenant_id.value,
                "actor_id": value.actor_id.value,
                "display_name": value.display_name,
            }

        payload = {
            "schema_version": 1,
            "tenant_id": access.tenant_id.value,
            "matter_id": access.matter_id.value,
            "revision": access.revision,
            "members": sorted(v.value for v in access.members),
            "walled": sorted(v.value for v in access.walled),
            "conflict_status": access.conflict_status.value,
            "conflict_recorded_by": access.conflict_recorded_by.value
            if access.conflict_recorded_by
            else None,
            "conflict_check": None
            if c is None
            else {
                "matter_id": c.matter_id.value,
                "result": c.result.value,
                "recorded_by": c.recorded_by.value,
                "recorded_at": c.recorded_at.isoformat(),
                "version": c.version,
                "recorder_profile": profile(c.recorder_profile),
            },
            "waiver": None
            if w is None
            else {
                "matter_id": w.matter_id.value,
                "check_version": w.check_version,
                "actor_profile": profile(w.actor_profile),
                "waived_by": w.waived_by.value,
                "reason": w.reason,
                "waived_at": w.waived_at.isoformat(),
                "same_actor_as_conflict_recorder": w.same_actor_as_conflict_recorder,
            },
        }
        raw = _Access.model_validate(payload).model_dump_json()
        decode_access(raw, access.tenant_id, access.matter_id, access.revision)
        return raw
    except (ValueError, TypeError, AttributeError):
        raise StoredMatterError() from None


def encode_content(content: MatterContent) -> str:
    try:
        value = _Content.model_validate(
            {
                "schema_version": 1,
                "title": content.title,
                "documents": [
                    {"document_id": d.document_id, "title": d.title, "text": d.text}
                    for d in content.documents
                ],
            }
        )
        raw = value.model_dump_json()
        decode_content(raw)
        return raw
    except (ValueError, TypeError, AttributeError):
        raise StoredMatterError() from None


def decode_content(raw: str) -> MatterContent:
    try:
        value = _Content.model_validate(_json(raw, 5_000_000))
        if type(value.schema_version) is not int or not value.title.strip():
            raise StoredMatterError()
        ids = [d.document_id for d in value.documents]
        if len(set(ids)) != len(ids):
            raise StoredMatterError()
        for d in value.documents:
            MatterId(d.document_id)
            if not d.title.strip():
                raise StoredMatterError()
        return MatterContent(
            value.title,
            tuple(MatterDocument(d.document_id, d.title, d.text) for d in value.documents),
        )
    except (ValueError, TypeError, RecursionError):
        raise StoredMatterError() from None
