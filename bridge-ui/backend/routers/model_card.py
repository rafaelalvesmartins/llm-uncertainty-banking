# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Model Card / Model Inventory endpoint — SR 11-7 §IV evidence.

SR 11-7 (Fed / OCC model risk management) §IV "Model Development,
Implementation, and Use" expects a documented model inventory: identity,
intended use, components, controls, limitations, and ownership. This endpoint
assembles that card from the SAME runtime fingerprints the audit trail and the
SR 11-7 crosswalk already pin (version, prompt/corpus fingerprints, backend
identity, guard threshold, DQ rule counts), so the card can never silently
drift from what is actually running.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


def _server() -> ModuleType:
    # Reuse whichever ``server`` module is already loaded so this router's reads
    # hit the SAME module globals as the hot path (uvicorn runs ``server:app``;
    # tests ``import server``). Mirrors routers/compliance.py.
    import sys

    mod = sys.modules.get("server") or sys.modules.get("backend.server")
    if mod is not None:
        return mod
    try:
        import server  # type: ignore[no-redef]
    except ImportError:
        from backend import server
    return server


def _build_model_card(s: ModuleType) -> dict[str, Any]:
    """Assemble the model card from live ``server`` module state."""
    backend = getattr(s._BACKEND, "name", "fake")
    is_real = bool(getattr(s._BACKEND, "is_real", False))
    threshold = round(float(s._RUNTIME_GUARD_THRESHOLD), 3)
    doc_count = s._DOC_STORE.size
    dq_in = len(s._DQ_INPUT.rules)
    dq_out = len(s._DQ_OUTPUT.rules)

    backend_limitation = (
        "Real backend active — responses subject to model variation."
        if is_real
        else "The default backend is the FakeBackend (predefined responses, no real LLM, no real banking data)."
    )

    return {
        "title": "Model Card — Bridge Banking AI",
        "sr_11_7_section": "IV — Development, Implementation, and Use",
        "identity": {
            "name": "Bridge Banking AI",
            "model_id": "bridge-pipeline",
            "version": "0.2.0",
            "type": "LLM pipeline with uncertainty guard (intent → RAG → agent → guard)",
            "owner": "Rafael Martins Alves",
            "lifecycle_stage": "Demo / development",
        },
        "runtime": {
            "backend": backend,
            "backend_is_real": is_real,
            "prompt_fingerprint": s._PROMPT_FINGERPRINT,
            "corpus_fingerprint": s._CORPUS_FINGERPRINT,
            "corpus_doc_count": doc_count,
            "dq_input_rules": dq_in,
            "dq_output_rules": dq_out,
            "guard_threshold": threshold,
        },
        "intended_use": {
            "purpose": (
                "Banking service triage: classifies the customer's intent, "
                "grounds the response in documents (RAG), and releases only responses with "
                "sufficient confidence — the rest is flagged or escalated to a human."
            ),
            "users": "Bank service team; the demo exposes the observability and governance view.",
            "in_scope": "24 intents across 3 families: banking, fraud, and security.",
            "out_of_scope": [
                "Real transaction execution (PIX, TED, payments) — the demo never moves money.",
                "Credit, investment, or financial advisory decisions.",
                "Replacing the human agent in fraud, crisis, or high-risk cases (always escalates).",
            ],
        },
        "architecture": [
            {
                "name": "Pipeline",
                "detail": (
                    "12 stages: dq_input → data_governance → cache → complexity → memory → "
                    "RAG → intent → agent → guard → cache_store → dq_output → audit."
                ),
            },
            {
                "name": "Intent classifier",
                "detail": "24 intents (banking / fraud / security), confidence by keywords.",
            },
            {
                "name": "Agents",
                "detail": "3 registered agents (chatbot, smart_payments, call_center) with handoffs.",
            },
            {
                "name": "RAG",
                "detail": f"Real TF-IDF retrieval over {doc_count} preloaded documents.",
            },
            {
                "name": "Uncertainty guard",
                "detail": f"Runtime threshold {threshold:.2f}; decides PASSTHROUGH / FLAG / REASK / ESCALATE.",
            },
        ],
        "controls": [
            {
                "name": "Uncertainty guard",
                "detail": "Every response passes through the guard (stage 9); fraud and security always escalate, regardless of confidence.",
            },
            {
                "name": "Tamper-evident audit",
                "detail": "sha256 hash chain (prev_hash ‖ payload) records every decision; verify/replay detect silent edits.",
            },
            {
                "name": "Data Governance (LGPD)",
                "detail": "PII masking (card, CPF, passport) before persisting to the audit trail.",
            },
            {
                "name": "Data Quality",
                "detail": f"{dq_in} input rules (incl. prompt-injection blocking) + {dq_out} output rules.",
            },
            {
                "name": "Drift detection",
                "detail": "TV-distance between baseline and current window; manual or automatic rebaseline.",
            },
            {
                "name": "Crosswalk SR 11-7",
                "detail": "Maps the 3 pillars (Conceptual Soundness, Outcome Analysis, Ongoing Monitoring) — see SR 11-7 Compliance panel.",
            },
        ],
        "limitations": [
            backend_limitation,
            "Calibration (ECE/Brier/AUROC) is genuinely computed over the catalog's labeled samples; there is no production benchmark for the fake backend, so the other SR 11-7 targets remain synthetic/pending.",
            "Personas and RAG corpus are pre-seeded (MOCK); TF-IDF retrieval runs for real over them.",
            "SQLite persistence (demo); the governance review dates below are illustrative.",
        ],
        "governance": {
            "owner": "Rafael Martins Alves",
            "review_cadence": "Quarterly (demo placeholder)",
            "status": "Controlled demo — gaps documented in DEMO_SCOPE.md.",
            "evidence": "Version / prompt / corpus pinned by fingerprint and cross-referenceable with the audit timestamps.",
        },
    }


@router.get("/model-card")
def model_card() -> dict[str, Any]:
    """Return the Model Card / inventory (SR 11-7 §IV) for the dashboard panel."""
    return _build_model_card(_server())


__all__ = ["router"]
