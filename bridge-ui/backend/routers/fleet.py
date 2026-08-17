# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Agent fleet / model inventory — the portfolio view (govern many, not one).

The EY agent-governance write-up frames the core need as a *structured inventory*
of every agent — owner, risk, data, cost/return — to govern at scale ("milhares
de agentes"). The Bridge demo governs ONE pipeline deeply; this endpoint puts that
pipeline into a fleet alongside seeded sibling agents (clearly MOCK) so the
dashboard shows the portfolio the platform is meant to oversee.

Honesty: only the first entry ("Bridge Banking AI") is this live deployment
(version + ECE pulled from runtime). The rest are seeded illustrative agents,
flagged ``live: false`` — same MOCK convention as the demo personas / RAG corpus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()


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


# Seeded sibling agents — illustrative bank AI systems (MOCK). They make the
# "govern a portfolio" story concrete without claiming to be real deployments.
_SEEDED_FLEET: list[dict[str, Any]] = [
    {
        "id": "fraud-pix",
        "name": "PIX Fraud Detection",
        "domain": "Anti-fraud",
        "owner": "Risk / Anti-fraud",
        "risk_tier": "alto",
        "lifecycle": "produção",
        "ece": 0.07,
        "cost_month_brl": 4200.0,
        "last_review": "2026-05-12",
        "frameworks": ["BCB 4.893", "SR 11-7"],
        "live": False,
    },
    {
        "id": "credito-pf",
        "name": "Consumer Credit Assistant",
        "domain": "Credit",
        "owner": "Retail Credit",
        "risk_tier": "alto",
        "lifecycle": "produção",
        "ece": 0.11,
        "cost_month_brl": 3100.0,
        "last_review": "2026-04-28",
        "frameworks": ["BCB 4.893", "EU AI Act", "SR 11-7"],
        "live": False,
    },
    {
        "id": "kyc-onboarding",
        "name": "Onboarding / KYC",
        "domain": "Compliance",
        "owner": "Compliance / AML",
        "risk_tier": "alto",
        "lifecycle": "produção",
        "ece": 0.09,
        "cost_month_brl": 2600.0,
        "last_review": "2026-05-30",
        "frameworks": ["BCB 4.893", "EU AI Act"],
        "live": False,
    },
    {
        "id": "cobranca",
        "name": "Smart Collections",
        "domain": "Credit recovery",
        "owner": "Collections",
        "risk_tier": "médio",
        "lifecycle": "homologação",
        "ece": None,
        "cost_month_brl": 1500.0,
        "last_review": "2026-05-20",
        "frameworks": ["BCB 4.893"],
        "live": False,
    },
    {
        "id": "reclamacoes",
        "name": "Complaint Classifier",
        "domain": "Customer service",
        "owner": "Customer service",
        "risk_tier": "baixo",
        "lifecycle": "produção",
        "ece": 0.06,
        "cost_month_brl": 900.0,
        "last_review": "2026-03-15",
        "frameworks": ["ISO 42001"],
        "live": False,
    },
    {
        "id": "risco-pj",
        "name": "Business Risk Analysis",
        "domain": "Business Credit",
        "owner": "Corporate Risk",
        "risk_tier": "alto",
        "lifecycle": "desenvolvimento",
        "ece": None,
        "cost_month_brl": 0.0,
        "last_review": "—",
        "frameworks": ["BCB 4.893", "BCBS 239"],
        "live": False,
    },
]


def _live_entry(s: ModuleType) -> dict[str, Any]:
    """This deployment as a fleet member — real version + ECE."""
    ece = None
    try:
        cal = s._load_live_calibration_metrics()
        ece = cal.get("ece", {}).get("value")
    except Exception:
        pass
    backend = getattr(s._BACKEND, "name", "fake")
    return {
        "id": "bridge-pipeline",
        "name": "Bridge Banking AI",
        "domain": "Customer service + uncertainty guard",
        "owner": "Rafael Martins Alves",
        "risk_tier": "alto",
        "lifecycle": "demo",
        "ece": ece,
        "cost_month_brl": 0.0,
        "last_review": "—",
        "frameworks": ["SR 11-7", "EU AI Act", "BCB 4.893"],
        "live": True,
        "backend": backend,
    }


@router.get("/fleet")
def fleet() -> dict[str, Any]:
    """Agent fleet / model inventory: this deployment + seeded sibling agents."""
    agents = [_live_entry(_server()), *_SEEDED_FLEET]
    return {
        "agents": agents,
        "n_agents": len(agents),
        "n_production": sum(1 for a in agents if a["lifecycle"] == "produção"),
        "n_high_risk": sum(1 for a in agents if a["risk_tier"] == "alto"),
        "cost_month_total_brl": round(sum(a.get("cost_month_brl") or 0.0 for a in agents), 2),
        "n_live": sum(1 for a in agents if a.get("live")),
    }


__all__ = ["router"]
