# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Per-channel firewall — a governed ``channel_policy`` carries an intent allow-list;
the /query pipeline ESCALATEs any off-list intent (default-deny), regardless of
confidence. Mirrors a bank restricting a public channel (e.g. WhatsApp) to a few
low-risk request types and handing everything else to a human."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

# Import gc under the SAME module name the /query pipeline resolves ("routers.…"),
# so this test and server.py share ONE module instance (and one in-memory DB) —
# importing via "backend.routers.…" would create a divergent instance the pipeline
# never sees (the documented two-instance trap).
from routers import governance_changes as gc  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    # Governance store in memory so the pipeline's policy read and this test's policy
    # writes share one clean DB; cache off so we exercise the main guard path.
    monkeypatch.setattr(gc, "_DB_PATH", ":memory:")
    monkeypatch.setattr(gc, "_DB", None)
    monkeypatch.setattr(server, "_RUNTIME_CACHE_ENABLED", False)
    yield


def _set_channel_allowlist(channel: str, allowed: list[str]) -> None:
    """Propose → approve → apply a channel_policy through the governed flow."""
    cid = gc.submit_change(
        "channel_policy", f"firewall: {channel}", "ana.analista",
        {"name": channel, "allowed_intents": allowed},
    )["id"]
    gc.decide_change(cid, "approve", "bruno.validador")
    gc.apply_change(cid, "carla.mrm")


def _q(text: str, channel: str, customer: str) -> server.QueryRequest:
    return server.QueryRequest(query=text, customer_id=customer, channel=channel)


def test_offlist_intent_escalates_on_a_channel_with_an_allowlist() -> None:
    _set_channel_allowlist("whatsapp", ["balance"])
    # A PIX request classifies as 'pix' (normally by-confidence), but it is NOT on the
    # whatsapp allow-list → the firewall forces ESCALATE.
    out = server.query(_q("mandar pix de 100 para a minha mãe", "whatsapp", "fw-off"))
    assert out.decision == "ESCALATE"


def test_allowed_intent_is_not_force_escalated() -> None:
    _set_channel_allowlist("whatsapp", ["balance", "pix"])
    out = server.query(_q("mandar pix de 100 para a minha mãe", "whatsapp", "fw-on"))
    assert out.decision != "ESCALATE"  # pix is on the list → normal guard decision


def test_a_channel_without_a_policy_is_unrestricted() -> None:
    # No channel_policy on 'app' → the firewall does not force ESCALATE.
    out = server.query(_q("mandar pix de 100 para a minha mãe", "app", "fw-none"))
    assert out.decision != "ESCALATE"


def test_cache_hit_does_not_bypass_the_firewall(monkeypatch) -> None:
    # Cache ON for this test (the default fixture turns it off).
    monkeypatch.setattr(server, "_RUNTIME_CACHE_ENABLED", True)
    monkeypatch.setattr(
        server, "_CACHE", server.SemanticCache(similarity_threshold=0.85, max_entries=200, max_age_seconds=300.0)
    )
    # 1) No policy yet → a balance answer is cached under a normal decision.
    server.query(_q("quero ver o saldo da conta", "whatsapp", "fw-cache"))
    # 2) Restrict whatsapp to ONLY pix (balance is now off-list).
    _set_channel_allowlist("whatsapp", ["pix"])
    # 3) Repeat the balance query → cache HIT, but balance is off-list → must ESCALATE.
    #    (Without the cache-path firewall, the cached PASS answer would leak through.)
    out = server.query(_q("quero ver o saldo da conta", "whatsapp", "fw-cache"))
    assert out.decision == "ESCALATE"


def test_idempotent_replay_is_channel_scoped() -> None:
    _set_channel_allowlist("whatsapp", ["pix"])  # whatsapp: only pix; balance off-list
    # On 'app' (no policy) a balance query with an idempotency key is allowed + stored.
    out_app = server.query(
        server.QueryRequest(query="quero ver o saldo", customer_id="fw-idem", channel="app", idempotency_key="k1")
    )
    assert out_app.decision != "ESCALATE"
    # Same customer + key, but on restricted 'whatsapp' → must NOT replay the app
    # response; balance is off-list there → ESCALATE (idempotency is channel-scoped).
    out_wa = server.query(
        server.QueryRequest(query="quero ver o saldo", customer_id="fw-idem", channel="whatsapp", idempotency_key="k1")
    )
    assert out_wa.decision == "ESCALATE"
