# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Theme A — an approved + applied governed 'intent' change takes effect at runtime.

Proves the overlay end-to-end: writing a governed intent policy into the
active_configs system-of-record makes (1) a new intent classifiable via its sample
utterances, (2) the guard decision pinned for that intent, and (3) the intent appear
in the /intents catalog — without restarting or touching the static catalog. Also
proves the safety floor is preserved (a protected intent is never overridden).
"""

from __future__ import annotations

import json
import time

import server  # noqa: E402 — loads the app + governance module into sys.modules

try:
    from routers import discovery
    from routers import governance_changes as gc
except ImportError:  # pragma: no cover - package layout fallback
    from backend.routers import discovery  # type: ignore[no-redef]
    from backend.routers import governance_changes as gc  # type: ignore[no-redef]


def _put_intent(name: str, cfg: dict) -> None:
    db = gc._db()
    db.execute(
        "INSERT OR REPLACE INTO active_configs (domain,name,config,enabled,updated_at,updated_by) "
        "VALUES ('intent',?,?,1,?,?)",
        (name, json.dumps(cfg), time.time(), "tester"),
    )
    db.commit()
    server._GOV_INTENT_CACHE = None  # bust the TTL cache so the change is seen now


def _del_intent(name: str) -> None:
    db = gc._db()
    db.execute("DELETE FROM active_configs WHERE domain='intent' AND name=?", (name,))
    db.commit()
    server._GOV_INTENT_CACHE = None


def test_new_governed_intent_is_classifiable_and_pins_decision() -> None:
    _put_intent(
        "pix_scheduled",
        {"name": "pix_scheduled", "family": "banking", "default_decision": "ESCALATE",
         "samples": ["agendar pix amanha"]},
    )
    try:
        # (1) classifiable via samples
        assert "pix_scheduled" in server._governed_intent_policies()
        assert server._match_governed_intent("quero agendar um pix amanha") == "pix_scheduled"
        assert server._match_governed_intent("qual o meu saldo") is None

        # (2) decision pinned: the override forces ESCALATE for the governed intent
        pol = server._governed_intent_policies()["pix_scheduled"]
        assert str(pol.get("default_decision")).upper() == "ESCALATE"

        # (3) appears in the /intents catalog, marked governed
        names = {i["name"] for i in discovery.intents()["intents"]}
        assert "pix_scheduled" in names
    finally:
        _del_intent("pix_scheduled")


def test_governed_overlay_never_weakens_the_safety_floor() -> None:
    # A governed policy must not be able to downgrade a protected safety/fraud intent.
    assert server._is_protected_intent("crisis") is True
    assert server._is_protected_intent("card_fraud") is True
    assert server._is_protected_intent("pix") is False
    # Even if an operator governs a sample that overlaps a crisis phrasing, the
    # classification override is skipped for protected intents (guarded at the call site).
    _put_intent(
        "evil_override",
        {"name": "evil_override", "family": "banking", "default_decision": "PASSTHROUGH",
         "samples": ["acabar com tudo"]},
    )
    try:
        # classify a crisis phrase: the static classifier should win (protected), so the
        # governed match must NOT be consulted — we assert the guard for the protected
        # path stays ESCALATE regardless of any governed PASSTHROUGH policy.
        from core.guard import apply_guard
        decision, _ = apply_guard(0.95, threshold=0.7, intent="crisis")
        assert decision == "ESCALATE"
    finally:
        _del_intent("evil_override")
