# Tier 1 Deployment Guide — Systemically Important Institutions

Companion to [`docs/integration_tiers.md`](../integration_tiers.md) (Tier 1).
This guide is an **implementation pattern** for banking organizations subject
to enhanced prudential standards under Federal Reserve Regulation YY
(12 CFR 252) — typically Categories I and II — not a guaranteed adoption
outcome. All code below runs against the deterministic `dummy` backend so an
MRM engineer can validate the wiring in an air-gapped environment before
pointing it at a production backend (`hf`, `vllm`, `openai`, `anthropic`).

---

## Institution profile

| Dimension | Tier 1 |
|---|---|
| Population | Reg YY Categories I–II banking organizations (12 CFR 252.5) |
| Validation profile | Dedicated MRM teams; deep model inventories; continuous supervisory monitoring |
| Adoption pattern | Integrate with existing MRM infrastructure — do not displace it |
| Key resource | In-house ML engineering capacity (the gating factor) |

The framework surfaces as **additional validation packets inside established
review cycles**: OSCAL Assessment Results (`lub.reports.assessment`) feed the
GRC platform, calibration metrics (`lub.calibration`) supplement existing
performance assessments, and the six-regime crosswalk
(`lub.reports.crosswalk`) supplies the documentation alignment that
supervisory examination already presupposes.

## Integration pattern — estimator ensemble at corpus scale

Tier 1 runs the estimator ensemble in parallel via
`lub.orchestration.UQSwarm` and treats the `method_disagreement`
second-order signal as a routing input for human-review triage.

```python
"""Tier 1 integration example: UQSwarm ensemble + OSCAL Assessment Results.

Executable as-is (deterministic dummy backend, no network). For production,
swap DummyBackend for the HF/vLLM/OpenAI/Anthropic wrapper of record.
"""

import json

from lub.orchestration import UQSwarm
from lub.reports.assessment import render_assessment_json
from lub.types import BenchmarkResult
from lub.uncertainty import (
    PTrueEstimator,
    SelfConsistencyEstimator,
    TokenLogprobEstimator,
)
from lub.wrappers.dummy import DummyBackend

# 1. One backend, several estimators — all score the same completion.
backend = DummyBackend(model_id="dummy-0")
swarm = UQSwarm(
    backend=backend,
    estimators={
        "token_logprob": TokenLogprobEstimator(),
        "self_consistency": SelfConsistencyEstimator(),
        "p_true": PTrueEstimator(),
    },
    weights={"token_logprob": 0.25, "self_consistency": 0.50, "p_true": 0.25},
)

result = swarm.answer("What is the Basel III minimum CET1 ratio?")
print("fused confidence:", round(result.fused.confidence, 4))
print("method_disagreement:", round(result.fused.raw_scores["method_disagreement"], 4))

# 2. Nightly benchmark runs persist BenchmarkResult records
#    (`lub benchmark --dataset br_regulatory --out results.json`).
#    Here we build one inline; in production, load the persisted record.
record = BenchmarkResult(
    repo_version="0.1.0",
    backend="DummyBackend:dummy-0",
    estimator="self_consistency",
    dataset="br_regulatory",
    dataset_version="0.1.0",
    n=20,
    accuracy=0.75,
    ece=0.08,
    refusal_auroc=0.82,
    metrics={"accuracy": 0.75, "ece": 0.08, "refusal_auroc": 0.82, "brier": 0.18},
    python_version="3.12",
    package_versions={"lub": "0.1.0"},
    dataset_hash="a" * 64,
    seed=0,
)

# 3. Emit OSCAL Assessment Results across all six regimes and hand the
#    machine-readable document to the GRC platform (Trestle, RegScale).
oscal_document = render_assessment_json(record)
parsed = json.loads(oscal_document)
n_findings = len(parsed["assessment-results"]["results"][0]["findings"])
print("OSCAL findings emitted:", n_findings)
```

### Continuous monitoring exporters

