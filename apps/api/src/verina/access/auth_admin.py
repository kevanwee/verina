"""Identity-provider administration port: invite users and resend invitations (ADR 009).

:class:`AuthAdminPort` is what the accounts service needs from an identity provider. The
Supabase implementation calls the Supabase Auth (GoTrue) admin API over HTTPS with the
project's secret key; :class:`FakeAuthAdmin` is the in-memory test double.

Supabase endpoints used (see ADR 009 for references):

* ``POST {project}/auth/v1/invite?redirect_to=...`` with ``{"email": ...}`` - creates the user
  if needed and e-mails an invite link. ``200`` returns the user (``id`` is the JWT ``sub``);
  ``422`` means the user already exists and has confirmed their address.
* ``GET {project}/auth/v1/admin/users?page=N&per_page=M`` - used only to look up the ``id`` of
  an already-confirmed user by e-mail (paged, bounded). This avoids minting a login link just
  to learn a user id.

Headers: ``apikey: <secret>``. A legacy ``service_role`` key (a JWT, ``eyJ...``) is also sent
as ``Authorization: Bearer``; new ``sb_secret_...`` keys are not JWTs and are sent on
``apikey`` only, as Supabase's API-key guide requires. The key is a ``SecretStr`` held only in
memory; it is never logged, echoed or included in exceptions. Responses are size-capped and
parsed strictly; failures raise :class:`AuthAdminError` with a coarse ``kind`` only.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

logger = logging.getLogger(__name__)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_RESPONSE_BYTES = 1024 * 1024
LOOKUP_PAGE_SIZE = 200
LOOKUP_MAX_PAGES = 10

FailureKind = Literal["unavailable", "rejected", "rate_limited", "misconfigured"]


class AuthAdminError(Exception):
    """The identity provider call failed. Carries a coarse kind, never request data."""

    def __init__(self, kind: FailureKind) -> None:
        super().__init__(f"identity provider admin call failed: {kind}")
        self.kind: FailureKind = kind


class InviteAlreadyAccepted(Exception):  # noqa: N818 - domain vocabulary
    """The user already confirmed their address; there is no invitation to resend."""


class AuthAdminPort(Protocol):
    def invite_user(self, email: str, redirect_to: str | None = None) -> str:
        """Invite ``email`` (or find the existing user) and return the provider subject."""
        ...

    def resend_invite(self, email: str, redirect_to: str | None = None) -> None:
        """Send the invitation again. Raise :class:`InviteAlreadyAccepted` if confirmed."""
        ...


def validate_project_url(url: str, issuer: str | None = None) -> str:
    """HTTPS project URL with no path beyond ``/``, credentials, query or fragment.

    When ``issuer`` is given its host must match, so invitations and token verification can
    never target two different projects.
    """
    parts = urlsplit(url or "")
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise AuthAdminError("misconfigured")
    if issuer is not None and urlsplit(issuer).hostname != parts.hostname:
        raise AuthAdminError("misconfigured")
    return f"https://{parts.netloc}"


class SupabaseAuthAdmin:
    def __init__(
        self,
        project_url: str,
        secret_key: SecretStr,
        *,
        issuer: str | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not isinstance(secret_key, SecretStr) or not secret_key.get_secret_value().strip():
            raise AuthAdminError("misconfigured")
        self._base = validate_project_url(project_url, issuer) + "/auth/v1"
        self._secret = secret_key
        self._client = client or httpx.Client(trust_env=False)
        self._owns_client = client is None
        self._timeout = httpx.Timeout(timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        key = self._secret.get_secret_value()
        headers = {"apikey": key, "Accept": "application/json"}
        if key.startswith("eyJ") and key.count(".") == 2:  # legacy service_role JWT
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        try:
            with self._client.stream(
                method,
                self._base + path,
                params=params,
                content=None if body is None else json.dumps(body).encode("utf-8"),
                headers={
                    **self._headers(),
                    **({"Content-Type": "application/json"} if body is not None else {}),
                },
                timeout=self._timeout,
                follow_redirects=False,
            ) as response:
                size, chunks = 0, []
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise AuthAdminError("unavailable")
                    chunks.append(chunk)
                status = response.status_code
        except httpx.HTTPError as exc:
            logger.warning("identity provider admin call failed: %s", type(exc).__name__)
            raise AuthAdminError("unavailable") from None
        try:
            payload = json.loads(b"".join(chunks) or b"null")
        except (ValueError, RecursionError):
            payload = None
        return status, payload

    @staticmethod
    def _raise_for(status: int) -> NoReturn:
        if status == 429:
            raise AuthAdminError("rate_limited")
        if status in (401, 403):
            raise AuthAdminError("misconfigured")
        if status >= 500 or status < 200:
            raise AuthAdminError("unavailable")
        raise AuthAdminError("rejected")

    @staticmethod
    def _user_id(payload: object, email: str | None = None) -> str:
        if not isinstance(payload, dict):
            raise AuthAdminError("unavailable")
        user_id = payload.get("id")
        if not isinstance(user_id, str) or _UUID.fullmatch(user_id) is None:
            raise AuthAdminError("unavailable")
        if email is not None and str(payload.get("email", "")).lower() != email:
            raise AuthAdminError("unavailable")
        return user_id

    def _invite(self, email: str, redirect_to: str | None) -> tuple[int, Any]:
        params = {"redirect_to": redirect_to} if redirect_to else None
        return self._call("POST", "/invite", params=params, body={"email": email})

    def invite_user(self, email: str, redirect_to: str | None = None) -> str:
        status, payload = self._invite(email, redirect_to)
        if status == 200:
            return self._user_id(payload, email)
        if status == 422:
            return self._lookup(email)
        self._raise_for(status)

    def resend_invite(self, email: str, redirect_to: str | None = None) -> None:
        status, _ = self._invite(email, redirect_to)
        if status == 200:
            return
        if status == 422:
            raise InviteAlreadyAccepted()
        self._raise_for(status)

    def _lookup(self, email: str) -> str:
        """Find an existing user's id by e-mail with bounded paging of the admin user list."""
        for page in range(1, LOOKUP_MAX_PAGES + 1):
            status, payload = self._call(
                "GET",
                "/admin/users",
                params={"page": str(page), "per_page": str(LOOKUP_PAGE_SIZE)},
            )
            if status != 200:
                self._raise_for(status)
            users = payload.get("users") if isinstance(payload, dict) else None
            if not isinstance(users, list):
                raise AuthAdminError("unavailable")
            for user in users:
                if isinstance(user, dict) and str(user.get("email", "")).lower() == email:
                    return self._user_id(user, email)
            if len(users) < LOOKUP_PAGE_SIZE:
                break
        raise AuthAdminError("rejected")


