# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Risk-proportional control (#3) — the client's risk drives the decision.

A high-risk client (PEP / AML watch / recurrent victim) performing a sensitive
financial action escalates to human review; the same action for a low-risk
client passes. The control is proportional to WHO the client is, not just WHAT
they ask (SR 11-7 high-risk-transaction review; BCB 4.893 / COAF for PEPs).
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402


def test_high_risk_client_escalates_every_sensitive_action() -> None:
    for intent in ("transfer", "pix", "loan"):
        decision, reason = server.apply_guard(0.95, threshold=0.7, intent=intent, risk_level=0.85)
        assert decision == "ESCALATE", f"{intent} should escalate for a high-risk client"
        assert "risk-proportional" in reason


def test_low_risk_client_is_not_force_escalated_for_the_same_action() -> None:
    decision, _ = server.apply_guard(0.95, threshold=0.7, intent="transfer", risk_level=0.2)
    assert decision != "ESCALATE"  # low risk → ordinary threshold logic, not the risk override


def test_rule_does_not_overreach_to_read_only_intents() -> None:
    # a high-risk client just *reading* (balance) is not force-escalated by the rule.
    # Assert the real contract (not a dead PT phrase): the override did not fire.
    decision, reason = server.apply_guard(0.95, threshold=0.7, intent="balance", risk_level=0.85)
    assert decision != "ESCALATE"
    assert "risk-proportional" not in reason  # the sensitive-action override did not fire


def test_extract_risk_level_whole_word_no_substring_false_positives() -> None:
    # common substrings must NOT trip a tier (follow/allow/below/flow -> LOW; highly -> HIGH)
    f = server._extract_risk_level
    for benign in (
        "client tends to follow advice",
        "we allow overdraft",
        "see note below",
        "steady cash flow",
        "highly cooperative customer",
    ):
        assert f(benign) == 0.0, f"{benign!r} should not match any risk tier"
    # real tier words still resolve
    assert f("risco BAIXO") == 0.2
    assert f("MEDIUM-HIGH exposure") == 0.75
    assert f("PEP_ESCALATE active") == 0.85
    assert f("VICTIM_RECURRENT flag") == 1.0


def test_pep_risk_text_parses_high() -> None:
    # the C003-PEP seed text must map to a high risk_level so the rule triggers
    level = server._extract_risk_level(
        "ALTO (AML). Toda operacao acima R$ 5k requer revisao manual + COAF. PEP_ESCALATE ativo."
    )
    assert level >= 0.7


# --- #B1: decide by intent risk class, not classification confidence ----------


def test_money_moving_action_never_auto_passthrough() -> None:
    # A confident transfer/pix/loan is FLAGGED for review, never auto-released,
    # even for a low-risk client: "understood the request" != "safe to execute".
    for intent in ("transfer", "pix", "loan"):
        decision, _ = server.apply_guard(0.95, threshold=0.7, intent=intent, risk_level=0.0)
        assert decision == "FLAG", f"{intent} at high confidence should FLAG, got {decision}"


def test_read_only_intent_passthrough_at_threshold() -> None:
    # A trivial read-only inquiry releases directly above the threshold — no
    # review-queue churn. This is the op that used to FLAG (conf 0.75 < 0.85).
    decision, _ = server.apply_guard(0.75, threshold=0.7, intent="balance", risk_level=0.0)
    assert decision == "PASSTHROUGH"


def test_no_risk_inversion_balance_vs_transfer() -> None:
    # Headline fix: reading a balance must not be treated as riskier than moving
    # money. Previously balance (0.75)->FLAG while transfer (0.90)->PASSTHROUGH.
    bal, _ = server.apply_guard(0.75, threshold=0.7, intent="balance")
    trf, _ = server.apply_guard(0.90, threshold=0.7, intent="transfer")
    assert bal == "PASSTHROUGH" and trf == "FLAG"
