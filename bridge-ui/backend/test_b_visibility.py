# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Bloco B (MVP) — AI Visibility monitoring with lub instrumentation.

Verifies the differentiator: each collection is routed through the real
uncertainty guard (decision) AND the real tamper-evident audit chain
(seq + hash), and Share-of-Voice / presence / position are aggregated
correctly. The model answers come from the offline FakeVisibilityAdapter.

Isolation: monkeypatches ``_audit_db`` so audit appends skip the shared SQLite
(in-memory chain still builds), and restores the visibility module globals.

Run from the project root::

    pytest bridge-ui/backend/test_b_visibility.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers import visibility as vis  # noqa: E402
except ImportError:
    from routers import visibility as vis  # type: ignore[no-redef]  # noqa: E402


def _no_db():
    raise RuntimeError("test: sqlite disabled")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    import sqlite3

    monkeypatch.setattr(server, "_audit_db", _no_db)
    # Isolate the visibility SQLite history in an in-memory DB so tests never
    # touch the on-disk file or contend with a running demo.
    mem = sqlite3.connect(":memory:", check_same_thread=False)
    mem.execute(
        "CREATE TABLE IF NOT EXISTS visibility_runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, adapter TEXT, metrics_json TEXT)"
    )
    mem.commit()
    monkeypatch.setattr(vis, "_VIS_DB_CONN", mem)
    # Save/restore all mutable visibility + guard state.
    saved_entries = list(server._AUDIT)
    saved_seq = server._AUDIT_SEQ
    saved_hash = server._AUDIT_LAST_HASH
    saved_q = list(vis._MONITORING_QUERIES)
    saved_e = list(vis._TARGET_ENTITIES)
    saved_run = vis._LAST_RUN
    saved_brand = vis._OWN_BRAND
    saved_active = vis._ACTIVE_ADAPTER
    saved_vol = dict(vis._QUERY_VOLUME)
    saved_drafts = list(vis._CONTENT_DRAFTS)
    saved_cseq = vis._CONTENT_SEQ
    saved_thr = server._RUNTIME_GUARD_THRESHOLD
    yield
    server._AUDIT.clear()
    server._AUDIT.extend(saved_entries)
    server._AUDIT_SEQ = saved_seq
    server._AUDIT_LAST_HASH = saved_hash
    vis._MONITORING_QUERIES = saved_q
    vis._TARGET_ENTITIES = saved_e
    vis._LAST_RUN = saved_run
    vis._OWN_BRAND = saved_brand
    vis._ACTIVE_ADAPTER = saved_active
    vis._QUERY_VOLUME = saved_vol
    vis._CONTENT_DRAFTS[:] = saved_drafts
    vis._CONTENT_SEQ = saved_cseq
    server._RUNTIME_GUARD_THRESHOLD = saved_thr


def test_config_lists_queries_entities_and_gaps() -> None:
    cfg = vis.get_config()
    assert len(cfg["queries"]) >= 1
    assert len(cfg["entities"]) >= 1
    assert cfg["active_adapter"] in cfg["available_adapters"]
    # Honesty: the gaps must be advertised, not hidden.
    assert any("FakeVisibilityAdapter" in g or "real" in g.lower() for g in cfg["gaps"])


def test_run_instruments_every_collection_with_guard_and_audit() -> None:
    out = vis.run_collection()
    assert out["queries_run"] == len(vis._MONITORING_QUERIES)
    seqs = []
    for r in out["results"]:
        assert r["decision"] in ("PASSTHROUGH", "FLAG", "REASK", "ESCALATE")
        assert 0.0 <= r["confidence"] <= 1.0
        assert isinstance(r["audit_seq"], int)
        assert len(r["audit_hash"]) == 64  # sha256 hex
        seqs.append(r["audit_seq"])
    # Each collection got its own chained audit entry.
    assert len(set(seqs)) == len(seqs)
    assert seqs == sorted(seqs)


