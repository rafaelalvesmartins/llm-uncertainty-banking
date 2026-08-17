<#
.SYNOPSIS
  Bridge scheduled maintenance / evidence jobs, run by an EXTERNAL scheduler.

.DESCRIPTION
  The Bridge backend has NO in-process scheduler by design (model-risk posture:
  recurring jobs live in the orchestration layer, not inside the request server,
  so they are observable and independently auditable). These endpoints are the
  cron-friendly surface — every call here is idempotent and read-only/recompute:

    - GET /audit/export?format=json|csv&source=disk   retention archive (BCB 4893)
    - GET /evidence/package                            signed model-risk snapshot
    - GET /security/vulnerability-scan?refresh=1       recompute defense battery
    - GET /experiments/run?refresh=1                   recompute challenge battery
    - GET /calibration                                 confidence-honesty snapshot
    - GET /audit/verify?source=disk                    at-rest integrity check

  The script archives each result under <OutDir>/<yyyy-MM-dd>/ and exits NON-ZERO
  if any fetch fails OR the at-rest audit chain is broken — so the scheduler (Task
  Scheduler / k8s / GitHub Actions) can alert on a non-zero exit.

.PARAMETER Base
  Backend base URL. Default http://localhost:8000. To go through the Next BFF use
  http://localhost:3002/api instead.

.PARAMETER OutDir
  Archive root. Default ./bridge-archive (created if missing).

.EXAMPLE
  pwsh ./bridge-cron.ps1 -Base http://localhost:8000 -OutDir D:\bridge-archive
#>
param(
  [string]$Base = "http://localhost:8000",
  [string]$OutDir = "./bridge-archive"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$day = Get-Date -Format "yyyy-MM-dd"
$dir = Join-Path $OutDir $day
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$failures = 0

function Save-Endpoint([string]$Name, [string]$Url, [string]$OutFile) {
  try {
    Invoke-WebRequest -Uri "$Base$Url" -OutFile (Join-Path $dir $OutFile) -TimeoutSec 180 | Out-Null
    Write-Host "[ok]  $Name -> $OutFile"
  } catch {
    Write-Host "[ERR] $Name : $($_.Exception.Message)"
    $script:failures++
  }
}

# 1. Audit retention archive (BCB 4893 5-year retention) — JSON + CSV, at-rest source.
Save-Endpoint "audit-export-json" "/audit/export?format=json&source=disk" "audit-$stamp.json"
Save-Endpoint "audit-export-csv"  "/audit/export?format=csv&source=disk"  "audit-$stamp.csv"

# 2. Evidence package snapshot (signed, hashed model-risk record).
Save-Endpoint "evidence-package" "/evidence/package" "evidence-$stamp.json"

# 3. Periodic re-validation (recompute + archive the content-hashed result).
Save-Endpoint "vulnerability-scan" "/security/vulnerability-scan?refresh=1" "vuln-scan-$stamp.json"
Save-Endpoint "experiments"        "/experiments/run?refresh=1"            "experiments-$stamp.json"
Save-Endpoint "calibration"        "/calibration"                          "calibration-$stamp.json"

# 4. At-rest integrity check — ALERT (non-zero exit) if the persisted chain is broken.
try {
  $verify = Invoke-RestMethod -Uri "$Base/audit/verify?source=disk" -TimeoutSec 180
  $verify | ConvertTo-Json -Depth 6 | Out-File -Encoding utf8 (Join-Path $dir "verify-$stamp.json")
  if ($verify.valid) {
    Write-Host "[ok]  audit-verify(disk): chain intact ($($verify.checked) entries)"
  } else {
    Write-Host "[ALERT] audit-verify(disk): CHAIN TAMPERED at seq $($verify.first_failure.seq) - $($verify.first_failure.reason)"
    $failures++
  }
} catch {
  Write-Host "[ERR] audit-verify(disk): $($_.Exception.Message)"
  $failures++
}

Write-Host ""
Write-Host "Bridge cron run $stamp -> $dir ; failures=$failures"
exit $failures
