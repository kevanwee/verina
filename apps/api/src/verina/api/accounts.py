"""Accounts, organizations and members routes under ``/v1`` (ADR 008).

The exact HTTP contract is ``docs/api/ACCOUNTS_CONTRACT.md``. Routes authenticate with the same
verified bearer token as the matter routes and resolve authority only from the Verina
directory (:meth:`~verina.access.sql_identity.SqlIdentityAdapter.resolve`):

* ``GET /v1/me`` is the only route that accepts a valid token without an active binding; it
  answers ``{"linked": false}`` instead of 401.
* ``/v1/admin/organizations*`` require the platform-admin grant (and ``aal2`` when
  ``VERINA_AUTH_ADMIN_REQUIRE_AAL2`` is on, answered with an RFC 9470 step-up challenge).
* ``/v1/organizations/{org_id}/members*`` allow a platform admin for any organization and a
  ``tenant_admin`` for their own organization only.

Every other caller gets the uniform ``404 {"error": "not_found"}``; unlinked or invalid tokens
get 401. Mutations need an ``Idempotency-Key`` (UUID). Blocking database and identity-provider
calls run in the worker thread pool, not on the event loop. Error bodies never echo input.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, Self

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import AfterValidator, Field, StringConstraints, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from verina.access.accounts import AccountsError, Caller, normalise_email
from verina.access.auth_admin import AuthAdminError
from verina.access.identity import AuthenticationError
from verina.access.sql_identity import IdentityUnavailableError
from verina.api.gate import RateLimited
from verina.api.matters import (
    ApiError,
    MattersApi,
    _Body,
    _body,
    _error_response,
    _operation_id,
    _title_text,
    _unauthenticated,
)
from verina.audit.events import AuditPayloadError
from verina.audit.store import AuditIntegrityError

logger = logging.getLogger(__name__)

Surface = Literal["me", "admin", "members"]

ACCOUNT_ERRORS: dict[str, tuple[int, str]] = {
    "not_found": (404, "not_found"),
    "slug_taken": (409, "slug_taken"),
    "account_exists": (409, "account_exists"),
    "last_admin": (409, "last_admin"),
    "idempotency_key_reused": (409, "idempotency_key_reused"),
    "organization_inactive": (409, "organization_inactive"),
    "member_inactive": (409, "member_inactive"),
    "invite_already_accepted": (409, "invite_already_accepted"),
    "insufficient_user_authentication": (401, "insufficient_user_authentication"),
}
STEP_UP_CHALLENGE = (
    'Bearer realm="verina", error="insufficient_user_authentication", '
    'error_description="multi-factor authentication required", acr_values="aal2"'
)

# ----------------------------------------------------------------------------- bodies

Name = Annotated[str, StringConstraints(min_length=1, max_length=120), AfterValidator(_title_text)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9](-?[a-z0-9]){1,39}$")]
Email = Annotated[
    str, StringConstraints(min_length=3, max_length=254), AfterValidator(normalise_email)
]
RoleName = Literal["partner", "lawyer", "requester", "knowledge", "tenant_admin"]


def _unique_roles(value: list[RoleName]) -> list[RoleName]:
    if len(set(value)) != len(value):
        raise ValueError("duplicate roles")
    return value


Roles = Annotated[list[RoleName], Field(min_length=1, max_length=5), AfterValidator(_unique_roles)]


class _PatchBody(_Body):
    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("nothing to change")
        return self


class CreateOrganizationBody(_Body):
    name: Name
    slug: Slug


class UpdateOrganizationBody(_PatchBody):
    name: Name | None = None
    active: bool | None = None


class InviteMemberBody(_Body):
    email: Email
    display_name: Name
    roles: Roles


class UpdateMemberBody(_PatchBody):
    roles: Roles | None = None
    active: bool | None = None
    display_name: Name | None = None


# ----------------------------------------------------------------------------- errors


def translate(exc: Exception, *, presented: bool) -> ApiError:
    """Central mapping to the generic error contract; unknown exceptions are re-raised."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, RateLimited):
        return ApiError(429, "rate_limited", {"Retry-After": str(exc.retry_after)})
    if isinstance(exc, AuthenticationError):
        return _unauthenticated(presented)
    if isinstance(exc, AccountsError):
        status, error = ACCOUNT_ERRORS.get(exc.code, (500, "internal_error"))
        if status == 401:
            return ApiError(status, error, {"WWW-Authenticate": STEP_UP_CHALLENGE})
        return ApiError(status, error)
    if isinstance(exc, AuthAdminError):
        if exc.kind == "rate_limited":
            return ApiError(429, "rate_limited", {"Retry-After": "60"})
        return ApiError(503, "unavailable")
    if isinstance(
        exc,
        IdentityUnavailableError | SQLAlchemyError | AuditIntegrityError | AuditPayloadError,
    ):
        return ApiError(503, "unavailable")
    if isinstance(exc, ValueError):
        return ApiError(422, "validation_failed")
    raise exc


# ----------------------------------------------------------------------------- routes


