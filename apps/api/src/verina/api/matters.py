"""Authenticated matter routes under ``/v1`` (ADR 007). Registered only when enabled.

The route layer authenticates through :class:`~verina.access.sql_identity.SqlIdentityAdapter`,
validates headers and a bounded JSON body, and calls :class:`~verina.access.service.MatterService`
composed in durable mode. All authorization stays in the service and policy. Errors are
generic: the body never echoes input, tokens, titles or reasons, and the matter routes return
the same 404 for a missing, other-tenant, walled or non-member matter.

Status mapping (see ``_MATTER_ERRORS``):

* 401 ``unauthenticated`` with ``WWW-Authenticate: Bearer`` - missing/invalid token, unknown
  binding, or a principal deactivated before the request completed;
* 403 ``forbidden`` - collection-level denial only (``POST /v1/matters`` role or profile);
* 404 ``not_found`` - every matter-level visibility or role denial, and a matter-route
  ``Idempotency-Key`` whose receipt belongs to another actor;
* 400 ``bad_request`` - missing/malformed ``Idempotency-Key`` or malformed ``If-Match``;
* 428 ``precondition_required`` - missing ``If-Match`` on a non-create mutation (RFC 6585);
* 409 - stale revision, changed conflict state, or the caller's own ``Idempotency-Key``
  reused for a different request (ADR 007 explains the deviation from the draft's 422);
* 413/415/422 - body too large, not JSON, or failed validation;
* 503 ``unavailable`` - storage, directory or audit failure (fails closed).
"""

import logging
import re
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, ValidationError
from sqlalchemy import Engine

from verina.access.domain import (
    Action,
    ConflictStatus,
    MatterId,
    ReasonCode,
    TenantId,
    conflict_is_ready,
)
from verina.access.identity import AuthenticationError, Principal
from verina.access.mutations import MutationReplayError, SqlMatterMutationUnitOfWork
from verina.access.policy import GRANTS, LedgerEntryStatus, MatterAccessPolicy
from verina.access.service import AccessDenied, MatterService, ModelContext
from verina.access.sql_identity import IdentityUnavailableError, SqlIdentityAdapter
from verina.access.sql_repository import MatterStorageError, SqlMatterRepository
from verina.access.storage_codec import StoredMatterError
from verina.access.tokens import JwksConfigError, JwtVerifier, load_jwks
from verina.ai.audit import AuditEmissionError
from verina.audit.store import SqlAuditStore
from verina.config import Settings
from verina.db import make_engine

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 16 * 1024
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_IF_MATCH = re.compile(r'^(?:"([1-9][0-9]{0,17})"|([1-9][0-9]{0,17}))$')


class MattersApiConfigError(RuntimeError):
    """The matter API is enabled without complete, valid configuration. Startup fails."""


