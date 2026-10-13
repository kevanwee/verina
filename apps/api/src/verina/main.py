"""FastAPI application factory."""

from fastapi import FastAPI
from pydantic import BaseModel

from verina import __version__
from verina.config import Settings, get_settings
from verina.security import add_security_headers


class HealthResponse(BaseModel):
    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Verina API. Use with ``uvicorn verina.main:create_app --factory``."""
    settings = settings or get_settings()
    docs_enabled = settings.env in ("local", "test")
    app = FastAPI(
        title="Verina API",
        version=__version__,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    add_security_headers(app)

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app
