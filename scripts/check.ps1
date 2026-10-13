# Verina local CI equivalent for Windows PowerShell 5.1+ / PowerShell 7 (EN-2).
# Mirrors .github/workflows/ci.yml: guard, api, web, security. Same steps as scripts/check.sh.
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1            # all checks
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Install   # npm ci + pip install first
# Optional tools: gitleaks and semgrep are used if on PATH (or $env:SEMGREP = path to semgrep.exe);
# otherwise they are skipped with a message. CI always runs both.
[CmdletBinding()]
param([switch]$Install)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Api = Join-Path $Root 'apps\api'

$env:IMPECCABLE_HOOK_DISABLED = '1'
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:PYTHONUTF8 = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'

$Py = Join-Path $Api '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) { $Py = Join-Path $Api '.venv/bin/python' }
if (-not (Test-Path $Py)) {
    Write-Host 'No API venv. Create it: cd apps/api; python -m venv .venv; .venv\Scripts\python -m pip install -e ".[dev]"'
    exit 2
}

$Failed = New-Object System.Collections.Generic.List[string]
$Skipped = New-Object System.Collections.Generic.List[string]
$Informational = New-Object System.Collections.Generic.List[string]

function Invoke-Step {
    param([string]$Name, [string]$Dir, [scriptblock]$Block)
    Write-Host ''
    Write-Host "==> $Name"
    Push-Location $Dir
    try {
        $ok = $true
        $global:LASTEXITCODE = 0
        & $Block
        if ($LASTEXITCODE -ne 0) { $ok = $false }
    } catch {
        Write-Host $_
        $ok = $false
    } finally {
        Pop-Location
    }
    if ($ok) { Write-Host "    ok: $Name" } else { Write-Host "    FAIL: $Name"; $Failed.Add($Name) }
}

# Runs native commands in sequence and stops at the first non-zero exit code.
function Invoke-All {
    param([scriptblock[]]$Commands)
    foreach ($c in $Commands) {
        & $c
        if ($LASTEXITCODE -ne 0) { return }
    }
}

function Skip-Step {
    param([string]$Name, [string]$Reason)
    Write-Host ''
    Write-Host "==> $Name"
    Write-Host "    SKIP: $Reason"
    $Skipped.Add("$Name ($Reason)")
}

# ---- guard -------------------------------------------------------------------------------
Invoke-Step 'guard' $Root { & $Py scripts\guard.py }

# ---- api ---------------------------------------------------------------------------------
if ($Install) { Invoke-Step 'api: install' $Api { & $Py -m pip install -q -e '.[dev]' } }
Invoke-Step 'api: ruff check' $Api { Invoke-All @(
        { & $Py -m ruff check . },
        { & $Py -m ruff check --config pyproject.toml ..\..\scripts }) }
Invoke-Step 'api: ruff format' $Api { Invoke-All @(
        { & $Py -m ruff format --check . },
        { & $Py -m ruff format --config pyproject.toml --check ..\..\scripts }) }
Invoke-Step 'api: mypy' $Api { & $Py -m mypy }
Invoke-Step 'api: pytest + coverage >= 85%' $Api { & $Py -m pytest -q --cov --cov-report=term-missing }

# ---- web ---------------------------------------------------------------------------------
if ($Install) { Invoke-Step 'web: npm ci' $Root { npm ci } }
Invoke-Step 'web: lint' $Root { npm run --silent lint:web }
Invoke-Step 'web: typecheck' $Root { npm run --silent typecheck:web }
Invoke-Step 'web: test' $Root { npm run --silent test:web }
Invoke-Step 'web: build' $Root { npm run --silent build:web }

# ---- security ----------------------------------------------------------------------------
$gitleaks = Get-Command gitleaks -ErrorAction SilentlyContinue
if ($gitleaks) {
    git -C $Root rev-parse --verify -q HEAD *> $null
    if ($LASTEXITCODE -eq 0) {
        Invoke-Step 'security: gitleaks (history)' $Root {
            & $gitleaks.Source git --config .gitleaks.toml --redact --no-banner .
        }
    } else {
        Skip-Step 'security: gitleaks' 'no commits yet; pre-commit hook covers staged files'
    }
} else {
    Skip-Step 'security: gitleaks' 'gitleaks not on PATH (install: https://github.com/gitleaks/gitleaks/releases; CI runs it)'
}
Invoke-Step 'security: npm audit (prod, high+)' $Root { npm audit --audit-level=high --omit=dev }
Push-Location $Root
try {
    npm audit --audit-level=high
    if ($LASTEXITCODE -ne 0) {
        $Informational.Add('full npm audit returned non-zero; inspect output (High findings block release)')
    }
} finally { Pop-Location }
Invoke-Step 'security: pip-audit' $Api { & $Py -m pip_audit --skip-editable --progress-spinner off }
Invoke-Step 'security: bandit' $Api { & $Py -m bandit -q -c pyproject.toml -r src }

$semgrep = $env:SEMGREP
if (-not $semgrep) {
    $cmd = Get-Command semgrep -ErrorAction SilentlyContinue
    if ($cmd) { $semgrep = $cmd.Source }
}
if ($semgrep) {
    Invoke-Step 'security: semgrep' $Root {
        & $semgrep scan --config .semgrep/ --error --metrics=off --quiet --exclude node_modules --exclude .venv .
    }
} else {
    Skip-Step 'security: semgrep' 'semgrep not on PATH (pip install semgrep in a separate venv, or set $env:SEMGREP; CI runs it)'
}

# ---- summary -----------------------------------------------------------------------------
Write-Host ''
Write-Host '==== summary ===='
foreach ($s in $Skipped) { Write-Host "skipped: $s" }
foreach ($i in $Informational) { Write-Host "informational: $i" }
if ($Failed.Count -gt 0) {
    foreach ($f in $Failed) { Write-Host "FAILED: $f" }
    exit 1
}
Write-Host 'All checks passed.'
exit 0
