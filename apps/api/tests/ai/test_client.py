"""AnthropicClient tests. The real SDK runs end to end against an in-process mock transport,
so request serialisation is exercised without any network access."""

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from verina.ai import (
    AnthropicClient,
    FakeModelClient,
    InMemoryAuditSink,
    ModelClient,
    ModelClientError,
    ModelRegistry,
    ModelRequest,
    Orchestrator,
    StaticRedactionPolicy,
    TemplateRegistry,
    UntrustedDocument,
)
from verina.ai.client import (
    UNTRUSTED_DOCUMENT_CONTEXT,
    ExternalModelCallsDisabledError,
    MissingAPIKeyError,
)
from verina.config import Settings

FAKE_KEY = "synthetic-api-key-canary"

REQUEST = ModelRequest(
    model="claude-opus-5-5",
    system="SYSTEM",
    instructions="Label the clauses.",
    documents=(
        UntrustedDocument("d1", "Main agreement", "1. Term. Two years."),
        UntrustedDocument("d2", "Schedule", "Fees: [EMAIL_1] invoices monthly."),
    ),
    max_tokens=1234,
    effort="high",
    output_schema={"type": "object", "properties": {}, "additionalProperties": False},
)


def _message_json(text: str = "done") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "x"},
            {"type": "text", "text": text},
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 120,
            "output_tokens": 7,
            "cache_read_input_tokens": 100,
            "cache_creation_input_tokens": None,
        },
    }


class Recorder:
    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body if body is not None else _message_json()
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, json=self.body, headers={"request-id": "req_123"})

    @property
    def last_json(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)  # type: ignore[no-any-return]


def _client(recorder: Callable[[httpx2.Request], httpx2.Response]) -> AnthropicClient:
    settings = Settings(env="test", anthropic_api_key=FAKE_KEY, ai_max_retries=0)
    return AnthropicClient.from_settings(settings, mock_transport=httpx2.MockTransport(recorder))


def test_request_shape_documents_separate_and_cached() -> None:
    recorder = Recorder()
    response = asyncio.run(_client(recorder).complete(REQUEST))

    body = recorder.last_json
    assert recorder.requests[0].url.path == "/v1/messages"
    assert recorder.requests[0].headers["x-api-key"] == FAKE_KEY
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 1234
    assert "thinking" not in body  # Opus 5.5: thinking always on; depth set by effort
    assert body["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": dict(REQUEST.output_schema or {})},
    }
    assert body["system"] == [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]
    (message,) = body["messages"]
    assert message["role"] == "user"
    first, second, instructions = message["content"]
    assert first["type"] == second["type"] == "document"
    assert first["source"] == {
        "type": "text",
        "media_type": "text/plain",
        "data": "1. Term. Two years.",
    }
    assert first["context"] == UNTRUSTED_DOCUMENT_CONTEXT
    assert "cache_control" not in first
    assert second["cache_control"] == {"type": "ephemeral"}
    assert instructions == {"type": "text", "text": "Label the clauses."}

    assert response.text == "done"  # thinking blocks ignored
    assert response.served_model == "claude-opus-5-5"
    assert response.input_tokens == 120
    assert response.output_tokens == 7
    assert response.cache_read_input_tokens == 100
    assert response.cache_creation_input_tokens == 0
    assert response.request_id == "req_123"


def test_no_schema_no_documents() -> None:
    recorder = Recorder()
    request = ModelRequest(
        model="claude-haiku-5-5", system="S", instructions="I", documents=(), max_tokens=10,
        effort="low",
    )  # fmt: skip
    asyncio.run(_client(recorder).complete(request))
    body = recorder.last_json
    assert body["output_config"] == {"effort": "low"}
    assert body["messages"][0]["content"] == [{"type": "text", "text": "I"}]


