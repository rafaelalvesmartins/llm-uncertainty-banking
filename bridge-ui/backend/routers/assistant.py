# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Ask AI — a permission-gated copilot over the dashboard (product v5).

A small assistant that explains the Bridge panels and decisions in natural
language. It calls the REAL local LLM (Ollama) — this is the one feature that
genuinely needs a model — and degrades honestly when Ollama is unreachable
instead of faking an answer. Opt-in: the UI only calls it when the user asks.
"""

from __future__ import annotations

import json
import urllib.request
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()

_OLLAMA_URL = "http://localhost:11434"

_SYSTEM = (
    "You are the assistant for the 'Bridge Banking AI' dashboard, a banking-pipeline "
    "demonstrator with an uncertainty guard, PII masking (LGPD/BCB 4893), a semantic cache, "
    "calibration, and regulatory coverage (SR 11-7, NIST, EU AI Act). The tabs are: Service "
    "(real-time query), Observability (metrics/audit/drift), Catalog (agents/"
    "intents/RAG), Evaluation (datasets + experiments), Governance (Model Card, calibration, "
    "frameworks, fleet, evidence), and Integrations (LLM providers). The guard decides "
    "PASSTHROUGH/FLAG/REASK/ESCALATE by confidence vs. a threshold. Answer in English, "
    "concise (at most 4 sentences), only about this dashboard and AI governance. Do not invent "
    "data or numbers; if you don't know, say you don't know."
)


def _server() -> ModuleType:
    import sys

    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


class AskRequest(BaseModel):
    question: str


def ask(question: str) -> dict[str, Any]:
    s = _server()
    model = getattr(s, "_OLLAMA_MODEL", "llama3.1:8b")
    payload = {
        "model": model,
        "prompt": f"{_SYSTEM}\n\nQuestion: {question.strip()}\nAnswer:",
        "stream": False,
        "options": {"num_predict": 220, "temperature": 0.3},
    }
    try:
        request = urllib.request.Request(  # noqa: S310
            _OLLAMA_URL + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as r:  # noqa: S310
            data = json.loads(r.read())
        return {
            "answer": (data.get("response") or "").strip() or "(no answer)",
            "model": model,
            "engine": "ollama",
            "live": True,
        }
    except Exception as exc:  # noqa: BLE001 — degrade honestly, never fake an answer
        print(f"[assistant] ollama call failed: {exc!r}", flush=True)
        return {
            "answer": (
                f"The assistant requires Ollama (the real LLM) running at {_OLLAMA_URL} with the "
                f"model {model!r} — unavailable right now. Start Ollama to use it."
            ),
            "model": model,
            "engine": "ollama",
            "live": False,
        }


@router.post("/assistant/ask")
def assistant_ask(req: AskRequest) -> dict[str, Any]:
    """Answer a question about the dashboard using the local LLM (Ollama)."""
    return ask(req.question)


__all__ = ["router"]
