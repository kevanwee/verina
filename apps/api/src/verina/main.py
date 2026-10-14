"""FastAPI application factory."""

from fastapi import FastAPI
from pydantic import BaseModel

from verina import __version__
from verina.api.accounts import register_account_routes
from verina.api.matters import build_matters_api, lifespan_for, register_matter_routes
from verina.config import Settings, get_settings
from verina.security import add_security_headers


class HealthResponse(BaseModel):
    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Verina API. Use with ``uvicorn verina.main:create_app --factory``.

    Health-only by default. With ``VERINA_MATTERS_API_ENABLED=true`` the authenticated
    ``/v1/matters`` routes (ADR 007) and the accounts routes ``/v1/me``,
    ``/v1/admin/organizations*`` and ``/v1/organizations/{id}/members*`` (ADR 008) are
    registered; incomplete auth configuration raises
    :class:`~verina.api.matters.MattersApiConfigError` and the app does not start.
    """
    settings = settings or get_settings()
    docs_enabled = settings.env in ("local", "test")
    matters_api = None
    lifespan = None
    if settings.matters_api_enabled:
        matters_api = build_matters_api(settings)
        lifespan = lifespan_for(matters_api)
    app = FastAPI(
        title="Verina API",
        version=__version__,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    add_security_headers(app)

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    if matters_api is not None:
        register_matter_routes(app, matters_api)
        register_account_routes(app, matters_api)

    return app