class ApiError(Exception):
    def __init__(self, status: int, error: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(error)
        self.status = status
        self.error = error
        self.headers = headers or {}


_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


def _clean(value: str, allowed_controls: str) -> str:
    """NFC-normalise and refuse invisible/format/separator characters (bidi overrides,
    zero-width characters, line/paragraph separators and control characters)."""
    value = unicodedata.normalize("NFC", value)
    if not value.strip() or any(
        unicodedata.category(c) in _FORBIDDEN_CATEGORIES and c not in allowed_controls
        for c in value
    ):
        raise ValueError("invalid text")
    return value


def _title_text(value: str) -> str:
    return _clean(value, "")


def _reason_text(value: str) -> str:
    return _clean(value, "\n\t")


Title = Annotated[str, StringConstraints(min_length=1, max_length=200), AfterValidator(_title_text)]
Reason = Annotated[
    str, StringConstraints(min_length=1, max_length=2000), AfterValidator(_reason_text)
]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CreateMatterBody(_Body):
    title: Title


class UpdateMatterBody(_Body):
    title: Title


class ConflictCheckBody(_Body):
    result: Literal["CLEAR", "CONFLICT"]


class WaiverBody(_Body):
    reason: Reason


# --------------------------------------------------------------------------- errors

_MATTER_ERRORS: dict[ReasonCode, tuple[int, str]] = {
    ReasonCode.UNAUTHENTICATED: (401, "unauthenticated"),
    ReasonCode.MATTER_NOT_ACCESSIBLE: (404, "not_found"),
    # On a matter route these are only reachable by a visible member, but the contract keeps
    # one 404 for every matter-level denial so no route distinguishes membership states.
    ReasonCode.ROLE_NOT_PERMITTED: (404, "not_found"),
    ReasonCode.PROFILE_REQUIRED: (404, "not_found"),
    ReasonCode.SELF_ESCALATION: (404, "not_found"),
    ReasonCode.TARGET_REQUIRED: (404, "not_found"),
    ReasonCode.MATTER_CHANGED: (409, "revision_mismatch"),
    ReasonCode.CONFLICT_CHANGED: (409, "conflict_changed"),
    ReasonCode.CONFLICT_NOT_WAIVABLE: (409, "conflict_not_waivable"),
    ReasonCode.CONFLICT_NOT_CLEARED: (409, "conflict_not_cleared"),
    ReasonCode.LEDGER_UNRESOLVED: (409, "ledger_unresolved"),
    ReasonCode.LEDGER_STATUS_UNAVAILABLE: (409, "ledger_unresolved"),
    ReasonCode.REASON_REQUIRED: (422, "validation_failed"),
    ReasonCode.ALLOWED: (500, "internal_error"),
}
_COLLECTION_ERRORS: dict[ReasonCode, tuple[int, str]] = {
    **_MATTER_ERRORS,
    ReasonCode.ROLE_NOT_PERMITTED: (403, "forbidden"),
    ReasonCode.PROFILE_REQUIRED: (403, "forbidden"),
}
_CHALLENGE = 'Bearer realm="verina"'


def _unauthenticated(presented: bool) -> ApiError:
    challenge = _CHALLENGE + (', error="invalid_token"' if presented else "")
    return ApiError(401, "unauthenticated", {"WWW-Authenticate": challenge})


def _translate(exc: Exception, *, collection: bool, presented: bool) -> ApiError:
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, AuthenticationError):
        return _unauthenticated(presented)
    if isinstance(exc, AccessDenied):
        status, error = (_COLLECTION_ERRORS if collection else _MATTER_ERRORS)[exc.reason_code]
        return _unauthenticated(presented) if status == 401 else ApiError(status, error)
    if isinstance(exc, MutationReplayError):
        return ApiError(409, "idempotency_key_reused")
    if isinstance(exc, MatterStorageError | IdentityUnavailableError | AuditEmissionError):
        return ApiError(503, "unavailable")
    if isinstance(exc, StoredMatterError):
        return ApiError(500, "internal_error")
    if isinstance(exc, ValueError):
        return ApiError(422, "validation_failed")
    raise exc


def _error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse({"error": exc.error}, status_code=exc.status, headers=exc.headers)


# --------------------------------------------------------------------------- composition


class _UnavailableLedger:
    """No ledger is exposed over HTTP. Any export check fails closed."""

    def entry_status_counts(
        self, tenant_id: TenantId, matter_id: MatterId
    ) -> dict[LedgerEntryStatus, int]:
        raise LookupError("ledger not available over HTTP")


class _NoReviewRunner:
    """Review and model work are not exposed over HTTP in this slice."""

    async def run(self, context: ModelContext) -> str:
        raise RuntimeError("review is not available over HTTP")


@dataclass(frozen=True, slots=True)
class MattersApi:
    """Shared, process-wide composition. One engine for matters, audit and directory."""

    engine: Engine
    repository: SqlMatterRepository
    audit: SqlAuditStore
    uow: SqlMatterMutationUnitOfWork
    identity: SqlIdentityAdapter
    policy: MatterAccessPolicy

    def service_for(self, principal: Principal) -> MatterService:
        # The audit sink is bound to the *authenticated* tenant, never to request input.
        return MatterService(
            repository=self.repository,
            policy=self.policy,
            identity=self.identity,
            audit_sink=self.audit.for_tenant(principal.tenant_id.value),
            review_runner=_NoReviewRunner(),
            mutation_uow=self.uow,
        )


def explicit_local_env(settings: Settings) -> bool:
    """True only when ``env`` was explicitly configured (not defaulted) as local or test."""
    return "env" in settings.model_fields_set and settings.env in ("local", "test")