def register_account_routes(app: FastAPI, api: MattersApi) -> None:
    service = api.accounts

    async def caller_for(request: Request, *, allow_unlinked: bool) -> Caller:
        resolution = await run_in_threadpool(api.identity.resolve, request.headers)
        if (
            not allow_unlinked
            and resolution.principal is None
            and resolution.platform_admin_id is None
        ):
            raise AuthenticationError(resolution.unlinked_reason or "unbound", resolution.subject)
        return Caller(
            issuer=resolution.token.issuer,
            subject=resolution.token.subject,
            aal=resolution.token.aal,
            principal=resolution.principal,
            platform_admin_id=resolution.platform_admin_id,
        )

    async def guarded(
        request: Request,
        surface: Surface,
        handler: Callable[[Caller], Awaitable[Response]],
        *,
        allow_unlinked: bool = False,
    ) -> Response:
        presented = bool(request.headers.getlist("authorization"))
        try:
            api.gate.check_client(request)
            try:
                caller = await caller_for(request, allow_unlinked=allow_unlinked)
            except AuthenticationError as failure:
                await api.gate.failed(request, failure, surface)
                raise
            return await handler(caller)
        except Exception as exc:  # mapped centrally; unknown errors are re-raised
            try:
                mapped = translate(exc, presented=presented)
            except Exception:
                logger.error("accounts api unhandled failure: %s", type(exc).__name__)
                raise
            return _error_response(mapped)

    def ok(body: Any, status: int = 200) -> JSONResponse:
        return JSONResponse(body, status_code=status)

    # ---- identity ----------------------------------------------------------------------

    @app.get("/v1/me", tags=["accounts"])
    async def me(request: Request) -> Response:
        async def handle(caller: Caller) -> Response:
            return ok(await run_in_threadpool(service.me, caller))

        return await guarded(request, "me", handle, allow_unlinked=True)

    # ---- platform administration -------------------------------------------------------

    @app.get("/v1/admin/organizations", tags=["accounts"])
    async def list_organizations(request: Request) -> Response:
        async def handle(caller: Caller) -> Response:
            orgs = await run_in_threadpool(service.list_organizations, caller)
            return ok(
                {"organizations": [{**o.public(), "member_count": o.member_count} for o in orgs]}
            )

        return await guarded(request, "admin", handle)

    @app.post("/v1/admin/organizations", tags=["accounts"], status_code=201)
    async def create_organization(request: Request) -> Response:
        async def handle(caller: Caller) -> Response:
            operation_id = _operation_id(request)
            body = await _body(request, CreateOrganizationBody)
            outcome = await run_in_threadpool(
                service.create_organization, caller, operation_id, body.name, body.slug
            )
            return ok(outcome.value.public(), outcome.status)

        return await guarded(request, "admin", handle)

    @app.get("/v1/admin/organizations/{org_id}", tags=["accounts"])
    async def get_organization(request: Request, org_id: str) -> Response:
        async def handle(caller: Caller) -> Response:
            view = await run_in_threadpool(service.get_organization, caller, org_id)
            return ok(view.public())

        return await guarded(request, "admin", handle)

    @app.patch("/v1/admin/organizations/{org_id}", tags=["accounts"])
    async def update_organization(request: Request, org_id: str) -> Response:
        async def handle(caller: Caller) -> Response:
            operation_id = _operation_id(request)
            body = await _body(request, UpdateOrganizationBody)

            def run() -> Any:
                return service.update_organization(
                    caller, operation_id, org_id, name=body.name, active=body.active
                )

            outcome = await run_in_threadpool(run)
            return ok(outcome.value.public(), outcome.status)

        return await guarded(request, "admin", handle)

    # ---- members -----------------------------------------------------------------------

    @app.get("/v1/organizations/{org_id}/members", tags=["accounts"])
    async def list_members(request: Request, org_id: str) -> Response:
        async def handle(caller: Caller) -> Response:
            members = await run_in_threadpool(service.list_members, caller, org_id)
            return ok({"members": [m.public() for m in members]})

        return await guarded(request, "members", handle)

    @app.post("/v1/organizations/{org_id}/members", tags=["accounts"], status_code=201)
    async def invite_member(request: Request, org_id: str) -> Response:
        async def handle(caller: Caller) -> Response:
            operation_id = _operation_id(request)
            body = await _body(request, InviteMemberBody)
            api.gate.allow_invite(caller.key)

            def run() -> Any:
                return service.invite_member(
                    caller,
                    operation_id,
                    org_id,
                    email=body.email,
                    display_name=body.display_name,
                    roles=list(body.roles),
                )

            outcome = await run_in_threadpool(run)
            return ok(outcome.value.public(), outcome.status)

        return await guarded(request, "members", handle)

    @app.patch("/v1/organizations/{org_id}/members/{actor_id}", tags=["accounts"])
    async def update_member(request: Request, org_id: str, actor_id: str) -> Response:
        async def handle(caller: Caller) -> Response:
            operation_id = _operation_id(request)
            body = await _body(request, UpdateMemberBody)

            def run() -> Any:
                return service.update_member(
                    caller,
                    operation_id,
                    org_id,
                    actor_id,
                    roles=None if body.roles is None else list(body.roles),
                    active=body.active,
                    display_name=body.display_name,
                )

            outcome = await run_in_threadpool(run)
            return ok(outcome.value.public(), outcome.status)

        return await guarded(request, "members", handle)

    @app.post(
        "/v1/organizations/{org_id}/members/{actor_id}/resend-invite",
        tags=["accounts"],
        status_code=202,
    )
    async def resend_invite(request: Request, org_id: str, actor_id: str) -> Response:
        async def handle(caller: Caller) -> Response:
            operation_id = _operation_id(request)
            api.gate.allow_invite(caller.key)
            outcome = await run_in_threadpool(
                service.resend_invite, caller, operation_id, org_id, actor_id
            )
            return ok({}, outcome.status)

        return await guarded(request, "members", handle)
