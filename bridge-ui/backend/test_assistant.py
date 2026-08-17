# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Ask AI assistant (product v5) — Ollama-backed, honest degradation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402,F401

try:
    from backend.routers import assistant as asst  # noqa: E402
except ImportError:
    from routers import assistant as asst  # type: ignore[no-redef]  # noqa: E402


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._b

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *a: object) -> bool:
        return False


def test_assistant_returns_the_ollama_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        asst.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResp({"response": "O guard decide PASSTHROUGH/FLAG/REASK/ESCALATE pela confiança."}),
    )
    out = asst.ask("o que é o guard?")
    assert out["live"] is True
    assert out["engine"] == "ollama"
    assert "guard" in out["answer"].lower()


def test_assistant_degrades_honestly_when_ollama_is_down(monkeypatch) -> None:
    def _boom(*a: object, **k: object) -> object:
        raise OSError("connection refused")

    monkeypatch.setattr(asst.urllib.request, "urlopen", _boom)
    out = asst.ask("oi")
    assert out["live"] is False
    assert "ollama" in out["answer"].lower()  # honest, names the dependency