def _verifier_from(settings: Settings) -> JwtVerifier:
    if not explicit_local_env(settings):
        # The default env is "local"; enabling must not rely on that default. Only an
        # explicitly set local/test environment may run the matters API in this slice.
        raise MattersApiConfigError("matters API requires VERINA_ENV explicitly set to local/test")
    issuer, audience, jwks = settings.auth_issuer, settings.auth_audience, settings.auth_jwks
    if not issuer or not audience or not jwks:
        raise MattersApiConfigError("matters API requires auth_issuer, auth_audience, auth_jwks")
    try:
        return JwtVerifier(
            issuer=issuer,
            audience=audience,
            keys=load_jwks(jwks),
            leeway_seconds=settings.auth_leeway_seconds,
            max_lifetime_seconds=settings.auth_max_token_lifetime_seconds,
            extra_audiences=settings.auth_extra_audiences,
        )
    except JwksConfigError as exc:
        raise MattersApiConfigError(f"invalid auth configuration: {exc}") from None


def build_matters_api(settings: Settings, *, engine: Engine | None = None) -> MattersApi:
    """Compose the durable service graph, failing closed on incomplete auth configuration."""
    verifier = _verifier_from(settings)
    engine = engine or make_engine(settings.database_url)
    key = settings.audit_head_key
    audit = SqlAuditStore(
        engine, head_key=key.get_secret_value().encode("utf-8") if key is not None else None
    )
    repository = SqlMatterRepository(engine)
    return MattersApi(
        engine=engine,
        repository=repository,
        audit=audit,
        uow=SqlMatterMutationUnitOfWork(repository, audit),
        identity=SqlIdentityAdapter(engine, verifier),
        policy=MatterAccessPolicy(_UnavailableLedger()),
    )


# --------------------------------------------------------------------------- request parsing


def _single(request: Request, name: str) -> str | None:
    values = request.headers.getlist(name)
    if len(values) > 1:
        raise ApiError(400, "bad_request")
    return values[0] if values else None


def _operation_id(request: Request) -> UUID:
    raw = _single(request, "idempotency-key")
    if raw is None or _UUID.fullmatch(raw) is None:
        raise ApiError(400, "bad_request")
    return UUID(raw)


def _expected_revision(request: Request) -> int:
    raw = _single(request, "if-match")
    if raw is None:
        raise ApiError(428, "precondition_required")
    match = _IF_MATCH.fullmatch(raw.strip())
    if match is None:
        raise ApiError(400, "bad_request")
    return int(match.group(1) or match.group(2))


async def _body[M: BaseModel](request: Request, model: type[M]) -> M:
    content_type = _single(request, "content-type") or ""
    media, _, params = content_type.partition(";")
    charset = params.strip().lower()
    if media.strip().lower() != "application/json" or charset not in ("", "charset=utf-8"):
        raise ApiError(415, "unsupported_media_type")
    declared = _single(request, "content-length")
    if declared is not None and (
        not declared.isascii()
        or not declared.isdigit()
        or len(declared) > 9
        or int(declared) > MAX_BODY_BYTES
    ):
        raise ApiError(413, "payload_too_large")
    size, chunks = 0, []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise ApiError(413, "payload_too_large")
        chunks.append(chunk)
    try:
        return model.model_validate_json(b"".join(chunks))
    except ValidationError:
        raise ApiError(422, "validation_failed") from None


def _etag(revision: int) -> dict[str, str]:
    return {"ETag": f'"{revision}"'}


# --------------------------------------------------------------------------- routes


