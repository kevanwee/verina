"""Security headers middleware (placeholder; hardening owned with verina-security)."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


def add_security_headers(app: FastAPI) -> None:
    """Attach baseline security headers to every response."""

    @app.middleware("http")
    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