def test_audit_chain_stays_valid_after_a_run() -> None:
    try:
        from backend.routers import audit as audit_router
    except ImportError:
        from routers import audit as audit_router  # type: ignore[no-redef]

    server._AUDIT.clear()
    server._AUDIT_SEQ = 0
    server._AUDIT_LAST_HASH = "0" * 64
    vis.run_collection()
    verdict = audit_router.audit_verify()
    assert verdict["valid"] is True, "visibility collections must extend the chain intact"
    assert verdict["checked"] == len(vis._MONITORING_QUERIES)


def test_accented_entity_is_detected() -> None:
    # "Itau" entity must match the answer text regardless of diacritics.
    mentions = vis._extract_mentions("O Itaú lidera em atendimento digital.")
    itau = next(m for m in mentions if m["entity"] == "Itau")
    assert itau["mentioned"] is True
    assert itau["position"] == 1


def test_share_of_voice_sums_to_one_when_there_are_mentions() -> None:
    out = vis.run_collection()
    metrics = out["metrics"]
    assert metrics["total_mentions"] > 0
    total_sov = sum(e["share_of_voice"] for e in metrics["entities"])
    assert abs(total_sov - 1.0) < 0.02, f"SoV should sum to ~1, got {total_sov}"
    # presence_pct is per-query frequency, bounded [0,1].
    for e in metrics["entities"]:
        assert 0.0 <= e["presence_pct"] <= 1.0


def test_absent_brand_yields_low_confidence_escalation() -> None:
    # A query whose answer mentions no target entity → low-confidence reading.
    vis.put_config(vis.ConfigUpdate(queries=["pergunta sem nenhuma marca conhecida"], entities=["MarcaInexistente"]))
    out = vis.run_collection()
    r = out["results"][0]
    assert all(not m["mentioned"] for m in r["mentions"])
    assert r["confidence"] < 0.6
    assert r["decision"] in ("REASK", "ESCALATE")


def test_results_empty_before_first_run() -> None:
    vis._LAST_RUN = None
    res = vis.get_results()
    assert res["queries_run"] == 0
    assert res["results"] == []


# ---------------------------------------------------------------------------
# P3.7 B1 — pluggable adapters (offline-safe; no keys present in test env)
# ---------------------------------------------------------------------------


def test_fake_adapter_is_default_and_real_adapters_are_key_gated() -> None:
    # The fake adapter must always be registered and the default; real adapters
    # only appear when their key env var is set (not in the test env).
    assert vis.FakeVisibilityAdapter.name in vis._ADAPTERS
    assert vis._ACTIVE_ADAPTER == vis.FakeVisibilityAdapter.name
    assert vis._ADAPTERS[vis._ACTIVE_ADAPTER].is_real is False
    cfg = vis.get_config()
    assert vis.FakeVisibilityAdapter.name in cfg["available_adapters"]


def test_selecting_unknown_adapter_is_rejected() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        vis.put_config(vis.ConfigUpdate(active_adapter="openai:does-not-exist"))
    assert exc.value.status_code == 422


def test_real_adapter_classes_exist_for_plugging() -> None:
    # The interface real providers implement (verified without network/keys).
    for cls in (vis.OpenAIVisibilityAdapter, vis.AnthropicVisibilityAdapter):
        a = cls()
        assert a.is_real is True
        assert ":" in a.name
        # No key in env -> answer() returns "" (graceful, never raises).
        assert a.answer("qual o melhor banco?") == ""


# ---------------------------------------------------------------------------
# P3.8 B2 — SQLite time-series persistence
# ---------------------------------------------------------------------------


def test_history_accumulates_across_runs() -> None:
    vis.run_collection()
    vis.run_collection()
    hist = vis.get_history()
    assert hist["count"] == 2, f"expected 2 runs persisted, got {hist['count']}"
    # Each history row carries per-entity Share-of-Voice (the time-series point).
    assert all("share_of_voice" in r for r in hist["runs"])
    assert vis._OWN_BRAND in hist["runs"][-1]["share_of_voice"]


