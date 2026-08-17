# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.challenge.drift_reasoning -- drift-event hypothesis generator.

For each :class:`lub.calibration.drift.DriftProfile` event, generate a
one-paragraph hypothesis about what changed, scored against k-NN
retrieval from :mod:`lub.evidence` over similar past cases.

Pure rule-based for v0.3; LLM-backed in v0.4 (see spec section 6 for why).

Spec: planning/24_CEC_Spec_2026-04-25.md section 1.2 + section 4 step 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DriftHypothesis:
    """One short reasoning artifact attached to a drift event.

    The hypothesis is a human-readable paragraph; the support evidence
    is a list of ledger row ids (k-NN neighbours) that justify it.
    """

    drift_event_id: str
    hypothesis: str  # one paragraph, ~50-100 words
    support_evidence_ids: list[str] = field(default_factory=list)
    similarity_score: float = 0.0  # max similarity over neighbours
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _classify_psi(psi: float) -> tuple[str, str]:
    """Map a PSI magnitude to (severity, qualitative-language) labels.

    Thresholds follow OCC 2011-12 (also used by
    :class:`lub.calibration.drift.DriftSeverity`):

    * < 0.10 -- none
    * < 0.25 -- moderate
    * else  -- significant
    """
    if psi < 0.10:
        return "none", "no material distributional shift"
    if psi < 0.25:
        return "moderate", "a moderate distributional shift"
    return "significant", "a significant distributional shift"


def _direction(reference_mean: float, current_mean: float) -> str:
    """Describe the direction of the confidence shift in plain English."""
    delta = current_mean - reference_mean
    if abs(delta) < 0.01:
        return "essentially flat confidence"
    if delta > 0:
        return f"confidence rose by {delta:+.2f}"
    return f"confidence fell by {delta:+.2f}"


def _resolve_drift_event(
    drift_event_id: str,
    ledger: Any,
    evidence_store: Any,
) -> dict[str, Any] | None:
    """Return a dict describing the drift event, or ``None`` if unknown."""
    for source in (ledger, evidence_store):
        events = getattr(source, "drift_events", None)
        if isinstance(events, dict) and drift_event_id in events:
            ev = events[drift_event_id]
            if isinstance(ev, dict):
                return ev
    return None


def _build_paragraph(
    severity: str,
    severity_phrase: str,
    direction_phrase: str,
    psi: float,
    n_neighbours: int,
    max_similarity: float,
    domain: str | None,
) -> str:
    """Compose the human-readable hypothesis paragraph."""
    domain_phrase = f"on the {domain} domain " if domain else ""
    if n_neighbours == 0:
        retrieval = (
            "No similar past drift events were found in the evidence store, "
            "so this hypothesis is based on the PSI magnitude alone."
        )
    else:
        retrieval = (
            f"The k-NN evidence store surfaced {n_neighbours} historically "
            f"similar windows (max cosine similarity {max_similarity:.2f}), "
            "supporting the hypothesis below."
        )

    if severity == "significant":
        action = (
            "Recommend an immediate calibration review and a Tier-2 spot "
            "check before letting the current threshold continue gating "
            "production answers."
        )
    elif severity == "moderate":
        action = (
            "Recommend monitoring this signal across the next two windows; "
            "if PSI remains above 0.10, escalate to a calibration review."
        )
    else:
        action = (
            "No action recommended; flagging is informational and the model "
            "is operating within OCC 2011-12 stability bounds."
        )

    return (
        f"PSI={psi:.3f} indicates {severity_phrase} {domain_phrase}with "
        f"{direction_phrase}. {retrieval} {action}"
    ).strip()


def explain_drift_event(
    drift_event_id: str,
    ledger: Any,
    evidence_store: Any,
    k: int = 5,
) -> DriftHypothesis:
    """Generate a :class:`DriftHypothesis` for the given drift event."""
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")

    event = _resolve_drift_event(drift_event_id, ledger, evidence_store) or {}

    psi = float(event.get("psi", 0.0))
    severity, severity_phrase = _classify_psi(psi)
    ref_mean = float(event.get("reference_mean", event.get("ref_mean", 0.5)))
    cur_mean = float(event.get("current_mean", event.get("cur_mean", 0.5)))
    direction_phrase = _direction(ref_mean, cur_mean)
    domain = event.get("domain")
    query_text = event.get("query_text") or (
        f"drift {severity} {direction_phrase} domain={domain or ''}"
    )

    support_ids: list[str] = []
    max_sim = 0.0
    n_neighbours = 0
    query_fn = getattr(evidence_store, "query", None)
    if callable(query_fn):
        try:
            neighbours = query_fn(query_text, k=k)
        except TypeError:
            neighbours = query_fn(query_text, k)
        n_neighbours = len(neighbours)
        for n in neighbours:
            sim = float(getattr(n, "cosine_similarity", 0.0))
            max_sim = max(max_sim, sim)
            ident = getattr(n, "id", None) or getattr(n, "question", "")
            if ident:
                support_ids.append(str(ident))

    paragraph = _build_paragraph(
        severity=severity,
        severity_phrase=severity_phrase,
        direction_phrase=direction_phrase,
        psi=psi,
        n_neighbours=n_neighbours,
        max_similarity=max_sim,
        domain=domain,
    )

    return DriftHypothesis(
        drift_event_id=drift_event_id,
        hypothesis=paragraph,
        support_evidence_ids=support_ids,
        similarity_score=max_sim,
        metadata={
            "severity": severity,
            "psi": psi,
            "reference_mean": ref_mean,
            "current_mean": cur_mean,
            "domain": domain,
            "k": k,
        },
    )


__all__ = ["DriftHypothesis", "explain_drift_event"]
