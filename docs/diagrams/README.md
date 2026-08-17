# lub/docs/diagrams/ — Eraser.io Diagram Source Files

**Purpose:** `.md` files containing [Eraser.io](https://eraser.io) diagram DSL code. Paste into Eraser to render the diagram; export PNG/SVG for the tech report, MkDocs site, or pitch decks.

**Relationship to other folders:**
- **Rendered exports** → stored next to the consuming doc (e.g. tech report in `../tech-report/figures/`). Eraser sources live here; rendered outputs do not.
- **Consolidated diagram narrative** → [`../architecture.md`](../architecture.md) pulls several of these together into a single explanation. If the narrative conflicts with a source here, the source wins; update the narrative to match.
- **Top-level architecture doc (PP Ch.3 / tech-report §2)** → links to rendered versions of `architecture_eraser.md` + `data_flow_eraser.md`.

---

## Files

| File | Renders | Used in |
|---|---|---|
| [`architecture_eraser.md`](architecture_eraser.md) | 5-layer architecture overview (wrappers → uncertainty → calibration → benchmarks → reports) + governance runtime modules | README, tech report §2, Professional Plan Ch.3 |
| [`data_flow_eraser.md`](data_flow_eraser.md) | End-to-end request flow: user → CLI → backend → estimators → calibration → report | README, tech report §3 |
| [`estimator_selection_eraser.md`](estimator_selection_eraser.md) | Decision tree for picking an estimator based on backend + task + latency budget | tech report §4, tutorial docs |
| [`benchmark_pipeline_eraser.md`](benchmark_pipeline_eraser.md) | Dataset → runner → metrics → signed-JSON record pipeline | tech report §5 |
| [`reask_policy_flow_eraser.md`](reask_policy_flow_eraser.md) | Governance loop: estimator → threshold → PolicyDecision (ABSTAIN/FLAG/PASSTHROUGH/RAISE) → NIST AI RMF MANAGE sub-category | tech report §6, petition Prong-1 narrative |
| [`sr117_evidence_map_eraser.md`](sr117_evidence_map_eraser.md) | SR 11-7 validation requirement → lub module / test / artifact crosswalk | petition_evidence §SR 11-7 map |
| [`competitive_landscape_eraser.md`](competitive_landscape_eraser.md) | Competitor matrix: uncertainty tools × regulated-finance focus × NIST AI RMF reporting | market research §competitive, pitch decks |

---

## Rendering workflow

1. Open [eraser.io](https://eraser.io) → New Diagram → Code tab.
2. Copy the entire contents of the target `.md` file (the DSL is the whole file body — there's no prose).
3. Paste into Eraser. The canvas updates as you type.
4. Export PNG (for MkDocs) and SVG (for LaTeX tech report). Save under the consuming doc's `figures/` folder, not here.
5. If you edit a diagram, **update the source here first**, then re-export. Never edit the rendered PNG directly.

---

## House rules

- One diagram per file. Don't stuff multiple diagrams into a single `.md`.
- Filename pattern: `<topic>_eraser.md`. The `_eraser` suffix makes it obvious at a glance what tooling the file targets.
- Keep labels short. Long labels make the canvas unreadable.
- Use Eraser's icon system (`[icon: <name>]`) rather than embedding raster images.
- If a diagram is **petition-relevant** (Prong-1 narrative, SR 11-7 map, competitive landscape), freeze a rendered copy in `_archive/` before every petition-filing draft — sources can drift, but the petition exhibit must be stable.