def register_matter_routes(app: FastAPI, api: MattersApi) -> None:
    app.state.matters_api = api

    async def guarded(
        request: Request,
        handler: Callable[[Principal], Awaitable[JSONResponse]],
        *,
        collection: bool = False,
    ) -> JSONResponse:
        presented = bool(request.headers.getlist("authorization"))
        try:
            principal = api.identity.authenticate(request.headers)
            return await handler(principal)
        except Exception as exc:  # mapped centrally; unknown errors are re-raised
            try:
                mapped = _translate(exc, collection=collection, presented=presented)
            except Exception:
                logger.error("matters api unhandled failure: %s", type(exc).__name__)
                raise
            return _error_response(mapped)

    def revision_of(principal: Principal, operation_id: UUID, matter_id: MatterId) -> int:
        token = api.uow.peek(principal.tenant_id, operation_id)
        if token is None or token.actor_id != principal.actor_id or token.matter_id != matter_id:
            raise MutationReplayError()
        return token.result_revision

    @app.post("/v1/matters", tags=["matters"], status_code=201)
    async def create_matter(request: Request) -> JSONResponse:
        async def handle(principal: Principal) -> JSONResponse:
            operation_id = _operation_id(request)
            body = await _body(request, CreateMatterBody)
            service = api.service_for(principal)
            matter_id = await service.create_matter(
                principal, body.title, operation_id=operation_id
            )
            revision = revision_of(principal, operation_id, matter_id)
            return JSONResponse(
                {"matter_id": matter_id.value, "revision": revision},
                status_code=201,
                headers={**_etag(revision), "Location": f"/v1/matters/{matter_id.value}"},
            )

        return await guarded(request, handle, collection=True)

    @app.get("/v1/matters/{matter_id}", tags=["matters"])
    async def get_matter(request: Request, matter_id: str) -> JSONResponse:
        async def handle(principal: Principal) -> JSONResponse:
            service = api.service_for(principal)
            if principal.has_any(GRANTS[Action.READ_MATTER]):
                record = await service.get_matter(principal, matter_id)
                access = record.access
                return JSONResponse(
                    {
                        "matter_id": access.matter_id.value,
                        "revision": access.revision,
                        "title": record.content.title,
                        "conflict_status": access.conflict_status.value,
                        "status": "ready" if conflict_is_ready(access) else "awaiting_clearance",
                    },
                    headers=_etag(access.revision),
                )
            status = await service.get_matter_status(principal, matter_id)
            return JSONResponse({"matter_id": status.matter_id.value, "status": status.status})

        return await guarded(request, handle)

    async def mutate[M: BaseModel](
        request: Request,
        matter_id: str,
        model: type[M],
        run: Callable[[MatterService, Principal, M, UUID, int], Awaitable[dict[str, Any]]],
    ) -> JSONResponse:
        async def handle(principal: Principal) -> JSONResponse:
            operation_id = _operation_id(request)
            expected = _expected_revision(request)
            body = await _body(request, model)
            prior = api.uow.peek(principal.tenant_id, operation_id)
            if prior is not None and prior.actor_id != principal.actor_id:
                # Another actor's receipt: answer exactly like an inaccessible matter so a
                # matter route never reveals that the key (or its matter) exists.
                raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)
            service = api.service_for(principal)
            extra = await run(service, principal, body, operation_id, expected)
            parsed = MatterId.parse(matter_id)
            if parsed is None:  # unreachable: the service already refused it
                raise AccessDenied(ReasonCode.MATTER_NOT_ACCESSIBLE)
            revision = revision_of(principal, operation_id, parsed)
            return JSONResponse(
                {"matter_id": parsed.value, "revision": revision, **extra},
                headers=_etag(revision),
            )

        return await guarded(request, handle)

    @app.patch("/v1/matters/{matter_id}", tags=["matters"])
    async def update_matter(request: Request, matter_id: str) -> JSONResponse:
        async def run(
            service: MatterService,
            principal: Principal,
            body: UpdateMatterBody,
            operation_id: UUID,
            expected: int,
        ) -> dict[str, Any]:
            await service.update_title(
                principal,
                matter_id,
                body.title,
                operation_id=operation_id,
                expected_revision=expected,
            )
            return {}

        return await mutate(request, matter_id, UpdateMatterBody, run)

    @app.post("/v1/matters/{matter_id}/conflict-checks", tags=["matters"])
    async def record_conflict_check(request: Request, matter_id: str) -> JSONResponse:
        async def run(
            service: MatterService,
            principal: Principal,
            body: ConflictCheckBody,
            operation_id: UUID,
            expected: int,
        ) -> dict[str, Any]:
            check = await service.record_conflict_check(
                principal,
                matter_id,
                ConflictStatus(body.result.lower()),
                operation_id=operation_id,
                expected_revision=expected,
            )
            return {"conflict_status": check.result.value, "check_version": check.version}

        return await mutate(request, matter_id, ConflictCheckBody, run)

    @app.post("/v1/matters/{matter_id}/conflict-waivers", tags=["matters"])
    async def waive_conflict(request: Request, matter_id: str) -> JSONResponse:
        async def run(
            service: MatterService,
            principal: Principal,
            body: WaiverBody,
            operation_id: UUID,
            expected: int,
        ) -> dict[str, Any]:
            waiver = await service.waive_conflict(
                principal,
                matter_id,
                body.reason,
                operation_id=operation_id,
                expected_revision=expected,
            )
            return {
                "conflict_status": ConflictStatus.WAIVED.value,
                "check_version": waiver.check_version,
            }

        return await mutate(request, matter_id, WaiverBody, run)


def lifespan_for(api: MattersApi) -> Callable[[FastAPI], Any]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            api.engine.dispose()

    return lifespan
