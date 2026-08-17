# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Governed change requests (#4 / v6) — persisted approval workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

try:
    from backend.routers import governance_changes as gc  # noqa: E402
except ImportError:
    from routers import governance_changes as gc  # type: ignore[no-redef]  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    monkeypatch.setattr(gc, "_DB_PATH", ":memory:")
    monkeypatch.setattr(gc, "_DB", None)
    yield


def test_submit_creates_a_pending_change() -> None:
    r = gc.submit_change("agent", "Adicionar agente de cobrança PJ", "ana.analista")
    assert r["status"] == "pending"
    lst = gc.list_changes()
    assert lst["n"] == 1
    assert lst["by_status"]["pending"] == 1
    assert lst["changes"][0]["submitted_by"] == "ana.analista"


def test_submit_rejects_oversized_summary() -> None:
    # A summary over the 500-char cap is rejected (422), not silently stored —
    # prevents trail-layout overflow / ledger bloat (QA: fields had no length cap).
    with pytest.raises(HTTPException) as exc:
        gc.submit_change("dq_rule", "x" * 501, "ana.analista")
    assert exc.value.status_code == 422
    assert gc.list_changes()["n"] == 0  # nothing persisted


def test_duplicate_submission_warns_without_blocking() -> None:
    gc.submit_change("dq_rule", "block messages over 5000 chars", "ana.analista")
    r2 = gc.submit_change("dq_rule", "block messages over 5000 chars", "bruno.validador")
    assert r2["status"] == "pending"  # still recorded — ledger is append-only
    assert "duplicate_warning" in r2 and "#1" in r2["duplicate_warning"]
    assert gc.list_changes()["n"] == 2  # both exist
    # a rejected duplicate no longer counts as "live"
    gc.decide_change(r2["id"], "reject", "carla.mrm")
    r3 = gc.submit_change("dq_rule", "block messages over 5000 chars", "carla.mrm")
    assert "#1" in r3["duplicate_warning"] and f"#{r2['id']}" not in r3["duplicate_warning"]


def test_independent_reviewer_approves_with_dated_trail() -> None:
    cid = gc.submit_change("intent", "Nova intent: pix_agendado", "ana.analista")["id"]
    out = gc.decide_change(cid, "approve", "bruno.validador", "revisado")
    assert out["status"] == "approved"
    ch = gc.list_changes()["changes"][0]
    assert ch["reviewer"] == "bruno.validador"
    assert ch["decided_at"]
    assert ch["decision_note"] == "revisado"


def test_segregation_of_duties_blocks_self_approval() -> None:
    cid = gc.submit_change("dq_rule", "Bloquear CPF inválido", "ana.analista")["id"]
    with pytest.raises(HTTPException) as exc:
        gc.decide_change(cid, "approve", "ana.analista")
    assert exc.value.status_code == 400


def test_cannot_decide_an_already_decided_change() -> None:
    cid = gc.submit_change("rag_doc", "Manual de cobrança v2", "ana.analista")["id"]
    gc.decide_change(cid, "reject", "bruno.validador")
    with pytest.raises(HTTPException) as exc:
        gc.decide_change(cid, "approve", "carla.mrm")
    assert exc.value.status_code == 409


def test_persists_across_a_reconnect(monkeypatch) -> None:
    # write to a real temp file, drop the connection, reopen — the change survives
    import tempfile

    path = str(Path(tempfile.gettempdir()) / "bridge_changes_test.db")

    def _close_and_reset() -> None:
        if gc._DB is not None:
            gc._DB.close()
        monkeypatch.setattr(gc, "_DB", None)

    monkeypatch.setattr(gc, "_DB_PATH", path)
    _close_and_reset()
    gc.submit_change("agent", "persistir isto", "ana.analista")
    _close_and_reset()  # simulate a process restart
    assert gc.list_changes()["n"] >= 1
    _close_and_reset()  # release the file (Windows locks it while open)
    Path(path).unlink(missing_ok=True)


def test_decision_endpoint_flags_sod_not_enforced_when_auth_off() -> None:
    """Audit honesty signal: with BRIDGE_AUTH=off the SoD check compares
    unverified body fields, so the response must self-disclose that the control
    is not cryptographically enforced."""
    cid = gc.submit_change("intent", "Nova intent: pix_agendado", "ana.analista")["id"]
    out = gc.decision_endpoint(
        cid, gc.DecisionRequest(decision="approve", reviewer="bruno.validador"), principal=None
    )
    assert out["status"] == "approved"
    assert out["sod_enforced"] is False
    assert "BRIDGE_AUTH=off" in out["sod_warning"]


def test_decision_endpoint_marks_sod_enforced_when_authenticated() -> None:
    """With a verified validator token, reviewer is signature-bound -> SoD is
    enforced and no warning is emitted."""
    cid = gc.submit_change("intent", "Outra intent", "ana.analista")["id"]
    principal = {"sub": "bruno.validador", "roles": ["validator"]}
    out = gc.decision_endpoint(
        cid, gc.DecisionRequest(decision="approve", reviewer="ignored-when-authed"), principal=principal
    )
    assert out["status"] == "approved"
    assert out["sod_enforced"] is True
    assert "sod_warning" not in out


