# LUB Protocol-Based Architecture (post-pass-39)

This document maps every plug-point in `lub` to its `Protocol`, default
implementation, and (where available) in-memory test double. As of pass 39
(2026-04-25), 9 architectural axes are Protocol-pluggable. New plug-ins
register without modifying core code.

---

## 1. The 9 plug-points

| # | Axis | Protocol | Default impl | InMemory double | Spec |
|---|---|---|---|---|---|
| 1 | Agent orchestration | `lub.agents.adapters.orchestrator.OrchestratorAgentProtocol` | `RufloAgentAdapter` (back-compat alias `lub.agents.adapters.ruflo`) | (test fixture in `tests/test_agent_adapters.py`) | spec 27 + ADR-002 |
| 2 | Benchmark dataset | `lub.benchmarks.protocol.BenchmarkProtocol` | `lub.benchmarks.base.Dataset` (ABC, 8 concrete) | `TinyMedQA` (in `tests/test_benchmark_protocol_plugin_example.py`) | spec 30 §4 |
| 3 | Live-dashboard data | `lub.dashboard.protocols.SnapshotSource` | `lub.dashboard.ledger_source.LedgerSnapshotSource` (sqlite) | `InMemorySnapshotSource` (pass 39) | spec 29 + 31 §2 |
| 4 | Live-dashboard format | `lub.dashboard.protocols.SnapshotRenderer` | `render_html` + `render_json` (auto-registered) | (any callable with `.content_type`) | spec 29 + 31 §2 |
| 5 | Static-dashboard data | `lub.reports.dashboard_protocols.EvidenceSource` | `lub.reports.dashboard_sources.DirEvidenceSource` (filesystem) | `InMemoryEvidenceSource` | spec 31 §1 |
| 6 | Static-dashboard format | `lub.reports.dashboard_protocols.EvidenceRenderer` | `render_dashboard_html` (auto-registered) | (any callable with `.content_type`) | spec 31 §1 |
| 7 | Router policy | `lub.orchestration.router_protocol.RouterPolicy` | `TieredRouter`, `FailoverChain` (structurally conformant) | (any callable with `.answer`) | spec 31 §2.3 |
| 8 | Evidence store | `lub.evidence.protocol.EvidenceStoreProtocol` | `lub.evidence.store.EvidenceStore` (TF-IDF + cosine) | `InMemoryEvidenceStore` (Jaccard) | spec 31 §2.1 |
| 9 | Audit ledger | `lub.ledger.protocol.LedgerProtocol` | `lub.ledger.store.Ledger` (sqlite) | `InMemoryLedger` | spec 31 §2.2 |

---

## 2. Two cross-Protocol bridges

| Bridge | Maps | Lives in |
|---|---|---|
| `_coerce_to_source` (back-compat shim) | concrete `Ledger` -> `SnapshotSource` (auto-wraps) | `lub.dashboard.query` |
| `_coerce_to_evidence_source` (back-compat shim) | `Path` / `str` -> `EvidenceSource` (auto-wraps with `DirEvidenceSource`) | `lub.reports.dashboard` |
| `InMemorySnapshotSource(led)` | `InMemoryLedger` -> `SnapshotSource` | `lub.dashboard.in_memory_source` |

---

## 3. Two namespace plug-points (counsel-gated)

| Axis | Namespace | Status |
|---|---|---|
| Domain | `lub.domains.<banking|healthcare|defense|...>` | empty (pass 30); migration counsel-gated per spec 30 §6 |
| Compliance framework | `lub.compliance.frameworks.<sr11_7|nist_ai_rmf|iso_42001|eu_ai_act|hipaa|...>` | empty (pass 30); migration counsel-gated |

---

## 4. End-to-end without external deps

```python
# All 7 in-process plug-points exercised in pure Python -- no sqlite,
# no FastAPI, no real LLM provider.
from datetime import datetime
from lub.dashboard import build_snapshot, render_html
from lub.dashboard.in_memory_source import InMemorySnapshotSource
from lub.ledger.protocol import InMemoryLedger

led = InMemoryLedger()
qid = led.log_query("Is X true?", domain="healthcare")
aid = led.log_answer(qid, "gpt-4o", "openai", "yes", tier="prime")
led.log_policy(aid, "EMIT", 0.7, True, "above threshold")
led.update_outcome(aid, correct=True)

src = InMemorySnapshotSource(led)
snap = build_snapshot(src,
                     period_start=datetime(2026, 1, 1),
                     period_end=datetime(2026, 12, 31),
                     tenant="healthcare-q2")
html = render_html(snap)  # <!DOCTYPE html>...
```

The full demo lives at `examples/playground_in_memory.py`. Run with
`python examples/playground_in_memory.py` -- output exercises all 7
plug-points + the bridge.

---

## 5. How to add a plug-in

The pattern is the same for every axis:

1. **Implement the Protocol structurally** -- no inheritance required;
   just expose the methods the Protocol declares (the type system uses
   `@runtime_checkable` Protocol so `isinstance()` works on duck types).
2. **Register if there's a registry** -- e.g.
   `register_router_policy("my_policy", MyPolicy())` for axes 4, 6, 7.
3. **Pass the instance to the consumer** -- e.g.
   `build_snapshot(MyCustomSnapshotSource(...), ...)` for axis 3.

The default implementations all satisfy their Protocols structurally, so
existing v0.1 callers keep working unchanged.

---

## 6. Why this matters

Beyond engineering taste, the Protocol-pluggable shape **strengthens the
generality argument** for the four "first OSS" claims in the petition
narrative (per spec 30 §6 reframe option):

- Claim 2 ("First OSS LLM UQ library mapped to compliance frameworks")
  reads broader when the compliance side is plug-in (not
  SR-11-7-monolithic).
- Claim 4 ("First OSS to operationalize SR 11-7 effective challenge as
  CEC") generalizes to any regulator-style effective challenge once the
  evidence/ledger storage is plug-in.

Whether to actually reframe in the petition is counsel-gated (per
`planning/_scratch/petition_pivot_risk_2026-04-25.md` Item 8). The
engineering side is decoupled from that decision: nothing in this
architecture depends on the petition narrative being rewritten.
