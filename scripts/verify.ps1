# verify.ps1 — run ALL bridge-ui gates and summarize PASS/FAIL (native Windows).
# Prerequisites (once):
#   cd 09_Projeto_GitHub\llm-uncertainty-banking
#   pip install -e ".[dev]" ; pip install -r bridge-ui\backend\requirements.txt
#   cd bridge-ui\frontend ; npm ci
# Usage:  .\scripts\verify.ps1 [-Frontend] [-Backend] [-Quick]
param([switch]$Frontend, [switch]$Backend, [switch]$Quick)

# Deterministic gates: force the fake backend + an in-memory audit DB (this machine
# may have Ollama; _select_backend() would pick the real LLM at import). Override by
# exporting either var before running.
if (-not $env:BRIDGE_USE_REAL_LLM) { $env:BRIDGE_USE_REAL_LLM = 'off' }
if (-not $env:BRIDGE_AUDIT_DB)     { $env:BRIDGE_AUDIT_DB     = ':memory:' }

$Repo = Split-Path -Parent $PSScriptRoot           # scripts\ -> code repo root
$FE   = Join-Path $Repo 'bridge-ui\frontend'
$BE   = Join-Path $Repo 'bridge-ui\backend'
$script:Pass = @(); $script:Fail = @()

function Gate([string]$name, [scriptblock]$block) {
  Write-Host "`n=== $name ==="
  & $block
  if ($LASTEXITCODE -eq 0) { Write-Host "OK  $name"; $script:Pass += $name }
  else                     { Write-Host "X   $name"; $script:Fail += $name }
}

if (-not $Backend) {
  Gate 'frontend - lint'  { Push-Location $FE; npm run lint;       Pop-Location }
  Gate 'frontend - tsc'   { Push-Location $FE; npx tsc --noEmit;   Pop-Location }
  if (-not $Quick) { Gate 'frontend - build' { Push-Location $FE; npm run build; Pop-Location } }
}
if (-not $Frontend) {
  Gate 'backend - ruff'         { Push-Location $BE; ruff check .; Pop-Location }
  Gate 'backend - mypy'         { Push-Location $BE; mypy .;       Pop-Location }
  Gate 'backend - lint-imports' { Push-Location (Join-Path $Repo 'bridge-ui'); python -c "import sys;from importlinter.cli import lint_imports;sys.exit(lint_imports(config_filename='backend/pyproject.toml'))"; Pop-Location }
  Gate 'backend - pytest'       { Push-Location $BE; pytest -q;    Pop-Location }
}

# Truncation gate (walks up to the git root).
$GitRoot = (git -C $Repo rev-parse --show-toplevel 2>$null)
$TruncPs = Join-Path $GitRoot '09_Projeto_GitHub\scripts\check_truncation.ps1'
$TruncSh = Join-Path $GitRoot '09_Projeto_GitHub\scripts\check_truncation.sh'
if (Test-Path $TruncPs)     { Gate 'truncation guard' { & $TruncPs -Threshold 5 } }
elseif (Test-Path $TruncSh) { Gate 'truncation guard' { bash $TruncSh --threshold 5 } }

Write-Host "`n-------- SUMMARY --------"
Write-Host ("PASS: {0}   FAIL: {1}" -f $script:Pass.Count, $script:Fail.Count)
if ($script:Fail.Count -gt 0) { $script:Fail | ForEach-Object { Write-Host "  X $_" }; Write-Host "A GATE FAILED."; exit 1 }
Write-Host "all green OK"
