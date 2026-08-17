# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Playground: exercise every plug-point in lub end-to-end with InMemory doubles.

A single self-contained script that demonstrates the post-pass-39
Protocol-pluggable architecture. **Zero external deps**: no sqlite, no
FastAPI, no real LLM provider, no filesystem. Just pure-Python plug-ins
that satisfy each Protocol structurally.

Run::

    python examples/playground_in_memory.py

What it shows:

1. lub.benchmarks.protocol.BenchmarkProtocol -- a TinyMedQA plug-in
   benchmark (not banking-flavored, no inheritance from Dataset).
2. lub.evidence.protocol.EvidenceStoreProtocol -- InMemoryEvidenceStore
   indexing + querying.
3. lub.ledger.protocol.LedgerProtocol -- InMemoryLedger logging
   queries/answers/policies/outcomes.
4. lub.dashboard.protocols.SnapshotSource -- InMemorySnapshotSource
   bridge over the InMemoryLedger.
5. lub.dashboard.protocols.SnapshotRenderer -- a custom plug-in
   markdown renderer registered alongside the default html/json.
6. lub.reports.dashboard_protocols.EvidenceSource -- InMemoryEvidenceSource
   for the static evidence dashboard.
7. lub.orchestration.router_protocol.RouterPolicy -- a tiny stub policy
   registered into the policy registry.

Anyone integrating LUB into a non-banking domain or with non-sqlite
storage can use this as the canonical "how do I plug in" reference.

Spec: planning/31_Storage_Genericity_Spec_2026-04-25.md (consolidation).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

# All 7 Protocol surfaces:
from lub.benchmarks.base import Example
from lub.benchmarks.protocol import (
    BenchmarkProtocol,
    register_external_benchmark,
)
from lub.dashboard import build_snapshot, render_html, render_json
from lub.dashboard.in_memory_source import InMemorySnapshotSource
from lub.dashboard.protocols import register_renderer
from lub.evidence.protocol import EvidenceStoreProtocol, InMemoryEvidenceStore
from lub.ledger.protocol import InMemoryLedger, LedgerProtocol
from lub.orchestration.router_protocol import (
    RouterPolicy,
    register_router_policy,
)
from lub.reports.dashboard import build_dashboard, collect_dashboard_data
from lub.reports.dashboard_sources import InMemoryEvidenceSource


# ---------------------------------------------------------------------------
# 1. Benchmark plug-in: TinyMedQA (healthcare domain, no inheritance)
# ---------------------------------------------------------------------------


class TinyMedQA:
    """3-example synthetic benchmark; satisfies BenchmarkProtocol structurally."""

    @property
    def name(self) -> str: return "medqa"

    @property
    def version(self) -> str: return "v1.0"

    def load(self) -> Iterator[Example]:
        yield Example("med-001", "Treatment for CAP?", "amoxicillin",
                      {"specialty": "pulmonology"})
        yield Example("med-002", "HbA1c >= 6.5 indicates?", "diabetes",
                      {"specialty": "endocrinology"})
        yield Example("med-003", "First-line for migraine?", "sumatriptan",
                      {"specialty": "neurology"})


# ---------------------------------------------------------------------------
# 2. Router plug-in: trivial cost-aware policy
# ---------------------------------------------------------------------------


class TwoTierRouter:
    """If the query has 'urgent' in it, escalate to strong tier."""
    def answer(self, query: dict[str, Any]) -> str:
        text = str(query.get("text", "")).lower()
        return "strong-tier" if "urgent" in text else "cheap-tier"


# ---------------------------------------------------------------------------
# 3. Renderer plug-in: markdown for the live dashboard
# ---------------------------------------------------------------------------


def render_markdown(snap: Any) -> str:
    return (
        f"# Dashboard ({snap.tenant})\n\n"
        f"- decisions: **{snap.decisions_in_window}**\n"
        f"- abstention: **{snap.abstention_rate:.0%}**\n"
        f"- correctness: **{snap.correctness_rate:.0%}**\n"
        if snap.correctness_rate is not None else
        f"# Dashboard ({snap.tenant})\n\n"
        f"- decisions: **{snap.decisions_in_window}**\n"
        f"- abstention: **{snap.abstention_rate:.0%}**\n"
        f"- correctness: n/a (no labelled outcomes)\n"
    )


render_markdown.content_type = "text/markdown"