@dataclass
class FakeAuthAdmin:
    """In-memory identity provider for tests and local development without a provider."""

    users: dict[str, tuple[str, bool]] = field(default_factory=dict)
    """email -> (subject, confirmed)."""
    invites: list[tuple[str, str | None]] = field(default_factory=list)
    resends: list[str] = field(default_factory=list)
    fail_with: FailureKind | None = None
    _counter: int = 0

    def _subject(self) -> str:
        self._counter += 1
        return f"00000000-0000-4000-8000-{self._counter:012d}"

    def invite_user(self, email: str, redirect_to: str | None = None) -> str:
        if self.fail_with is not None:
            raise AuthAdminError(self.fail_with)
        self.invites.append((email, redirect_to))
        if email not in self.users:
            self.users[email] = (self._subject(), False)
        return self.users[email][0]

    def resend_invite(self, email: str, redirect_to: str | None = None) -> None:
        if self.fail_with is not None:
            raise AuthAdminError(self.fail_with)
        subject, confirmed = self.users.get(email, ("", False))
        if not subject:
            raise AuthAdminError("rejected")
        if confirmed:
            raise InviteAlreadyAccepted()
        self.resends.append(email)

    def confirm(self, email: str) -> str:
        subject = self.users[email][0]
        self.users[email] = (subject, True)
        return subject
