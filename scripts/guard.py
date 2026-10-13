"""Repository guard (EN-2). Stdlib only; runs in CI and from scripts/check.(sh|ps1).

Fails (exit 1) when:
  1. a tracked (or untracked, not ignored) path is confidential or a secret file, matched
     case-insensitively: ``private/``, ``samples-real/``, ``.env`` / ``.env.*`` / ``*.env``
     (``.env.example`` allowed), ``*.pem``, ``*.key``, ``*.p12``, ``*.pfx``, ``id_rsa``-style keys;
  2. ``.githooks/pre-commit`` is missing;
  3. a model SDK is imported outside the orchestrator package
     ``apps/api/src/verina/ai/`` (threat ORC-1, control C-7.1).

Usage: python scripts/guard.py            (tracked + untracked-not-ignored files)
       python scripts/guard.py --paths-from FILE   (checks a newline-separated path list)
Self-test: apps/api/tests/test_guard.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Case-insensitive: Windows/macOS checkouts can produce "Private/" or ".ENV" that Linux CI tracks.
BLOCKED_PATH = re.compile(
    r"^private/|^samples-real/"
    r"|(^|/)\.env($|\.)|\.env$"  # .env, .env.local, config/production.env
    r"|\.(pem|key|p12|pfx)$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$",
    re.IGNORECASE,
)
ALLOWED_PATH = re.compile(r"(^|/)\.env\.example$", re.IGNORECASE)
CONFIDENTIAL_PATH = re.compile(r"^(private|samples-real)/", re.IGNORECASE)

ORCHESTRATOR_PREFIX = "apps/api/src/verina/ai/"
# The guard and its self-test contain SDK import strings as test data, not as imports.
SDK_CHECK_EXEMPT = frozenset({"scripts/guard.py", "apps/api/tests/test_guard.py"})
_PY_SDKS = (
    r"anthropic|openai|google\.genai|google\.generativeai|vertexai|mistralai|cohere|litellm"
    r"|langchain\w*"
)
PY_MODEL_SDK = re.compile(
    # import x | from x import y | import os, x | import_module("x") | __import__("x")
    rf"^\s*(?:from\s+(?:{_PY_SDKS})\b|import\s+(?:[\w.]+\s*(?:as\s+\w+\s*)?,\s*)*(?:{_PY_SDKS})\b)"
    rf"|(?:import_module|__import__)\(\s*['\"](?:{_PY_SDKS})\b",
    re.MULTILINE,
)
_JS_SDKS = r"@anthropic-ai/[^'\"]+|openai|@google/genai|@google/generative-ai|@ai-sdk/[^'\"]+|ai"
JS_MODEL_SDK = re.compile(
    # from "x", from "x/sub", require("x"), import("x"), and side-effect import "x"
    rf"""(?:from\s+|require\(\s*|import\(\s*|^\s*import\s+)['"](?:{_JS_SDKS})(?:/[^'"]*)?['"]""",
    re.MULTILINE,
)
JS_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}


def tracked_files() -> list[str]:
    # git on PATH is a CI/dev precondition; arguments are constant (no shell).
    cmd = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    out = subprocess.run(  # noqa: S603
        cmd,
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in out.split("\0") if p]


def blocked_paths(paths: list[str]) -> list[str]:
    return [
        p
        for p in paths
        if CONFIDENTIAL_PATH.search(p) or (BLOCKED_PATH.search(p) and not ALLOWED_PATH.search(p))
    ]


def model_sdk_violations(paths: list[str], root: Path = ROOT) -> list[str]:
    hits: list[str] = []
    for rel in paths:
        if rel.startswith(ORCHESTRATOR_PREFIX) or rel in SDK_CHECK_EXEMPT or "node_modules/" in rel:
            continue
        suffix = Path(rel).suffix
        if suffix == ".py":
            pattern = PY_MODEL_SDK
        elif suffix in JS_SUFFIXES:
            pattern = JS_MODEL_SDK
        else:
            continue
        file = root / rel
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            hits.append(rel)
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths-from", type=Path, help="newline-separated path list")
    args = parser.parse_args()

    if args.paths_from:
        paths = [ln.strip() for ln in args.paths_from.read_text("utf-8").splitlines() if ln.strip()]
    else:
        paths = tracked_files()

    failed = False

    bad = blocked_paths(paths)
    if bad:
        failed = True
        print("guard: confidential or secret files are tracked (or not ignored):", file=sys.stderr)
        for p in bad:
            print(f"  {p}", file=sys.stderr)

    if not (ROOT / ".githooks" / "pre-commit").is_file():
        failed = True
        print("guard: .githooks/pre-commit is missing.", file=sys.stderr)

    sdk = model_sdk_violations(paths)
    if sdk:
        failed = True
        print(
            f"guard: model SDK imported outside {ORCHESTRATOR_PREFIX} (ORC-1):",
            file=sys.stderr,
        )
        for p in sdk:
            print(f"  {p}", file=sys.stderr)

    if failed:
        return 1
    print(f"guard: OK ({len(paths)} paths checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
