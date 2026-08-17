# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""#B1.2 value-proportional guard + #3 informational-question unlock.

- The guard sizes a money-moving decision by transaction value (COAF R$10k line).
- A BRL amount is parsed only when currency-cued (so account/order numbers don't
  masquerade as a value).
- An informational question with no banking keyword is answerable by the LLM
  (PASSTHROUGH) instead of being REASK'd; greetings stay low-confidence.

Run from the project root::

    pytest bridge-ui/backend/test_value_gate_and_faq.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

apply_guard = server.apply_guard


# --- #B1.2 value-proportional guard -----------------------------------------


def test_value_gate_sizes_the_decision() -> None:
    # A confidently-classified transfer (conf .9, thr .7, low risk): the decision
    # scales with the amount — small releases, mid flags, large escalates (COAF).
    assert apply_guard(0.9, threshold=0.7, intent="transfer", amount=10.0)[0] == "PASSTHROUGH"
    assert apply_guard(0.9, threshold=0.7, intent="transfer", amount=5_000.0)[0] == "FLAG"
    assert apply_guard(0.9, threshold=0.7, intent="transfer", amount=5_000_000.0)[0] == "ESCALATE"


def test_unknown_amount_is_conservative_flag() -> None:
    # No parseable amount → review, never auto-release.
    assert apply_guard(0.9, threshold=0.7, intent="transfer", amount=None)[0] == "FLAG"


def test_high_risk_client_escalates_regardless_of_value() -> None:
    # The risk-proportional override fires before the value gate.
    decision, _ = apply_guard(0.9, threshold=0.7, intent="pix", risk_level=0.85, amount=10.0)
    assert decision == "ESCALATE"


def test_value_gate_only_applies_to_money_moving_intents() -> None:
    # A read-only intent is unaffected by a number in the text.
    assert apply_guard(0.75, threshold=0.7, intent="balance", amount=5_000_000.0)[0] == "PASSTHROUGH"


def test_extract_amount_is_currency_cued_only() -> None:
    assert server._extract_amount("transferir R$ 5.000.000,00 para Joao") == 5_000_000.0
    assert server._extract_amount("pix de R$ 50 para mae") == 50.0
    assert server._extract_amount("transferir 1,5 milhao") == 1_500_000.0
    assert server._extract_amount("manda 200 reais") == 200.0
    assert server._extract_amount("pagar R$ 1.250,00") == 1_250.0
    # An account/order number with no currency cue must NOT be read as an amount.
    assert server._extract_amount("transferir para conta 12345") is None


# --- #3 informational-question unlock ---------------------------------------


def test_informational_question_is_answerable_not_reasked() -> None:
    intent, conf = server.classify_intent("O que e o IOF?")
    assert intent == "general" and conf >= 0.7
    assert apply_guard(conf, threshold=0.7, intent=intent)[0] == "PASSTHROUGH"


def test_greeting_stays_low_confidence_reask() -> None:
    intent, conf = server.classify_intent("Ola, bom dia")
    assert intent == "general" and conf == 0.5
    assert apply_guard(conf, threshold=0.7, intent=intent)[0] == "REASK"


def test_value_gate_boundaries() -> None:
    # The COAF R$10k line and the R$1k FLAG line are inclusive — pin them so an
    # off-by-one (>= vs >) regression can't silently move a R$10k transfer to FLAG.
    def dec(amount: float) -> str:
        return apply_guard(0.9, threshold=0.7, intent="transfer", amount=amount)[0]

    assert dec(999.99) == "PASSTHROUGH"
    assert dec(1_000.0) == "FLAG"
    assert dec(9_999.99) == "FLAG"
    assert dec(10_000.0) == "ESCALATE"


def test_extract_amount_locale_and_degenerate() -> None:
    assert server._extract_amount("transferir 1.5 mil") == 1_500.0   # EN decimal in 'mil'
    assert server._extract_amount("transferir 1,5 mil") == 1_500.0   # pt-BR decimal
    assert server._extract_amount("R$ 1.5") == 1.5                    # lone EN decimal
    assert server._extract_amount("R$ 50,5") == 50.5                  # 1-digit pt-BR decimal
    assert server._extract_amount("R$ 5.000.000,00") == 5_000_000.0  # pt-BR thousands+decimal
    # 0 / anomalous -> None so the guard FLAGs (never a clean low-value release)
    assert server._extract_amount("transferir R$ 0,00 para joao") is None


def test_question_detector_is_anchored_not_substring() -> None:
    # Declarative statements that merely contain a cue mid-sentence must stay
    # low-confidence (REASK), not get bumped to a passing 0.7 and sent to the LLM.
    for stmt in (
        "reclamei porque o app travou",
        "fiz exatamente como voce mandou",
        "show me something",
    ):
        intent, conf = server.classify_intent(stmt)
        assert (intent, conf) == ("general", 0.5), f"{stmt!r} -> {(intent, conf)}"


def test_account_help_does_not_swallow_scam_or_phishing() -> None:
    # A social-engineering victim report must ESCALATE, not get password-reset advice.
    intent, conf = server.classify_intent("um funcionario do banco me ligou pedindo a senha")
    assert intent == "social_engineering"
    assert apply_guard(conf, threshold=0.7, intent=intent)[0] == "ESCALATE"
    # A phishing report (digit-substituted lookalike domain) routes to phishing -> ESCALATE.
    p_intent, p_conf = server.classify_intent("recebi link bradesc0-seguro.com pra atualizar senha")
    assert p_intent == "phishing"
    assert apply_guard(p_conf, threshold=0.7, intent=p_intent)[0] == "ESCALATE"
    # Legitimate self-service password help still routes to account_help.
    assert server.classify_intent("esqueci minha senha, como recupero?")[0] == "account_help"
    assert server.classify_intent("quero recuperar minha senha")[0] == "account_help"
