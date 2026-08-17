# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Demo-safe master switch: fake-by-default, never a real LLM in the exhibit.

Previously ``_select_backend`` defaulted to ``BRIDGE_USE_REAL_LLM=auto`` and silently
returned OllamaBackend when a model was loaded. BRIDGE_DEMO_SAFE=on (the new default)
is a hard floor that forces the deterministic FakeBackend regardless.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

try:
    from backend import backends as b
except ImportError:
    import backends as b  # type: ignore[no-redef]


def test_demo_safe_on_forces_fake_even_when_real_is_required(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_DEMO_SAFE", "on")
    monkeypatch.setenv("BRIDGE_USE_REAL_LLM", "required")  # would otherwise force/probe Ollama
    assert b.is_demo_safe() is True
    assert type(b._select_backend()).__name__ == "FakeBackend"


def test_demo_safe_off_allows_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_DEMO_SAFE", "off")
    monkeypatch.setenv("BRIDGE_USE_REAL_LLM", "off")  # opt out, but still no real LLM needed here
    assert b.is_demo_safe() is False
    assert type(b._select_backend()).__name__ == "FakeBackend"
