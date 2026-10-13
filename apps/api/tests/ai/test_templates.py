from pathlib import Path

import pytest

from verina.ai.models import ModelRole
from verina.ai.templates import (
    UNTRUSTED_CONTENT_FRAME,
    PromptTemplate,
    TemplateError,
    TemplateNotFoundError,
    TemplateRegistry,
    parse_semver,
)

# Pinned hashes of shipped templates. If this test fails you edited a template: bump its
# version (new file) instead of changing a released one. Audit events reference these.
PINNED_HASHES = {
    "clause.triage@0.1.0": (
        "sha256:ecd655c173e3cc6a189e023982148690b0b436cf79b7663240cff3603715a068"
    ),
}

MINIMAL = """
id = "test.echo"
version = "{version}"
role = "triage"
variables = ["topic"]
system = "You are a test."
instructions = "Say something about ${{topic}}."
"""


def _minimal(version: str = "1.0.0") -> str:
    return MINIMAL.format(version=version)


def test_shipped_templates_match_pinned_hashes() -> None:
    registry = TemplateRegistry.load_default()
    assert registry.refs() == sorted(PINNED_HASHES)
    for ref, expected in PINNED_HASHES.items():
        template_id, version = ref.split("@")
        assert registry.get(template_id, version).content_hash == expected


def test_hash_stable_across_loads_and_line_endings() -> None:
    a = PromptTemplate.from_toml(_minimal())
    b = PromptTemplate.from_toml(_minimal())
    crlf = PromptTemplate.from_toml(_minimal().replace("\n", "\r\n"))
    assert a.content_hash == b.content_hash == crlf.content_hash
    assert a.content_hash.startswith("sha256:")
    assert len(a.content_hash) == len("sha256:") + 64


def test_hash_changes_with_content_or_version() -> None:
    base = PromptTemplate.from_toml(_minimal())
    bumped = PromptTemplate.from_toml(_minimal("1.0.1"))
    edited = PromptTemplate.from_toml(_minimal().replace("You are a test.", "You are tested."))
    assert len({base.content_hash, bumped.content_hash, edited.content_hash}) == 3


def test_system_prompt_starts_with_untrusted_frame() -> None:
    template = TemplateRegistry.load_default().get("clause.triage")
    assert template.system_prompt.startswith(UNTRUSTED_CONTENT_FRAME)
    assert template.role is ModelRole.TRIAGE
    assert template.output_schema is not None


def test_render_requires_exact_variables() -> None:
    template = PromptTemplate.from_toml(_minimal())
    assert template.render({"topic": "indemnities"}) == "Say something about indemnities."
    with pytest.raises(TemplateError, match="expected variables"):
        template.render({})
    with pytest.raises(TemplateError, match="expected variables"):
        template.render({"topic": "x", "document": "smuggled text"})


def test_render_rejects_long_or_non_string_values() -> None:
    template = PromptTemplate.from_toml(_minimal())
    with pytest.raises(TemplateError, match="pass long text as a document"):
        template.render({"topic": "x" * 5000})
    with pytest.raises(TemplateError, match="must be a string"):
        template.render({"topic": 42})  # type: ignore[dict-item]


def test_variable_values_are_not_re_expanded() -> None:
    template = PromptTemplate.from_toml(_minimal())
    assert template.render({"topic": "${topic} $other"}) == "Say something about ${topic} $other."


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        ('version = "1.0.0"', 'version = "1.0"', "semver"),
        ('id = "test.echo"', 'id = "Test Echo"', "dotted lowercase"),
        ('role = "triage"', 'role = "oracle"', "unknown task role"),
        ('variables = ["topic"]', 'variables = ["topic", "extra"]', "do not match"),
        ('system = "You are a test."', 'system = "Hi ${topic}"', "must not contain"),
        ('system = "You are a test."\n', "", "missing required key"),
        ('variables = ["topic"]', 'variables = ["Topic"]', "bad variable name"),
        ('variables = ["topic"]', 'variables = ["topic", "topic"]', "duplicate variable"),
        ("${topic}", "${topic", "invalid placeholder"),
        ('id = "test.echo"', "id = ", "invalid TOML"),
    ],
)
def test_malformed_templates_rejected(needle: str, replacement: str, message: str) -> None:
    with pytest.raises(TemplateError, match=message):
        PromptTemplate.from_toml(_minimal().replace(needle, replacement))


def test_registry_versions_and_lookup(tmp_path: Path) -> None:
    for version in ("1.2.0", "1.10.0", "1.9.3"):
        (tmp_path / f"echo-{version}.toml").write_text(_minimal(version), encoding="utf-8")
    registry = TemplateRegistry.from_directory(tmp_path)
    assert len(registry) == 3
    assert registry.get("test.echo").version == "1.10.0"  # semver, not string, ordering
    assert registry.get("test.echo", "1.2.0").version == "1.2.0"
    with pytest.raises(TemplateNotFoundError):
        registry.get("test.echo", "9.9.9")
    with pytest.raises(TemplateNotFoundError):
        registry.get("no.such")


def test_registry_rejects_duplicates() -> None:
    template = PromptTemplate.from_toml(_minimal())
    with pytest.raises(TemplateError, match="duplicate"):
        TemplateRegistry([template, template])


def test_parse_semver() -> None:
    assert parse_semver("2.10.3") == (2, 10, 3)
    with pytest.raises(TemplateError):
        parse_semver("01.0.0")