The continuous-monitoring layer integrates with existing model-performance
dashboards through `lub.ledger.metrics` (stdlib-only Prometheus textfile +
Grafana SimpleJson exporters):

```python
from lub.ledger.metrics import collect_metrics, write_prometheus_textfile

# `ledger` is the sqlite-backed lub.ledger.Ledger recording every
# production query/answer/score/decision (see README "Governance runtime").
metrics = collect_metrics(ledger)
write_prometheus_textfile(
    metrics,
    "/var/lib/node_exporter/textfile_collector/lub.prom",
)
```

Nightly calibration drift is enforced by `lub.governance.drift.enforce_drift`,
which replays reliability buckets from the ledger and raises
`PolicyViolation` when measured ECE exceeds the ADR target — a calibration
regression fails CI, not production.

## Configuration template

```toml
# tier1-lub.toml — Tier 1 (Reg YY Categories I-II) configuration
[deployment]
tier = 1

[model]
backend = "vllm"            # hf | openai | anthropic | vllm | dummy
model_id = "meta-llama/Llama-3.1-70B-Instruct"

[uncertainty]
# UQSwarm members: registry keys from lub.uncertainty (22 estimators, 7 families)
swarm_estimators = ["token_logprob", "self_consistency", "p_true"]
swarm_weights = { token_logprob = 0.25, self_consistency = 0.50, p_true = 0.25 }

[abstention]
refusal_threshold = 0.50          # UncertaintyPipeline global floor
disagreement_review_cutoff = 0.15 # method_disagreement above this -> human review

[reporting]
# All six canonical regimes (Regime enum values, lub.reports.crosswalk)
regimes = [
    "NIST_AI_600-1",
    "EU_AI_ACT_2024/1689",
    "BCBS_239",
    "BCB_Res4893",
    "ISO/IEC_23894:2023",
    "ISO/IEC_42001:2023",
]

[monitoring]
prometheus_textfile = "/var/lib/node_exporter/textfile_collector/lub.prom"
```

Binding the template to the API:

```python
import tomllib
from pathlib import Path

from lub.reports.crosswalk import Regime

config = tomllib.loads(Path("tier1-lub.toml").read_text(encoding="utf-8"))
regime_filter = {Regime(value) for value in config["reporting"]["regimes"]}
```

## SR 11-7 tailoring

Tier 1 populates **all three** SR 11-7 validation pillars from a single
`lub benchmark` + `lub report` run. The pillar-to-metric mapping is code,
not prose:

```python
from lub.compliance.frameworks import sr_11_7

for pillar, metric_names in sr_11_7.get_pillar_metrics().items():
    print(pillar, "->", metric_names)
```

| SR 11-7 pillar | Tier 1 expectation |
|---|---|
| V.A Conceptual Soundness | Full calibration evidence (ECE, RMSCE, ENCE, Brier, ...) per model-inventory entry |
| V.B Outcome Analysis | Selective-prediction quality on institution-curated evaluation sets |
| VI.A–C Ongoing Monitoring | Ledger-backed drift replay + Prometheus exporters wired into the existing dashboard estate |

The Revised Interagency Supervisory Guidance on Model Risk Management
(OCC / Federal Reserve / FDIC, April 17, 2026) carries forward the SR 11-7
principles-based posture and states that generative AI and agentic AI are
outside its declared scope — the crosswalk therefore keeps SR 11-7 as a
cross-referenced pillar table (`lub.compliance.frameworks.sr_11_7`), not as
a `Regime` enum value.

## References

- 12 CFR 252.5 — Federal Reserve tailoring framework (Regulation YY)
- SR 11-7 / OCC Bulletin 2011-12 — supervisory guidance on model risk management
- Revised Interagency Supervisory Guidance on Model Risk Management
  (OCC / Federal Reserve / FDIC, April 17, 2026)
- [`docs/integration_tiers.md`](../integration_tiers.md) — cross-tier summary