# ---------------------------------------------------------------------------
# Run the playground
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("LUB plug-in playground (no sqlite, no FastAPI, no real models)")
    print("=" * 70)

    # 1. Register the benchmark plug-in
    bench = TinyMedQA()
    assert isinstance(bench, BenchmarkProtocol)
    register_external_benchmark("medqa", bench)
    print(f"\n[1] Registered benchmark plug-in: {bench.name} v{bench.version}")
    examples = list(bench.load())
    print(f"    -> 3 examples; first: {examples[0].id} ({examples[0].metadata['specialty']})")

    # 2. Register the router policy
    router = TwoTierRouter()
    assert isinstance(router, RouterPolicy)
    register_router_policy("two_tier", router)
    print(f"\n[2] Registered router policy: two_tier")
    print(f"    -> 'urgent x' -> {router.answer({'text': 'urgent x'})}")
    print(f"    -> 'normal x' -> {router.answer({'text': 'normal x'})}")

    # 3. Evidence store: InMemoryEvidenceStore
    store: EvidenceStoreProtocol = InMemoryEvidenceStore()
    store.add("Is X true?", "yes", correct=True, uq_scores={"p_true": 0.9})
    store.add("Is Y true?", "no", correct=False, uq_scores={"p_true": 0.4})
    hits = store.query("Is X true?", k=1)
    print(f"\n[3] Evidence store ({type(store).__name__}, {len(store.query('', k=10))} records):")
    print(f"    -> top hit for 'Is X true?': '{hits[0]['question']}' (correct={hits[0]['correct']})")

    # 4. Ledger: InMemoryLedger
    led: LedgerProtocol = InMemoryLedger()
    qid = led.log_query("Is X true?", domain="healthcare")
    aid = led.log_answer(qid, "gpt-4o", "openai", "yes", tier="prime")
    led.log_score(aid, "p_true", 0.92)
    led.log_policy(aid, "EMIT", 0.7, True, "above threshold")
    led.update_outcome(aid, correct=True)
    print(f"\n[4] Ledger ({type(led).__name__}): logged 1 query/answer/score/policy/outcome")

    # 5. Bridge: InMemoryLedger -> SnapshotSource
    src = InMemorySnapshotSource(led)
    snap = build_snapshot(
        src, evidence_store=None,
        period_start=datetime(2020, 1, 1), period_end=datetime(2030, 1, 1),
        tenant="playground", git_sha="demo",
    )
    print(f"\n[5] Live dashboard snapshot built via InMemorySnapshotSource:")
    print(f"    -> decisions={snap.decisions_in_window}, abstention={snap.abstention_rate:.0%}, "
          f"correctness={snap.correctness_rate:.0%}")

    # 6. Render the snapshot in 3 formats: html, json, markdown
    register_renderer("markdown", render_markdown)
    html_out = render_html(snap)
    json_out = render_json(snap)
    md_out = render_markdown(snap)
    print(f"\n[6] Rendered in 3 formats (registered: html, json, markdown):")
    print(f"    -> html: {len(html_out)} chars")
    print(f"    -> json: {len(json_out)} chars")
    print(f"    -> markdown ({len(md_out)} chars):")
    for line in md_out.splitlines():
        print(f"       | {line}")

    # 7. Static evidence dashboard via InMemoryEvidenceSource
    ev_src = InMemoryEvidenceSource(
        benchmark_results=[{
            "estimator": "medqa_p_true", "backend": "openai", "dataset": "medqa",
            "n": 3, "accuracy": 0.67, "ece": 0.04,
        }],
        artefacts=[{"name": "in_memory_run.json", "kind": "benchmark"}],
        regimes=[{"key": "hipaa", "name": "HIPAA", "n_controls": 18}],
    )
    data = collect_dashboard_data(ev_src, title="Healthcare evidence pack")
    print(f"\n[7] Static evidence dashboard via InMemoryEvidenceSource:")
    print(f"    -> {len(data.estimator_rows)} estimator row(s), "
          f"{len(data.regime_coverage)} regime(s)")
    print(f"    -> first regime: {data.regime_coverage[0]['key']} "
          f"({data.regime_coverage[0]['n_controls']} controls)")

    print()
    print("=" * 70)
    print("All 7 plug-points exercised end-to-end. Zero external deps. "
          "Zero banking-specific code.")
    print("=" * 70)


if __name__ == "__main__":
    main()
