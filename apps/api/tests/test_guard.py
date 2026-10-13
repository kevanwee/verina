"""Self-test for scripts/guard.py (EN-2): proves the repository guard fails on planted cases."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

GUARD_PATH = Path(__file__).resolve().parents[3] / "scripts" / "guard.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verina_repo_guard", GUARD_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()

BLOCKED = [
    "private/BACKLOG.md",
    "Private/notes.md",
    "private/.env.example",
    "Private/.ENV.EXAMPLE",
    "samples-real/contract.docx",
    "samples-real/.env.example",
    ".env",
    "apps/api/.env",
    ".env.local",
    "apps/api/.ENV.production",
    "config/production.env",
    "certs/server.pem",
    "certs/server.PEM",
    "keys/signing.key",
    "keys/client.p12",
    "keys/client.pfx",
    "home/id_rsa",
    "id_ed25519",
]
ALLOWED = [
    "apps/api/.env.example",
    ".env.example",
    "docs/private/ok.md",
    "apps/web/env.ts",
    "apps/api/src/verina/config.py",
    "README.md",
    "id_rsa.pub",
]


@pytest.mark.story("EN-2")
@pytest.mark.parametrize("path", BLOCKED)
def test_blocks_confidential_and_secret_paths(path: str) -> None:
    assert guard.blocked_paths([path]) == [path]


@pytest.mark.story("EN-2")
@pytest.mark.parametrize("path", ALLOWED)
def test_allows_ordinary_paths(path: str) -> None:
    assert guard.blocked_paths([path]) == []


PY_VIOLATIONS = [
    "import anthropic\n",
    "import anthropic as a\n",
    "from anthropic.types import Message\n",
    "from openai import OpenAI\n",
    "import os, openai\n",
    "    import litellm\n",
    "import google.genai\n",
    "from langchain_anthropic import ChatAnthropic\n",
    "mod = importlib.import_module('anthropic')\n",
    'mod = __import__("openai")\n',
]
JS_VIOLATIONS = [
    "import Anthropic from '@anthropic-ai/sdk';\n",
    'import OpenAI from "openai/resources";\n',
    'import { generateText } from "ai";\n',
    'import { x } from "ai/rsc";\n',
    'import { GoogleGenAI } from "@google/genai/node";\n',
    'import "openai";\n',
    'const a = require("@anthropic-ai/sdk");\n',
    'const m = await import("openai");\n',
    'export * from "openai";\n',
]
CLEAN_SOURCES = [
    ("x.py", "import os\nfrom verina.ai import orchestrator\n"),
    ("x.py", "import anthropicish_helpers\n"),
    ("x.ts", 'import { motion } from "./ai-panel";\nimport x from "aidan";\n'),
]


def _plant(root: Path, rel: str, text: str) -> str:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return rel


@pytest.mark.story("EN-2")
@pytest.mark.parametrize("source", PY_VIOLATIONS)
def test_flags_python_model_sdk_outside_orchestrator(tmp_path: Path, source: str) -> None:
    rel = _plant(tmp_path, "apps/api/src/verina/matters/x.py", source)
    assert guard.model_sdk_violations([rel], root=tmp_path) == [rel]


@pytest.mark.story("EN-2")
@pytest.mark.parametrize("source", JS_VIOLATIONS)
def test_flags_js_model_sdk(tmp_path: Path, source: str) -> None:
    rel = _plant(tmp_path, "apps/web/app/x.tsx", source)
    assert guard.model_sdk_violations([rel], root=tmp_path) == [rel]


@pytest.mark.story("EN-2")
def test_orchestrator_may_import_model_sdk(tmp_path: Path) -> None:
    rel = _plant(tmp_path, "apps/api/src/verina/ai/client.py", "import anthropic\n")
    assert guard.model_sdk_violations([rel], root=tmp_path) == []


@pytest.mark.story("EN-2")
@pytest.mark.parametrize(("name", "source"), CLEAN_SOURCES)
def test_ignores_non_sdk_imports(tmp_path: Path, name: str, source: str) -> None:
    rel = _plant(tmp_path, f"apps/x/{name}", source)
    assert guard.model_sdk_violations([rel], root=tmp_path) == []


@pytest.mark.story("EN-2")
def test_repository_is_clean() -> None:
    """The real working tree passes the guard (tracked + untracked, not ignored)."""
    paths = guard.tracked_files()
    assert guard.blocked_paths(paths) == []
    assert guard.model_sdk_violations(paths) == []
    assert (guard.ROOT / ".githooks" / "pre-commit").is_file()


@pytest.mark.story("EN-2")
def test_tracked_private_file_is_blocked_even_when_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ignored files already in the index still reach the CI guard."""
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    _plant(tmp_path, ".gitignore", "private/\n")
    rel = _plant(tmp_path, "private/synthetic.txt", "synthetic guard fixture\n")
    git_executable = shutil.which("git")
    assert git_executable is not None
    for args in (["init", "-q"], ["add", "-f", rel]):
        subprocess.run(  # noqa: S603
            [git_executable, *args], cwd=tmp_path, check=True, capture_output=True
        )
    assert rel in guard.tracked_files()
    assert guard.blocked_paths(guard.tracked_files()) == [rel]


@pytest.mark.story("EN-2")
def test_missing_hook_fails_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "tracked_files", lambda: [])
    monkeypatch.setattr(sys, "argv", ["guard.py"])
    assert guard.main() == 1
    assert "pre-commit is missing" in capsys.readouterr().err
