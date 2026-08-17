# banking_personas — calibrated agent pack (skeleton)

10 calibrated banking agents shaped for any orchestrator runtime that
satisfies `OrchestratorAgentProtocol`. Per
`RUFLO_VS_LUB_GAP_2026-04-25.md`
§4.3 this is **post-filing v0.4+ scope**; the skeleton ships now so
counsel can review the contract surface without orchestrator imports
or network dependencies.

## Personas

| # | Name | Estimator | Threshold | NIST AI RMF |
|---|---|---|---|---|
| 1 | `bcb_compliance_officer` | semantic_entropy | 0.70 | MEASURE 2.7 |
| 2 | `mrm_validator` | p_true | 0.65 | MEASURE 2.9 |
| 3 | `basel_iii_reporter` | semantic_entropy | 0.70 | MEASURE 2.8 |
| 4 | `finqa_analyst` | self_consistency | 0.60 | MEASURE 2.3 |
| 5 | `credit_memo_drafter` | conformal | 0.80 | MEASURE 2.8 |
| 6 | `kyc_narrative_writer` | verbalized | 0.75 | MANAGE 3.1 |
| 7 | `aml_summarizer` | claim_level | 0.70 | MANAGE 3.2 |
| 8 | `regime_crosswalk_agent` | p_true | 0.60 | GOVERN 1.4 |
| 9 | `drift_detector` | ensemble | 0.55 | MEASURE 2.10 |
| 10 | `challenge_generator` | epistemic_aleatoric | 0.50 | MANAGE 4.1 |

## Use

```python
from examples.plugins.banking_personas.handlers import build_pack
from lub.runtime import build_orchestrated_pack

pack = build_orchestrated_pack(build_pack())
# hand `pack` to your orchestrator (ruflo / langgraph / crewai / autogen)
```

Or via the CLI:

```bash
lub run-swarm \
    --pack examples.plugins.banking_personas.handlers:build_pack \
    --dry-run
```

## What this skeleton is

- 10 declarative persona rows in `manifest.json` (tags, thresholds, RMF mapping)
- 1 stub Python class (`StubBankingAgent`) that proves the wiring works on `DummyBackend`
- Hooks into `lub.runtime.build_orchestrated_pack` — same contract as production

## What this skeleton is *not*

- Not production agent logic. Real `prompt_template` and `parse` for each
  persona land post-filing per [RUFLO_AS_CORE_IMPACT §4.3].
- Not integrated with a real backend. `DummyBackend` only — the goal here
  is shape review, not output quality.
- Not a public release. The directory lives under `examples/plugins/`
  exactly so it does not ship in the wheel.