def test_scheduler_is_off_by_default() -> None:
    # No VISIBILITY_SCHEDULE_EVERY_S in the test env -> no background thread.
    import os

    assert os.environ.get("VISIBILITY_SCHEDULE_EVERY_S", "0") in ("", "0")
    assert vis._SCHEDULER_STARTED is False


# ---------------------------------------------------------------------------
# P3.9 B3 — recommendations engine
# ---------------------------------------------------------------------------


def test_recommendations_rank_own_brand_gaps_by_score() -> None:
    vis.put_config(vis.ConfigUpdate(own_brand="Bradesco"))
    vis.run_collection()
    recs = vis.get_recommendations()
    assert recs["own_brand"] == "Bradesco"
    # Default config: q1 ("melhor banco digital") fake answer omits Bradesco →
    # a gap recommendation must exist for it.
    assert any(r["query_id"] == "q1" for r in recs["recommendations"]), recs
    # Sorted by score descending; every rec has evidence + an action.
    scores = [r["score"] for r in recs["recommendations"]]
    assert scores == sorted(scores, reverse=True)
    for r in recs["recommendations"]:
        assert r["gap"] > 0 and r["evidence"] and r["action"]


def test_recommendations_volume_weight_raises_score() -> None:
    vis.run_collection()
    base = {r["query_id"]: r["score"] for r in vis.get_recommendations()["recommendations"]}
    # Triple the volume of a gap query → its score must increase proportionally.
    gap_qid = next(iter(base))
    vis.put_config(vis.ConfigUpdate(query_volumes={gap_qid: 3.0}))
    after = {r["query_id"]: r["score"] for r in vis.get_recommendations()["recommendations"]}
    assert after[gap_qid] > base[gap_qid]


# ---------------------------------------------------------------------------
# P3.10 B4 — content drafts gated by the guard + human approval
# ---------------------------------------------------------------------------


def test_passthrough_draft_can_be_human_approved() -> None:
    server._RUNTIME_GUARD_THRESHOLD = 0.7  # default → high-confidence draft PASSTHROUGH
    vis.run_collection()
    draft = vis.create_draft(vis.DraftRequest(query_id="q1"))
    assert draft["decision"] == "PASSTHROUGH"
    assert draft["status"] == "pending_approval" and draft["publishable"] is True
    out = vis.approve_draft(draft["id"], approver="rafael", principal=None)
    assert out["status"] == "approved"
    # Approval enqueues only — it must NOT claim external publication.
    assert "no external publication" in out["note"].lower()


def test_flag_or_escalate_draft_is_blocked_from_approval() -> None:
    # Raise the threshold ABOVE the reading's confidence so it does not PASSTHROUGH
    # → the draft is REASK/ESCALATE → blocked → approval refused (409). Since #B1,
    # read-only/informational intents (visibility) release at conf >= threshold (no
    # +0.15 margin), so the bar must exceed q1's measurement confidence (0.97).
    server._RUNTIME_GUARD_THRESHOLD = 0.98
    vis.run_collection()
    draft = vis.create_draft(vis.DraftRequest(query_id="q1"))
    assert draft["decision"] in ("FLAG", "REASK", "ESCALATE")
    assert draft["status"] == "blocked" and draft["publishable"] is False

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        vis.approve_draft(draft["id"], principal=None)
    assert exc.value.status_code == 409, "FLAG/ESCALATE content must never be approvable"


def test_draft_requires_a_prior_run_and_valid_query() -> None:
    from fastapi import HTTPException

    vis._LAST_RUN = None
    with pytest.raises(HTTPException) as exc:
        vis.create_draft(vis.DraftRequest(query_id="q1"))
    assert exc.value.status_code == 409  # no run yet

    vis.run_collection()
    with pytest.raises(HTTPException) as exc2:
        vis.create_draft(vis.DraftRequest(query_id="does-not-exist"))
    assert exc2.value.status_code == 404
