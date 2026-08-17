# Code-Health Scan Prompt

Reusable prompt for periodic, read-only code-health scans of the
`llm-uncertainty-banking` repository. The scan never modifies code;
it produces a timestamped markdown report under
`reports/code_health/` so Rodrigo can review and act on findings.

This file is the **single source of truth** for the scan. The
scheduled-task version (Cowork scheduled tasks) is generated from
this prompt; if they drift, this file wins. Edit here, then update
the schedule via `mcp__scheduled-tasks__update_scheduled_task` (or
the Cowork UI).

---

## Prompt (paste this into a fresh Claude session, or it runs automatically via the schedule)

```
OBJECTIVE
=========

Perform a READ-ONLY code-health scan of the llm-uncertainty-banking
repository at:

    C:\code\eb2niw\06_Projeto_GitHub\llm-uncertainty-banking

Produce a timestamped markdown report listing concrete improvement
opportunities. DO NOT modify any code, regardless of what you find.
The user (Rodrigo) reviews the report and decides what to act on.

CONTEXT
=======

- Python 3.11+ uncertainty-quantification library for LLMs in regulated banking.
- Layered architecture: lub.wrappers (L1) -> lub.uncertainty (L2) ->
  lub.calibration (L3) -> lub.benchmarks (L4) -> lub.reports (L5).
  Enforced by import-linter (4 contracts in pyproject.toml).
- Architectural reference: docs/architecture.md.
- The Windows + bash-mount development environment has a recurring
  disk-corruption issue that produces null bytes / truncated files.
  scripts/check_integrity.py detects this.
- Recent additions: lub.exceptions hierarchy (LubError + 7 subtypes),
  BackendCapability flag enum, lub.uncertainty._math_utils,
  lub._text_utils, lub.benchmarks._hf_local.HFLocalDataset,
  lub.ledger.LedgerSummary protocol method, retry tunables on
  lub.wrappers.api_base.

STEPS
=====

1) Disk integrity (gating step — must pass before anything else)

   Run from repo root:
       python scripts/check_integrity.py

   - Exit 0: continue.
   - Exit non-zero: STOP. Write a report with status "🔴 REPAIR
     NEEDED", list every flagged file, and skip steps 2–7. Do NOT
     attempt to repair.

2) AST sweep

   Walk every .py in src/lub/ and tests/. Confirm AST parse OK.
   Flag any file that fails. Note any file that imports Python 3.11+
   features that block running tests on a Python 3.10 sandbox
   (datetime.UTC, tomllib, typing.Self).

3) Architectural drift

   - Read docs/architecture.md.
   - List src/lub/*.py files NOT mentioned in the doc.
   - Verify the four import-linter contracts in pyproject.toml are
     present and intact.
   - Run "git log --since=\"24 hours ago\" --oneline" and list recent
     commits.

4) Code-smell + duplication scan

   Search for known anti-patterns:
   - Inline `entropy = -sum(p * math.log(p)` outside _math_utils.py
   - `.strip().lower()` on raw text outside _text_utils.py
   - `except Exception: pass` (silent failure)
   - Direct `_conn` access (encapsulation leak)
   - Bare `except BaseException` (masks Ctrl-C)
   - SQL via f-string / %-format / .format() / + concatenation in execute()
   - `from typing import` with names already on collections.abc
   - Functions/classes longer than 100 lines (rough complexity proxy)
   - `__all__` lists missing exported names (use ast to compare)
   - TODO / FIXME / XXX comments grouped by file

5) Backend capability + estimator coverage

   - Read every backend's CAPABILITIES in src/lub/wrappers/*.py.
   - Read every estimator's REQUIRES_CAPABILITIES in src/lub/uncertainty/*.py.
   - Flag (estimator, backend) pairs whose declarations are
     incompatible — the assertion would always fail at runtime.

6) Test coverage by subpackage

   For each subpackage in src/lub/, count source files vs.
   tests/unit/test_<modulename>.py files. Flag subpackages where the
   ratio is < 50% (e.g. agents/ 5 files but only 2 test files).

7) Recent activity quick-recheck

   Files modified in the last 24h (from step 3) get an extra pass:
   - Re-run check_integrity on each (defensive — corruption recurs)
   - Re-run AST parse
   - Confirm no new SQL-injection or capability-mismatch patterns

OUTPUT
======

Write a markdown report at:

    C:\code\eb2niw\06_Projeto_GitHub\llm-uncertainty-banking\reports\code_health\<YYYY-MM-DD>_<HHMM>.md

Create the parent directory if missing. Use local time for the filename.

Report shape (markdown):

    # Code Health Scan — <local timestamp>

    **Status:** <emoji> <STATUS>

    **Summary:** N P1, N P2, N P3 findings — see "Top 5 next moves" below.

    ---

    ## 1. Disk integrity
    ## 2. AST sweep + Python 3.11+ usage
    ## 3. Architectural drift
    ## 4. Code-smell + duplication
    ## 5. Backend capability + estimator coverage
    ## 6. Test coverage by subpackage
    ## 7. Recent-activity recheck (last 24h)

    Each finding is rendered as:

    - **<priority>** | `<path>:<line>` | <one-sentence problem> | <one-sentence fix>

    ## Top 5 next moves

    1. ...
    2. ...
    ...

    ---

    *Compared to previous report (<previous filename or "first run">):*
    - Same: ...
    - Resolved: ...
    - New: ...

STATUS LADDER
=============

- 🟢 OK             — no findings of any priority.
- 🟡 NICE           — only NICE / P3 findings, no urgency.
- 🟠 RECOMMENDED    — at least one P1 or P2 finding.
- 🔴 REPAIR NEEDED  — disk integrity failed (step 1).

PRIORITY SCALE
==============

- P1: blocks correctness or imports (AST fail, capability mismatch,
  SQL injection pattern). Fix today.
- P2: meaningful refactor opportunity (duplication, encapsulation
  leak, test gap on critical path). Fix this week.
- P3: polish (docstring inconsistency, magic number, extra import).
- NICE: cosmetic.

CONSTRAINTS
===========

- READ-ONLY. Never edit code. Never run pytest. Never commit. Never push.
- Total report ≤ 1500 words. Move long lists to a Details appendix.
- Do not invent findings. If a section has no findings, write
  "No findings.".
- If two consecutive reports have the same Top 5, append "(unchanged)"
  to the matching items so Rodrigo can see what's stuck.
- Final line of the report: a one-sentence executive summary suitable
  for a Slack notification.

FAILURE MODES
=============

- If you cannot read a file (permission / encoding), log it and
  continue with the rest of the scan; flag it under "Tool issues" at
  the end.
- If git is unavailable, skip step 3's git portion; flag it.
- If the repo has uncommitted changes, include a snapshot
  ("git status --short" output truncated to 30 lines) but do not
  commit.

SUCCESS CRITERIA
================

- Report file written to the expected path.
- Status header is one of the four ladder values.
- Top 5 next moves is populated (or "No improvements detected" only
  when status is 🟢 OK).
- Comparison-to-previous section is present when at least one prior
  report exists.
```

---

## How to use

**Manually (any session):** copy the prompt block above, paste into a
new Claude session.

**Automatically:** the matching scheduled task fires hourly. To change
frequency:

```python
# via the Cowork scheduled-tasks tool, or edit
# C:\Users\rodri\OneDrive\Documents\Claude\Scheduled\lub-code-health-scan\SKILL.md
```

Suggested cron alternatives:
- Every 4 hours during work hours: `0 9,13,17,21 * * *`
- Weekdays at 9 AM only: `0 9 * * 1-5`
- Once a day at 8 AM: `0 8 * * *`

**Reports accumulate at:**

```
C:\code\eb2niw\06_Projeto_GitHub\llm-uncertainty-banking\reports\code_health\
```

You can `git ignore` this directory if you don't want reports
committed (`reports/code_health/` in `.gitignore`).
