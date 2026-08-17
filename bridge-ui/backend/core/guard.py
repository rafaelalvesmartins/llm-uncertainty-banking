# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Uncertainty-guard decision logic (decoupling step 1).

Pure, self-contained functions extracted verbatim from server.py — no dependency
on server state. server.py re-exports `apply_guard` and `_extract_risk_level`, so
routers (playground, security, governance) and tests that call them via the
`_server()` surface keep working with zero change.
"""

from __future__ import annotations

import re


def _extract_risk_level(risk_text: str) -> float:
    """Parse free-text risk_profile into 0.0-1.0 (v13-fix Phase 2).

    Personas store risk as prose; this keyword-matches the severity. Markers are
    recognised in both Portuguese and English so EN-translated personas keep the
    same risk level (the PT markers are retained for back-compat + tests).
    Scale: 0.0 unknown · 0.2 BAIXO/LOW · 0.5 MEDIO/MEDIUM/vulnerability ·
    0.75 ALTO/HIGH · 0.85 PEP · 1.0 MUITO ALTO/VERY HIGH / victim_recurrent /
    hold automatico / AML sweep.

    Matching is whole-word so common substrings on free-text/edited personas
    don't spuriously trip a tier — e.g. "LOW" inside FOLLOW/ALLOW/BELOW/FLOW,
    or "HIGH" inside HIGHLY would over-state risk. Underscores are word chars,
    so VICTIM_RECURRENT still matches as a single token, and hyphens are
    boundaries so "MEDIUM-HIGH" still resolves to HIGH (0.75) as before.
    """
    s = (risk_text or "").upper()

    def has(*words: str) -> bool:
        return any(re.search(rf"\b{re.escape(w)}\b", s) for w in words)

    if has("VICTIM_RECURRENT", "HOLD AUTOMATICO", "SWEEP AML", "AML SWEEP"):
        return 1.0
    if has("MUITO ALTO", "VERY HIGH"):
        return 1.0
    if has("PEP", "PEP_ESCALATE", "EXPOSTA POLITICAMENTE", "POLITICALLY EXPOSED"):
        return 0.85
    if has("ALTO", "HIGH"):
        return 0.75
    if has("MEDIO", "MEDIUM", "VULNERABILIDADE", "VULNERABILITY"):
        return 0.5
    if has("BAIXO", "LOW"):
        return 0.2
    return 0.0


def apply_guard(
    confidence: float,
    threshold: float = 0.7,
    intent: str = "",
    risk_level: float = 0.0,
    amount: float | None = None,
) -> tuple[str, str]:
    """Simulate UncertaintyGuard decision.

    Intent override: fraud intents always ESCALATE regardless of confidence.
    SR 11-7 requires human review on high-risk transactions; a card_fraud
    report meets that threshold by definition. Without this override, a
    high-confidence fraud classification (0.95) would route to PASSTHROUGH,
    contradicting the agent's reply that promises a human handoff.
    """
    # v7 — safety intents always ESCALATE regardless of classifier confidence.
    if intent in (
        "crisis",
        "social_engineering",
        "illegal_activity",
        "aml_review",
        "third_party_data",
        "account_manipulation",
        "privilege_escalation",
        "discrimination",
        "phishing",
        "urgency_scam",
        "aml_suspect",
        "age_minor",
        "complaint_escalated",
        "prompt_leak",
    ):
        return ("ESCALATE", f"Safety intent ({intent}) — mandatory human review.")
    if intent == "non_pt":
        return ("REASK", "Query outside PT/EN — asking the customer to rephrase in a supported language.")
    if intent and ("_fraud" in intent or intent == "card_fraud"):
        return (
            "ESCALATE",
            "Fraud intent — bypassing the confidence gate; routing to anti-fraud human review.",
        )
    # v14 (#3) risk-proportional control: a HIGH-risk client (PEP / AML watch /
    # recurrent victim, risk_level >= 0.7) performing a SENSITIVE financial action
    # (transfer / pix / loan) goes to mandatory human review regardless of the
    # classifier's confidence. The same action for a low-risk client passes — the
    # control is proportional to WHO the client is, not just WHAT they ask
    # (SR 11-7 high-risk-transaction review; BCB 4.893 / COAF for PEPs).
    if risk_level >= 0.7 and intent in ("transfer", "pix", "loan"):
        return (
            "ESCALATE",
            f"High-risk client (risk_level={risk_level:.2f}) on a sensitive action ({intent}) — "
            "mandatory human review (risk-proportional control; PEP/AML/COAF).",
        )
    # v13-fix Phase 2: risk_level lifts the effective threshold so high-risk
    # personas (PEP, victim_recurrent, AML watch) FLAG/ESCALATE sooner.
    # Cap below 1.0 so a max-confidence classification can still release: a
    # high-risk client at the top slider must not be permanently locked out of a
    # legitimate read-only answer (money-moving actions are already covered by the
    # risk-proportional override above).
    effective_threshold = min(threshold + 0.2 * risk_level, 0.99)
    risk_note = f" (risk_level={risk_level:.2f})" if risk_level > 0 else ""
    # v16 (#B1) — decide by the intent's RISK CLASS, not only by classification
    # confidence. A confident classification means "we understood the request",
    # not "it is safe to auto-execute". Money-moving actions (transfer/pix/loan)
    # therefore never auto-PASSTHROUGH — they release to the agent only FLAGGED for
    # review; read-only/informational intents release directly above the threshold.
    # This removes the inversion where a balance inquiry was FLAGGED while a large
    # transfer PASSED THROUGH, purely because "transfer" matched more keywords.
    if intent in ("transfer", "pix", "loan"):
        if confidence < effective_threshold - 0.2:
            return "ESCALATE", f"Confidence too low on a money-moving action ({intent}){risk_note}; escalate to a human."
        if confidence < effective_threshold:
            return "REASK", f"Low confidence on a money-moving action ({intent}){risk_note}; ask the customer to clarify."
        # v17 (#B1.2) — value-proportional gate on a confidently-classified action:
        # >= R$10k escalates to a human (COAF reporting line); >= R$1k (or an
        # unspecified amount) flags for review; a small, known amount is released.
        if amount is not None and amount >= 10_000:
            return "ESCALATE", f"High-value {intent} (R$ {amount:,.2f} >= R$ 10k COAF line){risk_note} — mandatory human review."
        if amount is None or amount >= 1_000:
            shown = f"R$ {amount:,.2f}" if amount is not None else "amount unspecified"
            return "FLAG", f"Money-moving action ({intent}, {shown}) — released but flagged for review{risk_note}."
        return "PASSTHROUGH", f"Low-value {intent} (R$ {amount:,.2f} < R$ 1k){risk_note}; released."

    if confidence >= effective_threshold:
        return "PASSTHROUGH", f"Read-only/informational intent, confidence above the threshold{risk_note}; answer released."
    if confidence >= effective_threshold - 0.2:
        return "REASK", f"Confidence below the threshold{risk_note}; ask the customer to clarify."
    return "ESCALATE", f"Confidence too low{risk_note}; escalate to a human."


__all__ = ["apply_guard", "_extract_risk_level"]