@pytest.mark.parametrize(
    ("status", "retryable"), [(400, False), (401, False), (429, True), (500, True), (529, True)]
)
def test_api_errors_mapped_without_leaking(status: int, retryable: bool) -> None:
    body = {"type": "error", "error": {"type": "x", "message": f"bad key {FAKE_KEY}"}}
    with pytest.raises(ModelClientError) as info:
        asyncio.run(_client(Recorder(status, body)).complete(REQUEST))
    assert info.value.retryable is retryable
    assert info.value.status_code == status
    assert FAKE_KEY not in str(info.value)
    assert info.value.__cause__ is None


def test_connection_error_is_retryable() -> None:
    def explode(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(ModelClientError) as info:
        asyncio.run(_client(explode).complete(REQUEST))
    assert info.value.retryable is True


def test_missing_key() -> None:
    with pytest.raises(MissingAPIKeyError):
        AnthropicClient.from_settings(
            Settings(env="test"), mock_transport=httpx2.MockTransport(Recorder())
        )
    with pytest.raises(MissingAPIKeyError):
        AnthropicClient.from_settings(
            Settings(env="test", anthropic_api_key=""),
            mock_transport=httpx2.MockTransport(Recorder()),
        )


def test_api_key_never_in_logs_events_or_repr(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)  # includes the SDK's and httpx2's debug logging
    settings = Settings(env="test", anthropic_api_key=FAKE_KEY, ai_max_retries=0)
    sink = InMemoryAuditSink()
    client = _client(Recorder(body=_message_json('{"clauses": []}')))
    orch = Orchestrator(
        client=client,
        models=ModelRegistry.from_settings(settings),
        templates=TemplateRegistry.load_default(),
        audit_sink=sink,
        redaction_policy=StaticRedactionPolicy(enabled=True),
    )
    doc = UntrustedDocument("d1", "NDA", "Party email a@example.com.")
    result = asyncio.run(
        orch.run("triage", "clause.triage", {"contract_type": "NDA", "perspective": "Buyer"},
                 [doc], "M-1", "u-1")
    )  # fmt: skip
    assert result.text == '{"clauses": []}'
    assert caplog.records  # logging really was captured
    assert "Party email" not in caplog.text
    assert "a@example.com" not in caplog.text
    assert FAKE_KEY not in caplog.text
    assert FAKE_KEY not in sink.events[0].model_dump_json()
    assert FAKE_KEY not in repr(client)
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in str(settings.model_dump())


def test_clients_satisfy_protocol() -> None:
    assert isinstance(FakeModelClient(), ModelClient)
    assert isinstance(_client(Recorder()), ModelClient)


@pytest.mark.parametrize("env", ["local", "test", "staging", "production"])
def test_live_transport_blocked_before_sdk_construction(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_sdk(*args: Any, **kwargs: Any) -> None:
        pytest.fail("A live SDK must not even be constructed")

    monkeypatch.setattr("verina.ai.client.anthropic.AsyncAnthropic", forbidden_sdk)
    settings = Settings(env=env, anthropic_api_key=FAKE_KEY)
    with pytest.raises(ExternalModelCallsDisabledError):
        AnthropicClient.from_settings(settings)


def test_injected_clients_cannot_bypass_transport_gate() -> None:
    with pytest.raises(ExternalModelCallsDisabledError):
        AnthropicClient(api_key=SecretStr(FAKE_KEY), sdk_client=object())  # type: ignore[arg-type]
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(Recorder()))
    with pytest.raises(ExternalModelCallsDisabledError):
        AnthropicClient(
            api_key=SecretStr(FAKE_KEY),
            http_client=http,
            mock_transport=httpx2.MockTransport(Recorder()),
        )
    asyncio.run(http.aclose())


def test_real_transport_cannot_be_disguised_as_mock() -> None:
    with pytest.raises(ExternalModelCallsDisabledError):
        AnthropicClient(api_key=SecretStr(FAKE_KEY), mock_transport=httpx2.AsyncHTTPTransport())  # type: ignore[arg-type]
