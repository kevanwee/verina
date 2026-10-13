"""Exercise the real pre-commit guard in isolated synthetic Git repositories."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".githooks" / "pre-commit"


def _shell() -> str:
    # Git for Windows includes the POSIX shell needed by the project's hook.
    if sys.platform == "win32":
        shell = Path("C:/Program Files/Git/bin/sh.exe")
        assert shell.is_file(), "Git for Windows POSIX shell is required"
        return str(shell)
    shell_path = shutil.which("sh")
    assert shell_path is not None
    return shell_path


def _run_hook(tmp_path: Path, rel: str, content: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    assert git is not None
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    for args in (["init", "-q"], ["add", "--", rel]):
        subprocess.run(  # noqa: S603
            [git, *args], cwd=tmp_path, check=True, capture_output=True
        )
    return subprocess.run(  # noqa: S603
        [_shell(), str(HOOK)], cwd=tmp_path, check=False, capture_output=True, text=True
    )


@pytest.mark.story("EN-2")
@pytest.mark.parametrize(
    "rel",
    [
        "Private/synthetic.txt",
        "private/.env.example",
        "samples-real/.ENV.EXAMPLE",
        "config/production.ENV",
        "keys/signing.PEM",
        "keys/client.p12",
        "keys/client.PFX",
        "home/id_ed25519",
    ],
)
def test_hook_blocks_secret_and_confidential_paths(tmp_path: Path, rel: str) -> None:
    result = _run_hook(tmp_path, rel, "synthetic fixture\n")
    assert result.returncode == 1
    assert "confidential or secret files" in result.stderr


@pytest.mark.story("EN-2")
@pytest.mark.parametrize("rel", [".env.example", "apps/api/.ENV.EXAMPLE", "docs/private/ok.md"])
def test_hook_allows_non_confidential_examples(tmp_path: Path, rel: str) -> None:
    result = _run_hook(tmp_path, rel, "synthetic fixture\n")
    assert result.returncode == 0, result.stderr


@pytest.mark.story("EN-2")
def test_hook_blocks_secret_shaped_added_content(tmp_path: Path) -> None:
    # Assemble a synthetic canary to avoid placing a secret-shaped literal in the repo.
    content = "sk-ant-" + "synthetic" * 4
    result = _run_hook(tmp_path, "example.txt", content)
    assert result.returncode == 1
    assert "possible secret" in result.stderr
