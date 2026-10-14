"""Accounts and organizations service (ADR 008, docs/api/ACCOUNTS_CONTRACT.md).

Platform administrators create organizations and invite members; tenant administrators manage
members of their own organization. Every write commits, in one transaction, the directory
change, a metadata-only ``directory.changed`` audit event (organization chain, or the system
chain for platform-level writes) and, for HTTP mutations, an ``admin_idempotency`` row.

Authority comes only from the Verina directory: the platform-admin grant (``platform_admins``,
keyed by verified ``(issuer, subject)``) and the caller's principal roles. Token claims never
grant anything. Denials are uniform ``not_found`` so a caller cannot probe which organizations
or members exist.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select

from verina.access.auth_admin import AuthAdminPort
from verina.access.directory_schema import SYSTEM_CHAIN_ID, platform_admins
from verina.access.subject_hmac import subject_hmac
from verina.audit.events import DirectoryChanged
from verina.audit.store import SqlAuditStore

MAX_EMAIL_LENGTH = 254
_EMAIL = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}"
    r"@(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


class AccountsError(Exception):
    """A generic, disclosable failure code (mapped to HTTP centrally). Carries no input."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalise_email(raw: object) -> str:
    """Lower-case, NFC, ASCII address in a conservative shape; raise ``ValueError`` otherwise.

    Supabase stores e-mail addresses lower-cased; matching the same normal form keeps the
    one-account-one-organization rule exact.
    """
    if not isinstance(raw, str):
        raise ValueError("invalid email")
    value = unicodedata.normalize("NFC", raw).strip().lower()
    if len(value) > MAX_EMAIL_LENGTH or not value.isascii() or _EMAIL.fullmatch(value) is None:
        raise ValueError("invalid email")
    return value


def request_hash(action: str, scope: str, body: object) -> str:
    """Fingerprint of a command. Stored instead of the body (which may hold an e-mail)."""
    material = json.dumps([action, scope, body], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def actor_key(issuer: str, subject: str) -> str:
    return hashlib.sha256(f"{issuer}\n{subject}".encode()).hexdigest()


def bootstrap_platform_admin(
    engine: Engine,
    audit: SqlAuditStore,
    auth_admin: AuthAdminPort,
    *,
    issuer: str,
    email: str,
    redirect_to: str | None = None,
    subject_key: bytes | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Create the first platform administrator; refuse if one already exists.

    Invites (or finds) the identity-provider user for ``email``, then records the grant and a
    ``platform_admin_bootstrapped`` event on the system chain atomically. Returns the opaque
    admin id. The e-mail address is not stored in Verina.
    """
    address = normalise_email(email)
    with engine.connect() as probe:
        if probe.execute(select(platform_admins.c.admin_id).limit(1)).first() is not None:
            raise AccountsError("platform_admin_exists")
    subject = auth_admin.invite_user(address, redirect_to)
    admin_id = "pa_" + uuid4().hex
    now = clock()
    with engine.begin() as conn:
        audit.lock_tenant_on_connection(conn, SYSTEM_CHAIN_ID)
        if conn.execute(select(platform_admins.c.admin_id).limit(1)).first() is not None:
            raise AccountsError("platform_admin_exists")
        conn.execute(
            platform_admins.insert().values(
                issuer=issuer, subject=subject, admin_id=admin_id, created_at=now
            )
        )
        audit.append_on_connection(
            conn,
            SYSTEM_CHAIN_ID,
            DirectoryChanged(
                occurred_at=now,
                tenant_id=SYSTEM_CHAIN_ID,
                actor="cli:bootstrap",
                actor_kind="cli",
                action="platform_admin_bootstrapped",
                target_actor_id=admin_id,
                subject_hmac=subject_hmac(subject_key, issuer, subject),
            ),
        )
    return admin_id
