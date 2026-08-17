# Bridge — scheduled jobs (cron)

The Bridge backend has **no in-process scheduler by design**. For a model-risk
platform, recurring jobs belong in the orchestration layer (Task Scheduler, k8s
CronJob, CI cron) where they are observable, independently auditable, and cannot
stall the request server. The backend instead exposes **idempotent endpoints**
that an external scheduler calls on a cadence.

`bridge-cron.ps1` is that caller: it archives evidence + checks integrity and
**exits non-zero** on any failure or a broken at-rest chain, so the scheduler can
alert.

## What it does each run

| Job | Endpoint | Why | Suggested cadence |
|---|---|---|---|
| Audit archive (JSON+CSV) | `GET /audit/export?source=disk` | BCB 4893 5-year retention | nightly |
| Evidence package | `GET /evidence/package` | signed SR 11-7 model-risk snapshot | weekly |
| Vulnerability scan | `GET /security/vulnerability-scan?refresh=1` | re-prove defenses hold | weekly |
| Effective-challenge battery | `GET /experiments/run?refresh=1` | ongoing monitoring | weekly |
| Calibration | `GET /calibration` | confidence-honesty snapshot | weekly |
| At-rest integrity | `GET /audit/verify?source=disk` | detect out-of-band tamper → **alert** | hourly |

Output lands in `<OutDir>/<yyyy-MM-dd>/` with a timestamp per file.

## Run it manually

```powershell
pwsh ./bridge-cron.ps1 -Base http://localhost:8000 -OutDir D:\bridge-archive
# or through the Next BFF proxy:
pwsh ./bridge-cron.ps1 -Base http://localhost:3002/api
```

## Register with Windows Task Scheduler

Nightly archive at 02:00 (exit code surfaces failures to the Task Scheduler "Last
Run Result"):

```powershell
$action  = New-ScheduledTaskAction -Execute "pwsh.exe" `
  -Argument "-NoProfile -File `"$PWD\bridge-cron.ps1`" -Base http://localhost:8000 -OutDir D:\bridge-archive"
$trigger = New-ScheduledTaskTrigger -Daily -At 2:00am
Register-ScheduledTask -TaskName "Bridge nightly evidence" -Action $action -Trigger $trigger
```

For the **hourly integrity check** only, point a second task at the same script
(or make a trimmed copy that runs just the `audit/verify?source=disk` block) with
`New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)`.

## k8s CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata: { name: bridge-nightly-evidence }
spec:
  schedule: "0 2 * * *"          # nightly 02:00
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: cron
              image: mcr.microsoft.com/powershell:latest
              args: ["pwsh","/scripts/bridge-cron.ps1","-Base","http://bridge-backend:8000","-OutDir","/archive"]
              volumeMounts:
                - { name: archive, mountPath: /archive }
                - { name: scripts, mountPath: /scripts }
          volumes:
            - { name: archive, persistentVolumeClaim: { claimName: bridge-archive } }
            - { name: scripts, configMap: { name: bridge-cron-script } }
```

## GitHub Actions (cron)

```yaml
on:
  schedule:
    - cron: "0 2 * * *"          # nightly 02:00 UTC
jobs:
  evidence:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - shell: pwsh
        run: ./bridge-ui/scripts/scheduled/bridge-cron.ps1 -Base ${{ secrets.BRIDGE_URL }} -OutDir ./archive
      - uses: actions/upload-artifact@v4
        with: { name: bridge-evidence, path: ./archive }
```

## In-app schedulers that already exist (partial)

- **Visibility collection** — a real time-based scheduler, but **env-only and off
  by default**: set `VISIBILITY_SCHEDULE_EVERY_S=<seconds>` before starting the
  backend. There is no runtime UI to change it.
- **Drift auto-rebaseline** — rolls the baseline **every N queries** (a count
  trigger, not a clock), configurable from the Observability › Operations panel.

Everything else (audit export, evidence, vuln-scan, experiments, calibration,
integrity verify) is on-demand only — which is exactly what this external cron
covers.
