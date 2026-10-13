import pytest
from fastapi.testclient import TestClient

from verina.config import Settings
from verina.main import create_app
from verina.security import SECURITY_HEADERS


def _client() -> TestClient:
    return TestClient(create_app(Settings(env="test")))


@pytest.mark.story("EN-1")
def test_health_returns_ok() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.story("EN-1")
def test_health_sets_security_headers() -> None:
    response = _client().get("/health")
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


@pytest.mark.story("EN-1")
def test_docs_disabled_in_production() -> None:
    client = TestClient(create_app(Settings(env="production")))
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
