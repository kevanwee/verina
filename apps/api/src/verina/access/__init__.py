"""Tenancy, trusted identity and matter authorization (ADR 003, EN-7).

No identity vendor is selected. ``SqlIdentityAdapter`` verifies bearer tokens against a
configured JWKS and resolves authority from a Verina-owned directory (ADR 007).
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
from verina.access.mutations import (
    MutationReceipt,
    MutationReplayError,
    SqlMatterMutationUnitOfWork,
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
from verina.access.sql_identity import (
    IdentityDirectory,
    IdentityUnavailableError,
    SqlIdentityAdapter,
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
    "IdentityDirectory",
    "IdentityUnavailableError",
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
    "MutationReceipt",
    "MutationReplayError",
    "Principal",
    "ReasonCode",
    "ReviewJob",
    "ReviewRunner",
    "Role",
    "SqlIdentityAdapter",
    "SqlMatterMutationUnitOfWork",
    "SqlMatterRepository",
    "StoredMatterError",
    "TenantId",
    "TenantMismatchError",
]
