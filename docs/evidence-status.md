# Evidence status — implemented vs. benchmarked

Candor artifact (planning/39). "Implemented" = code + unit tests pass.
"Benchmarked on a real model" = has produced numbers from a real (non-Dummy) LLM.
As of 2026-07-11 the library has its **first non-degenerate real-model result** —
so the tables that still show 0.000 are stale DummyBackend runs, disclosed here.

| Component | Implemented (code + unit tests) | Benchmarked on a real model | Artifact |
|---|---|---|---|
| Uncertainty estimators (22) | ✅ 22, unit-tested | ✅ real run — `llama3.1:8b`, `perplexity`: **accuracy 0.55** (fuzzy/containment, n=20) | [benchmarks.md](benchmarks.md) |
| Calibration metrics (14) | ✅ unit-tested (116 tests) | ✅ computed on the real run: ece 0.178, refusal_auroc 0.586 | [benchmarks.md](benchmarks.md) |
| Datasets (`br_regulatory` + 7) | ✅ schemas + loaders | ✅ `br_regulatory` n=20 on a real model | [benchmarks.md](benchmarks.md) |
| OSCAL Assessment Results emit | ✅ real emitter (`reports/oscal.py`) | ⚠️ committed artifacts stale / fail NIST schema (planning/35 A.3) | `docs/tech-report/artifacts/` |
| SR 11-7 / 6-regime crosswalk | ✅ 23 metrics × 32 controls mapped | ➖ crosswalk = **map coverage, not measured accuracy** | `src/lub/reports/crosswalk_data.toml` |
| Bridge demo evidence pack | ✅ Ed25519-signed, hash-chained | ➖ demo-grade (FakeBackend / in-sample n=34 intent classifier) | `bridge-ui/` |

**Bottom line for a diligence reader:** the library is now **demonstrated, not
just claimed** — `llama3.1:8b` answers ~55% of the BR-regulatory set with the
correct value, confidence carries a 0.586-AUROC refusal signal, and the run is
reproducible (`scripts/run_real_benchmark.py`). Still open: the committed OSCAL
artifacts fail NIST's schema (planning/35 A.3) and the crosswalk reports map
coverage, not measured accuracy — those are the next candor items.
