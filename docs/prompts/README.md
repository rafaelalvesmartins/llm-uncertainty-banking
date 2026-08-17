# lub/docs/prompts/ — Reusable LLM Prompts (lub-facing)

**Purpose:** copy-paste prompts that live inside the public `llm-uncertainty-banking` repo. These are the prompts a **contributor or downstream user** might run — not the petition-scoping prompts. They mirror (but are not identical to) the operator-side prompts in `06_Projeto_GitHub/docs/prompts/`.

**Relationship to other prompt locations:**
- **Petition-scoping mirror** → `09_Projeto_GitHub/docs/prompts/` (repo tree) — README explaining how the three prompt locations relate.
- **Build prompts (scaffold lub itself)** → `planning/10_LLM_Build_Prompts.md` (repo tree).
- **Operator-side per-repo sweep prompt** → `scripts/competitor_review_prompt.md` (repo tree).
- **Operator-side whole-landscape sweep prompt** → `market_research/prompt_competitive_gap_analysis.md` (repo tree).

---

## Files

| File | Status | What it does |
|---|---|---|
| [`competitor_review.md`](competitor_review.md) | **LIVE-TEMPLATE** | Single-repo competitor review prompt — drops a `{{REPO_URL}}` placeholder, produces a structured feature-gap report. |
| [`prompt1_uq_calibration_CORRECTED.md`](prompt1_uq_calibration_CORRECTED.md) | **LIVE-TEMPLATE** | UQ + calibration landscape scan (the "corrected" version that replaced an earlier draft). Use this for the calibration-tool landscape specifically. |
| [`open_ended_improvement_sweep.md`](open_ended_improvement_sweep.md) | **LIVE-TEMPLATE** | Open-ended improvement prompt — "what could lub do better / what am I missing?" Produces exploratory suggestions rather than a scorecard. |
| [`market_research_prompt.md`](market_research_prompt.md) | **LIVE-TEMPLATE** | 7-area market-intelligence prompt (mirror of the one in `06_Projeto_GitHub/docs/prompts/`). Run for full market snapshot. |

---

## How to use

1. Open a fresh LLM chat with web-search enabled (Claude / ChatGPT / Perplexity).
2. Paste the target prompt verbatim; replace any `{{PLACEHOLDER}}` with a real value.
3. Save the output to the corresponding landing folder:
   - Single-repo review → `../../../market_research/13b_Sweep_<ProjectName>.md`
   - UQ/calibration scan → `../../../market_research/13b_Sweep_UQ_Calibration_2026-04-15.md` (or a fresh dated copy if re-running)
   - Open-ended sweep → `../../../market_research/13c_Sweep_OpenEnded_<YYYY-MM-DD>.md`
   - Market research → `../../../market_research/14b_Market_Research_<YYYY-MM-DD>.md`
4. Cite source URLs in the output. Unsourced claims do not feed into the petition narrative.

---

## Why two copies of `market_research_prompt.md`?

Intentional. The `06_Projeto_GitHub/docs/prompts/` copy is the **operator-facing** reference (the copy the petition workflow uses). This lub-facing copy travels with the public repo so external contributors and users can run the same research without cloning the petition workspace. Keep them in sync — when one is updated, update the other.
