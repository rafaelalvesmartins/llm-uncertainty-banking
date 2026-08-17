# Folder Organization Plan — `eb2niw` Workspace

> **Date:** 2026-06-15 · **Approved scope:** everything (code repo + `09_Projeto_GitHub/` + NIW root).
> **Nature:** a plan for review. Nothing moves until you approve the slice.
> **Golden rule:** this reorganizes *loose files* into existing homes. It does NOT restructure
> code or the petition system.

---

## 0. Principles (non-negotiable)

1. **Always `git mv`** — preserves history. Never a raw `mv`.
2. **One slice at a time → verify → commit.** No big-bang. Each slice is an isolated, reversible commit.
3. **On your machine, not the sandbox.** The mount's git is unsafe and it truncates edited files.
   Folder moves must run where git sees the real files.
4. **Gate after each slice:** `bash 09_Projeto_GitHub/scripts/check_truncation.sh --threshold 5`
   + (for code-adjacent slices) the gates from `VERIFICATION_HANDOFF.md`. If something shrank/broke, `git reset` the slice.
5. **I generate the `git mv` scripts (dry-run); you review and run.** I don't move anything blind.

---

## 1. UNTOUCHABLE (stays exactly where it is)

| Item | Why |
|---|---|
| `eb2niw/00_Meta/` … `16_PP/` | The numbered petition system — already organized by design. |
| `…/llm-uncertainty-banking/src/`, `bridge-ui/backend|frontend/` | Moving modules breaks imports; the full suite can't be verified here (torch). |
| `09_Projeto_GitHub/scripts/check_truncation.{sh,ps1}` · `TRUNCATION_POSTMORTEM.md` · `.githooks/` | The `truncation-check` workflow references them **by path**. Moving breaks CI. If ever moved, update the workflow path in the SAME commit. |
| `bridge-ui.yml`/`ci.yml` paths (root `.github/workflows/`) | Just fixed to monorepo-relative. Any move under `bridge-ui/` must keep them in sync (none planned). |
| Standard repo files at the code root | `README.md`, `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CITATION.cff`, `CHANGELOG.md`, `pyproject.toml`, `Dockerfile`, `mkdocs.yml`, dotfiles. Convention: stay at root. |

---

## 2. Slice 1 — Code repo (LOW risk, start here)

**Where:** `09_Projeto_GitHub/llm-uncertainty-banking/` (root has 27 loose files; `docs/` already exists).

Move into `docs/` subfolders:

| Loose file | → destination |
|---|---|
| `CI_REPORT_2026-04-22.md`, `CI_RESULTS_2026-04-22_FINAL.txt`, `INTEGRATION_TEST_RESULTS_2026-04-22.txt` | `docs/ci/` |
| `DESIGN_DECISIONS.md`, `DESIGN_DECISIONS_OUTLINE.md`, `DESIGN_DECISIONS_PERSONALIZATION_WORKSHEET.md`, `COMMIT_PLAN_2026-04-26.md` | `docs/design/` |
| `CODE_HEALTH_SCAN_PROMPT.md`, `PROJECT_VALIDATION_BRIEF.md` | `docs/reviews/` |
| `ARXIV_SUBMISSION_READY.txt` | `docs/arxiv/` |

