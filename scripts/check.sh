#!/usr/bin/env bash
# Verina local CI equivalent (EN-2). Mirrors .github/workflows/ci.yml: guard, api, web, security.
# Works in Git Bash on Windows, macOS and Linux. Run from anywhere:
#   scripts/check.sh            # all checks, using existing node_modules and apps/api/.venv
#   scripts/check.sh --install  # first run `npm ci` and `pip install -e .[dev]` (as CI does)
# Optional tools: gitleaks and semgrep are used if on PATH (or SEMGREP=/path/to/semgrep);
# otherwise they are skipped with a message. CI always runs both.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --install) INSTALL=1 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

export IMPECCABLE_HOOK_DISABLED=1 NEXT_TELEMETRY_DISABLED=1 PYTHONUTF8=1 PIP_DISABLE_PIP_VERSION_CHECK=1

if [ -x "$API/.venv/Scripts/python.exe" ]; then PY="$API/.venv/Scripts/python.exe"
elif [ -x "$API/.venv/bin/python" ]; then PY="$API/.venv/bin/python"
else
  echo "No API venv. Create it: cd apps/api && python -m venv .venv && <venv python> -m pip install -e \".[dev]\"" >&2
  exit 2
fi

FAILED=()
SKIPPED=()
INFORMATIONAL=()
step() { # step <name> <command...>
  local name="$1"; shift
  printf '\n==> %s\n' "$name"
  if "$@"; then printf '    ok: %s\n' "$name"; else printf '    FAIL: %s\n' "$name"; FAILED+=("$name"); fi
}
skip() { printf '\n==> %s\n    SKIP: %s\n' "$1" "$2"; SKIPPED+=("$1 ($2)"); }

# ---- guard -------------------------------------------------------------------------------
step "guard" "$PY" "$ROOT/scripts/guard.py"

# ---- api ---------------------------------------------------------------------------------
if [ "$INSTALL" = 1 ]; then step "api: install" bash -c "cd '$API' && '$PY' -m pip install -q -e '.[dev]'"; fi
step "api: ruff check"   bash -c "cd '$API' && '$PY' -m ruff check . && '$PY' -m ruff check --config pyproject.toml ../../scripts"
step "api: ruff format"  bash -c "cd '$API' && '$PY' -m ruff format --check . && '$PY' -m ruff format --config pyproject.toml --check ../../scripts"
step "api: mypy"         bash -c "cd '$API' && '$PY' -m mypy"
step "api: pytest + coverage >= 85%" bash -c "cd '$API' && '$PY' -m pytest -q --cov --cov-report=term-missing"

# ---- web ---------------------------------------------------------------------------------
cd "$ROOT" || exit 2
if [ "$INSTALL" = 1 ]; then step "web: npm ci" npm ci; fi
step "web: lint"      npm run --silent lint:web
step "web: typecheck" npm run --silent typecheck:web
step "web: test"      npm run --silent test:web
step "web: build"     npm run --silent build:web

# ---- security ----------------------------------------------------------------------------
if command -v gitleaks >/dev/null 2>&1; then
  if git -C "$ROOT" rev-parse --verify -q HEAD >/dev/null; then
    step "security: gitleaks (history)" gitleaks git --config "$ROOT/.gitleaks.toml" --redact --no-banner "$ROOT"
  else
    skip "security: gitleaks" "no commits yet; pre-commit hook covers staged files"
  fi
else
  skip "security: gitleaks" "gitleaks not on PATH (install: https://github.com/gitleaks/gitleaks/releases; CI runs it)"
fi
step "security: npm audit (prod, high+)" npm audit --audit-level=high --omit=dev
if ! npm audit --audit-level=high; then
  INFORMATIONAL+=("full npm audit returned non-zero; inspect output (High findings block release)")
fi
step "security: pip-audit"  bash -c "cd '$API' && '$PY' -m pip_audit --skip-editable --progress-spinner off"
step "security: bandit"     bash -c "cd '$API' && '$PY' -m bandit -q -c pyproject.toml -r src"
SEMGREP="${SEMGREP:-$(command -v semgrep || true)}"
if [ -n "$SEMGREP" ]; then
  step "security: semgrep" "$SEMGREP" scan --config "$ROOT/.semgrep/" --error --metrics=off --quiet \
    --exclude node_modules --exclude .venv "$ROOT"
else
  skip "security: semgrep" "semgrep not on PATH (pip install semgrep in a separate venv, or set SEMGREP=; CI runs it)"
fi

# ---- summary -----------------------------------------------------------------------------
printf '\n==== summary ====\n'
for s in "${SKIPPED[@]+"${SKIPPED[@]}"}"; do printf 'skipped: %s\n' "$s"; done
for i in "${INFORMATIONAL[@]+"${INFORMATIONAL[@]}"}"; do printf 'informational: %s\n' "$i"; done
if [ "${#FAILED[@]}" -gt 0 ]; then
  for f in "${FAILED[@]}"; do printf 'FAILED: %s\n' "$f"; done
  exit 1
fi
echo "All checks passed."