# --- apply executor: the primitive that closes the governance loop ---------------


def _approved_provider(name: str = "fake-2", **extra) -> int:
    """Submit + independently approve a fake provider change; return its id."""
    payload = {"name": name, "type": "fake", **extra}
    cid = gc.submit_change("provider", f"Ativar provedor {name}", "ana.analista", payload)["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    return cid


def test_apply_executes_an_approved_change_into_the_system_of_record() -> None:
    cid = _approved_provider("fake-2")
    out = gc.apply_change(cid, "carla.mrm")
    assert out["status"] == "applied"
    ch = gc.list_changes()["changes"][0]
    assert ch["status"] == "applied"
    assert ch["applied_by"] == "carla.mrm"
    assert ch["applied_at"]
    active = gc.active_configs("provider")
    assert active["n"] == 1
    assert active["configs"][0]["name"] == "fake-2"


def test_apply_is_replay_guarded() -> None:
    cid = _approved_provider()
    gc.apply_change(cid, "carla.mrm")
    with pytest.raises(HTTPException) as exc:
        gc.apply_change(cid, "carla.mrm")  # second apply must be refused
    assert exc.value.status_code == 409


def test_apply_requires_an_independent_applier() -> None:
    cid = _approved_provider()
    with pytest.raises(HTTPException) as exc:
        gc.apply_change(cid, "ana.analista")  # submitter cannot apply its own work
    assert exc.value.status_code == 400


def test_apply_requires_applier_distinct_from_reviewer() -> None:
    # Four-eyes: the approver cannot also execute. _approved_provider() is approved by
    # bruno.validador, so applying as bruno must be refused (was a real SoD gap).
    cid = _approved_provider()
    with pytest.raises(HTTPException) as exc:
        gc.apply_change(cid, "bruno.validador")
    assert exc.value.status_code == 400


def test_cannot_apply_a_change_that_is_not_approved() -> None:
    cid = gc.submit_change("provider", "Ainda pendente", "ana.analista", {"name": "fake-x", "type": "fake"})["id"]
    with pytest.raises(HTTPException) as exc:
        gc.apply_change(cid, "carla.mrm")  # still pending
    assert exc.value.status_code == 409


def test_secret_is_never_persisted_or_returned() -> None:
    raw = "EAAS3cr3tT0k3n12345"
    cid = gc.submit_change(
        "provider", "Provedor com chave", "ana.analista", {"name": "p1", "type": "fake", "api_key": raw}
    )["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    gc.apply_change(cid, "carla.mrm")
    blob = json.dumps(gc.list_changes()) + json.dumps(gc.active_configs())
    assert raw not in blob, "raw secret leaked into a governance read path"
    assert "_masked" in blob, "secret field should be replaced by a masked marker"


def test_nested_secrets_are_masked_at_any_depth() -> None:
    # A flat redaction would leak a secret nested in a dict/list — mask at any depth.
    raw1, raw2 = "RAWKEY-abc123", "RAWTOKEN-xyz789"
    cid = gc.submit_change(
        "provider",
        "nested secret test",
        "ana.analista",
        {"name": "p", "config": {"api_key": raw1}, "credentials": [{"token": raw2}]},
    )["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    gc.apply_change(cid, "carla.mrm")
    blob = json.dumps(gc.list_changes()) + json.dumps(gc.active_configs())
    assert raw1 not in blob and raw2 not in blob, "nested secret leaked"
    assert "_masked" in blob


def test_demo_safe_refuses_a_real_provider() -> None:
    cid = gc.submit_change(
        "provider", "Ligar OpenAI", "ana.analista", {"name": "openai", "type": "openai", "is_real": True}
    )["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    with pytest.raises(HTTPException) as exc:
        gc.apply_change(cid, "carla.mrm", demo_safe=True)
    assert exc.value.status_code == 409


def test_apply_generalizes_to_non_connection_kinds() -> None:
    # apply now works for agent/intent/dq_rule/rag_doc, not just provider/channel.
    cid = gc.submit_change("agent", "Add agent collector", "ana.analista", {"name": "collector", "model": "fake"})["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    out = gc.apply_change(cid, "carla.mrm")
    assert out["status"] == "applied" and out["domain"] == "agent" and out["name"] == "collector"
    active = gc.active_configs("agent")
    assert active["n"] == 1 and active["configs"][0]["name"] == "collector"


def test_apply_remove_op_deletes_the_live_config() -> None:
    cid = gc.submit_change("provider", "Activate fake p9", "ana.analista", {"name": "p9", "type": "fake"})["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    gc.apply_change(cid, "carla.mrm")
    assert gc.active_configs("provider")["n"] == 1
    rid = gc.submit_change("provider", "Remove p9", "ana.analista", {"name": "p9", "type": "fake", "op": "remove"})["id"]
    gc.decide_change(rid, "approve", "bruno.validador")
    out = gc.apply_change(rid, "carla.mrm")
    assert out["result"] == "removed"
    assert gc.active_configs("provider")["n"] == 0  # gone


def test_unknown_kind_is_rejected_with_422() -> None:
    """A typo'd kind must 422, not silently become a stored 'other' change."""
    with pytest.raises(HTTPException) as exc:
        gc.submit_change("provder", "kind digitado errado", "ana.analista", {"name": "x", "type": "fake"})
    assert exc.value.status_code == 422


def test_submit_is_recorded_on_the_tamper_evident_audit_chain() -> None:
    """The PROPOSAL is evidence too: a submit must land on the same hash-chain, masked.
    Before this, only the apply was chained — so the 'approvals are tamper-evident' claim
    covered 1 of the 3 lifecycle steps (propose/approve lived in mutable SQLite)."""
    srv = gc._server()
    raw = "EAAS3cr3tSubmit11111"
    before = len(srv._AUDIT)
    cid = gc.submit_change(
        "provider", "Provedor proposto", "ana.analista",
        {"name": "fake-sub", "type": "fake", "api_key": raw},
    )["id"]
    chain = list(srv._AUDIT)
    assert len(chain) > before, "submit must append to the audit chain"
    entry = chain[-1]
    assert entry.get("event") == "governance.submit"
    assert entry.get("change_id") == cid
    assert entry.get("submitted_by") == "ana.analista"
    assert entry.get("decision") == "PENDING"
    assert entry.get("config_hash")
    assert "hash" in entry and "prev_hash" in entry and "seq" in entry  # chain fields stamped
    assert raw not in json.dumps(chain, default=str)  # secret never reaches the trail


def test_decision_is_recorded_on_the_tamper_evident_audit_chain() -> None:
    """The APPROVAL is the SoD control itself — who approved what, when, must be chained
    so it cannot be quietly rewritten in the mutable change_requests row."""
    srv = gc._server()
    cid = gc.submit_change("intent", "Nova intent auditada", "ana.analista")["id"]
    gc.decide_change(cid, "approve", "bruno.validador", "revisado")
    entry = list(srv._AUDIT)[-1]
    assert entry.get("event") == "governance.decision"
    assert entry.get("change_id") == cid
    assert entry.get("reviewer") == "bruno.validador"
    assert entry.get("submitted_by") == "ana.analista"  # both sides of the SoD pair
    assert entry.get("decision") == "APPROVED"
    assert entry.get("decision_note") == "revisado"
    assert "hash" in entry and "prev_hash" in entry and "seq" in entry

    # a rejection is chained too, with its own verdict
    rid = gc.submit_change("dq_rule", "Regra recusada", "ana.analista")["id"]
    gc.decide_change(rid, "reject", "carla.mrm", "fora de escopo")
    rej = list(srv._AUDIT)[-1]
    assert rej.get("event") == "governance.decision"
    assert rej.get("decision") == "REJECTED"
    assert rej.get("reviewer") == "carla.mrm"


def test_full_lifecycle_is_chained_end_to_end() -> None:
    """submit → decision → apply produce THREE linked entries: the whole governed change
    (who proposed, who approved, who executed) is tamper-evident, not just the apply."""
    srv = gc._server()
    # The audit deque is the REAL shared module state (only the SQLite db is per-test), and
    # change_id restarts at 1 in every test — so scope to the entries THIS test appended.
    before = len(srv._AUDIT)
    cid = gc.submit_change(
        "provider", "Ciclo completo", "ana.analista", {"name": "fake-life", "type": "fake"}
    )["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    gc.apply_change(cid, "carla.mrm")
    mine = [e for e in list(srv._AUDIT)[before:] if e.get("change_id") == cid]
    assert [e["event"] for e in mine] == [
        "governance.submit",
        "governance.decision",
        "governance.apply",
    ]
    # the chain links them in order (each seq strictly increases)
    seqs = [e["seq"] for e in mine]
    assert seqs == sorted(seqs) and len(set(seqs)) == 3
    # the approval is bound to the same proposed bytes across all three
    hashes = {e["config_hash"] for e in mine}
    assert len(hashes) == 1, "config_hash must bind the whole lifecycle to the same payload"


def test_apply_is_recorded_on_the_tamper_evident_audit_chain() -> None:
    """An applied change must land on the SR 11-7 audit hash-chain (the same one /query
    uses), masked — so the governance trail is detectable-tamper, not just a mutable row."""
    srv = gc._server()  # the single canonical server/audit module
    raw = "EAAS3cr3tApply98765"
    cid = gc.submit_change(
        "provider", "Provedor auditado", "ana.analista",
        {"name": "fake-chain", "type": "fake", "api_key": raw},
    )["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    before = len(srv._AUDIT)
    gc.apply_change(cid, "carla.mrm")
    chain = list(srv._AUDIT)
    assert len(chain) > before, "apply must append to the audit chain"
    entry = chain[-1]
    assert entry.get("event") == "governance.apply"
    assert entry.get("change_id") == cid
    assert entry.get("applied_by") == "carla.mrm"
    assert "hash" in entry and "prev_hash" in entry and "seq" in entry  # chain fields stamped
    assert raw not in json.dumps(chain, default=str)  # secret never reaches the trail