**Investigate by hand (don't move blind):**
- `mkdocs_clean.yml` — looks like a duplicate of `mkdocs.yml`. `diff` it; delete one only after confirming.
- `.coverage` — a generated artifact; should be `.gitignore`d, not tracked. Confirm + `git rm --cached`.
- `llm-uncertainty-banking/` nested **inside** itself — suspicious (accidental copy?). Investigate first.
- A blank/1-byte-named file at the root — likely junk; confirm + remove.

---

## 3. Slice 2 — `09_Projeto_GitHub/` (LOW risk)

**Where:** ~30 loose dated reports mixed with content directories.

| Pattern | → destination |
|---|---|
| `AUDIT_2026-04-25.md`, `CHANGES_2026-04-25/26.md`, `CODE_ORGANIZATION_REVIEW_*`, `DAY_SUMMARY_*`, `IMPROVEMENT_OPPORTUNITIES_*`, `PROJECT_REVIEW_*`, `RUFLO_*`, `TOOLING.md`, `COWORK_SANDBOX_NOTES_*`, `URGENT_*_disk_corruption.md` | `_reports/2026-04/` |
| `16_Filing_Day_Checklist.md`, `17_Press_Inquiry_OnePager.md`, `18_Weekly_Cadence.md`, `19_Recommender_Letter_Packet.md`, `COUNSEL_REVIEW_CHECKLIST_*`, `WHAT_RAFAEL_NEEDS_TO_DO.md` | `_petition_ops/` |

**STAYS in place:** `scripts/check_truncation.{sh,ps1}`, `TRUNCATION_POSTMORTEM.md`, `.githooks/` (see §1).

---

## 4. Slice 3 — `eb2niw` root / NIW workspace (SENSITIVE — approve item by item)

**Rule:** these are personal/legal documents. I only **propose**; you approve each file.
Petition PDFs I do **not** move without explicit per-file OK.

| Pattern | → proposed destination |
|---|---|
| `QUESTIONS_FOR_COUNSEL_*.md` (8 dated) + `QUESTIONS_FOR_COUNSEL.md` | `_counsel/` |
| `HEALTH_LOG.md`, `HEALTH_LATEST.md`, `ALERT.md`, `ALERTS.md`, `DAILY_DIGEST.md`, `PIPELINE_HEALTH_REPORT.md` | `_ops_logs/` |
| `AUDIT_LUB_PETITION_CLAIMS_*`, `PETITION_FLEET_ANALYSIS_*`, `BRIDGE_GOVERNANCE_POSITIONING_*`, `PROJECT_ANALYSIS.md`, `PROJECT_BRIEFING_FOR_LLM.md`, `FILING_READINESS.md`, `DATA_GOVERNANCE.md`, `TEST_REPORT.md`, `LINTER_REPORT.md`, `RAFAEL_TODO.md` | `_reports/` |
| `1065_zeroed.pdf`, `k1_partner1_zeroed.pdf`, `k1_partner2_josiane.pdf` | **Probably** `01_Documentos_Pessoais/` — but personal PDFs; **only with your per-file OK.** |

**STAYS at root:** `README.md`, `CLAUDE.md`, `CHANGELOG.md`, dotfiles.
**Consolidate (investigate first):** the several `_archive*` / `_Arquivo_Transicao` → one `_archive/` with dated subfolders; `eb2NIW/` vs `eb2niw/` nested (same name, different case).

---

## 5. Execution protocol (per slice)

```
# 1. create the destination folder
git mv <file> <destination>/        # repeat per file in the slice
# 2. truncation gate (on your machine, real disk)
bash 09_Projeto_GitHub/scripts/check_truncation.sh --threshold 5
# 3. (slices 1–2, near code) run the VERIFICATION_HANDOFF gates
# 4. check: git status should show RENAMES (R), not loose deletions+additions
git status
# 5. isolated commit for the slice
git commit -m "chore(org): slice N — <description>"
```

Order: **Slice 1 → 2 → 3.** Start with 1 (safest). Stop and check `git status` (renames, not mass
deletions) before each commit.

---

## 6. What I do here × what's yours

- **Me (now, if you want):** generate the exact `git mv` scripts per slice
  (`reorg_fatia1/2/3.sh`, dry-run-friendly, with `mkdir -p` of the destinations) — you review line by line.
- **You (on your machine):** run the slice, run the truncation gate, check `git status`, commit. Repeat.
- **I do NOT** automate Slice 3 (personal/legal) end to end — it defaults to `--dry-run` and you uncomment what you approve.

---

## One-line summary

Consolidate loose files into homes that already exist (`docs/`, `_reports/`, `_counsel/`), in three
risk-ordered slices, with `git mv` + a truncation gate + a commit per slice — without touching the
numbered petition system, the code modules, or the files the CI references by path.
