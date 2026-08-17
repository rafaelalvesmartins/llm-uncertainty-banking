# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Integrations provider inventory (product v3).

Asserts the provider list + honest Ollama reachability. The Ollama probe is
monkeypatched so the test is deterministic (no network dependency in CI).

Run from the project root::

    pytest bridge-ui/backend/test_integrations.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402,F401

try:
    from backend.routers import integrations as intg  # noqa: E402
except ImportError:
    from routers import integrations as intg  # type: ignore[no-redef]  # noqa: E402


def test_integrations_lists_providers(monkeypatch) -> None:
    monkeypatch.setattr(intg, "_ollama_status", lambda: {"reachable": True, "models": ["llama3.1:8b", "qwen2.5:7b"]})
    p = intg.build_integrations(refresh=True)
    ids = {x["id"] for x in p["providers"]}
    assert {"fake", "ollama", "openai", "anthropic"} <= ids
    assert p["active_backend"]
    assert p["switch_note"]
    oll = next(x for x in p["providers"] if x["id"] == "ollama")
    assert oll["reachable"] is True
    assert "llama3.1:8b" in oll["models"]
    # at most one backend is the live/active one
    assert sum(1 for x in p["providers"] if x.get("live")) <= 1


def test_unreachable_ollama_is_honest(monkeypatch) -> None:
    monkeypatch.setattr(intg, "_ollama_status", lambda: {"reachable": False, "models": []})
    p = intg.build_integrations(refresh=True)
    oll = next(x for x in p["providers"] if x["id"] == "ollama")
    assert oll["reachable"] is False
    openai = next(x for x in p["providers"] if x["id"] == "openai")
    assert openai["status"] == "not_configured"


def test_no_api_keys_or_secrets_surfaced(monkeypatch) -> None:
    # the inventory must never carry credentials — only env-config instructions.
    monkeypatch.setattr(intg, "_ollama_status", lambda: {"reachable": True, "models": []})
    p = intg.build_integrations(refresh=True)
    blob = repr(p).lower()
    for bad in ("api_key", "apikey", "secret", "password", "bearer", "sk-"):
        assert bad not in blob
