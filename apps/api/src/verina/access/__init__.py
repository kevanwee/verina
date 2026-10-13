"""Tenancy, trusted identity and matter authorization (ADR 003, EN-7).

Synthetic and in-memory: no identity vendor, database or HTTP authentication is selected.
See ``docs/security/ACCESS_MATRIX.md`` for the executable roles x actions matrix.
"""

from verina.access.domain import (
    Action,
    ActorId,
    ActorProfile,
    ConflictCheckRecord,
    ConflictStatus,
    ConflictWaiver,
    Decision,
    DenialDetail,
    InvalidIdentifierError,
    MatterAccess,
    MatterContent,
    MatterDocument,
    MatterId,
    MatterRecord,
    ReasonCode,
    Role,
    TenantId,
)
from verina.access.identity import (
    AuthenticationError,
    IdentityAdapter,
    InMemoryIdentityAdapter,
    Principal,
)
from verina.access.policy import (
    GRANTS,
    POLICY_VERSION,
    InMemoryLedgerStatus,
    LedgerEntryStatus,
    LedgerStatusProvider,
    MatterAccessPolicy,
)
from verina.access.repository import (
    AccessFilter,
    InMemoryMatterRepository,
    MatterRepository,
    TenantMismatchError,
)
from verina.access.service import (
    AccessDenied,
    Attestation,
    ExportClearance,
    MatterService,
    MatterStatus,
    MatterSummary,
    ModelContext,
    ReviewJob,
    ReviewRunner,
)
from verina.access.sql_repository import SqlMatterRepository
from verina.access.storage_codec import StoredMatterError

__all__ = [
    "GRANTS",
    "POLICY_VERSION",
    "AccessDenied",
    "AccessFilter",
    "Action",
    "ActorId",
    "ActorProfile",
    "Attestation",
    "AuthenticationError",
    "ConflictCheckRecord",
    "ConflictStatus",
    "ConflictWaiver",
    "Decision",
    "DenialDetail",
    "ExportClearance",
    "IdentityAdapter",
    "InMemoryIdentityAdapter",
    "InMemoryLedgerStatus",
    "InMemoryMatterRepository",
    "InvalidIdentifierError",
    "LedgerEntryStatus",
    "LedgerStatusProvider",
    "MatterAccess",
    "MatterAccessPolicy",
    "MatterContent",
    "MatterDocument",
    "MatterId",
    "MatterRecord",
    "MatterRepository",
    "MatterService",
    "MatterStatus",
    "MatterSummary",
    "ModelContext",
    "Principal",
    "ReasonCode",
    "ReviewJob",
    "ReviewRunner",
    "Role",
    "SqlMatterRepository",
    "StoredMatterError",
    "TenantId",
    "TenantMismatchError",
]
