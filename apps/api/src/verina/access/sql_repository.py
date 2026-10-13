"""Reusable SQL matter storage. Explicit tenant keys and revision CAS on every mutation."""

import builtins
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Connection,
    Engine,
    MetaData,
    String,
    Table,
    Text,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.sql.elements import ColumnElement

from verina.access.domain import MatterAccess, MatterId, MatterRecord, TenantId
from verina.access.repository import (
    AccessFilter,
    MatterRevisionConflictError,
    TenantMismatchError,
    _require_tenant,
)
from verina.access.storage_codec import decode_access, decode_content, encode_access, encode_content
from verina.db import bind_connection

metadata = MetaData()
matters = Table(
    "matters",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("matter_id", String(128), primary_key=True),
    Column("revision", BigInteger, nullable=False),
    Column("access_json", Text, nullable=False),
    Column("content_json", Text, nullable=False),
    CheckConstraint("revision >= 1", name="ck_matters_positive_revision"),
)


class MatterStorageError(RuntimeError):
    """A generic storage failure; SQL parameters and connection details are never exposed."""


class SqlMatterRepository:
    """Durable repository port, not a production authorization or retention lifecycle."""

    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("unsupported matter database")
        self._engine = engine

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        try:
            with self._engine.begin() as conn, bind_connection(conn):
                yield conn
        except SQLAlchemyError:
            raise MatterStorageError("matter storage unavailable") from None

    @staticmethod
    def _key(tenant: TenantId, matter: MatterId) -> ColumnElement[bool]:
        _require_tenant(tenant)
        if not isinstance(matter, MatterId):
            raise TypeError("a MatterId is required")
        return (matters.c.tenant_id == tenant.value) & (matters.c.matter_id == matter.value)

    def add(self, tenant_id: TenantId, record: MatterRecord) -> None:
        _require_tenant(tenant_id)
        if record.tenant_id != tenant_id:
            raise TenantMismatchError("record tenant does not match the tenant key")
        if type(record.access.revision) is not int or record.access.revision != 1:
            raise ValueError("new matter requires initial revision")
        access = encode_access(record.access)
        content = encode_content(record.content)
        with self._transaction() as conn:
            try:
                conn.execute(
                    matters.insert().values(
                        tenant_id=tenant_id.value,
                        matter_id=record.matter_id.value,
                        revision=1,
                        access_json=access,
                        content_json=content,
                    )
                )
            except IntegrityError:
                raise ValueError("matter already exists") from None

    def get_access(self, tenant_id: TenantId, matter_id: MatterId) -> MatterAccess | None:
        with self._transaction() as conn:
            row = conn.execute(
                select(matters.c.access_json, matters.c.revision).where(
                    self._key(tenant_id, matter_id)
                )
            ).first()
            return (
                decode_access(row.access_json, tenant_id, matter_id, row.revision) if row else None
            )

    def _content(self, conn: Connection, access: MatterAccess) -> MatterRecord:
        raw = conn.execute(
            select(matters.c.content_json).where(
                self._key(access.tenant_id, access.matter_id), matters.c.revision == access.revision
            )
        ).scalar_one_or_none()
        if raw is None:
            raise MatterRevisionConflictError("matter changed")
        return MatterRecord(access, decode_content(raw))

    def get(
        self,
        tenant_id: TenantId,
        matter_id: MatterId,
        *,
        expected_access: MatterAccess | None = None,
    ) -> MatterRecord | None:
        with self._transaction() as conn:
            # Hold a shared row lock on PostgreSQL; SQLite's engine transaction is
            # BEGIN IMMEDIATE. Access comparison precedes the content SELECT.
            row = conn.execute(
                select(matters.c.access_json, matters.c.revision)
                .where(self._key(tenant_id, matter_id))
                .with_for_update(read=True)
            ).first()
            if row is None:
                return None
            access = decode_access(row.access_json, tenant_id, matter_id, row.revision)
            if expected_access is not None and access != expected_access:
                raise MatterRevisionConflictError("matter changed")
            return self._content(conn, access)

    def _visible(
        self, conn: Connection, tenant_id: TenantId, visible: AccessFilter
    ) -> builtins.list[MatterAccess]:
        _require_tenant(tenant_id)
        rows = conn.execute(
            select(matters.c.matter_id, matters.c.access_json, matters.c.revision)
            .where(matters.c.tenant_id == tenant_id.value)
            .order_by(matters.c.matter_id)
            .with_for_update(read=True)
        )
        accesses = [
            decode_access(row.access_json, tenant_id, MatterId(row.matter_id), row.revision)
            for row in rows
        ]
        return [access for access in accesses if visible(access)]

    def list(self, tenant_id: TenantId, *, visible: AccessFilter) -> builtins.list[MatterRecord]:
        with self._transaction() as conn:
            return [
                self._content(conn, access) for access in self._visible(conn, tenant_id, visible)
            ]

    def search(
        self, tenant_id: TenantId, text: str, *, visible: AccessFilter
    ) -> builtins.list[MatterRecord]:
        _require_tenant(tenant_id)
        needle = text.casefold().strip()
        if not needle:
            return []
        return [
            r
            for r in self.list(tenant_id, visible=visible)
            if needle in r.content.title.casefold()
            or any(needle in d.text.casefold() for d in r.content.documents)
        ]

    def count(self, tenant_id: TenantId, *, visible: AccessFilter) -> int:
        with self._transaction() as conn:
            return len(self._visible(conn, tenant_id, visible))

    def update(self, tenant_id: TenantId, record: MatterRecord) -> bool:
        _require_tenant(tenant_id)
        if record.tenant_id != tenant_id:
            raise TenantMismatchError("record tenant does not match the tenant key")
        revision = record.access.revision
        if type(revision) is not int or revision < 1:
            raise ValueError("invalid expected revision")
        access = encode_access(replace(record.access, revision=revision + 1))
        content = encode_content(record.content)
        with self._transaction() as conn:
            result = conn.execute(
                matters.update()
                .where(self._key(tenant_id, record.matter_id), matters.c.revision == revision)
                .values(revision=revision + 1, access_json=access, content_json=content)
            )
            return result.rowcount == 1

    def delete(self, tenant_id: TenantId, matter_id: MatterId, *, expected_revision: int) -> bool:
        key = self._key(tenant_id, matter_id)
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("invalid expected revision")
        with self._transaction() as conn:
            result = conn.execute(
                matters.delete().where(key, matters.c.revision == expected_revision)
            )
            return result.rowcount == 1
