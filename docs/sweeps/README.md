# lub/docs/sweeps/ — In-Repo Mirror of Competitive Sweeps

**Purpose:** selected competitive-sweep outputs that travel with the public `llm-uncertainty-banking` repo so external readers (arXiv reviewers, OSS maintainers, downstream users) can see the adjacent-project survey without cloning the petition workspace.

**Relationship to other locations:**
- **Operator-side canonical** → `market_research/` (repo tree) — all dated sweeps land here first with their raw URLs, LLM prompts used, and provenance. That folder is the single source of truth; files here are deliberately narrower mirrors.
- **Petition-facing merge** → `petition_evidence/17_EB2_NIW_Market_Evidence.md` (repo tree) — formatted market evidence for USCIS.
- **lub-facing canonical** → [`../MARKET_RESEARCH.md`](../MARKET_RESEARCH.md) — merged live competitor matrix.
- **Quarterly refresh prompts** → [`../prompts/`](../prompts/) and `market_research/prompt_competitive_gap_analysis.md` (repo tree).

---

## Files

| File | Status | What it tells you |
|---|---|---|
| [`13b_Sweep_UQ_Calibration.md`](13b_Sweep_UQ_Calibration.md) | **DATED** (2026-04-16) | Deep-dive sweep of three adjacent UQ/calibration projects (LM-Polygraph, Uncertainty Toolbox, ConformalLLM). Identifies L2/L3 methods `lub` lacks, estimated lines of code per method, and compatibility with Apache-2.0. Mirror of `../../../market_research/13b_Sweep_UQ_Calibration.md`. |

---

## Why mirror sweeps into the public repo at all?

The arXiv reviewer or OSS maintainer asking "what about LM-Polygraph / Uncertainty Toolbox?" should be able to find the answer inside the repo they're already reading. Cloning the petition workspace to find the answer is friction they won't pay. So sweeps that are *technical, narrow, and answer a specific "what about X?" question* live here; sweeps that are *market-facing (pricing, MRM spend, hiring signals)* stay operator-only in `market_research/`.

## Mirror discipline

- **Add here only sweeps that answer a technical-reader question** ("did you consider X?" "why not port Y from Z?"). Do not mirror market-sizing or competitor-pricing sweeps.
- **Keep file names identical** to the operator-side canonical (`market_research/13X_*.md`) so cross-references from other docs resolve the same way regardless of clone context.
- **Never edit the mirror.** If the content changes, edit the operator-side copy and re-mirror. The mirror is a point-in-time freeze.
- **Date-stamped filenames.** Same rule as `market_research/` — every sweep file has `_YYYY-MM-DD` in the name or a dated header at the top.
- **License compatibility.** Every project reviewed must have its license noted (MIT/BSD/Apache = safe; GPL/AGPL = contamination risk; proprietary = no-go). No exceptions — it's the single fastest reviewer-objection to cover.
