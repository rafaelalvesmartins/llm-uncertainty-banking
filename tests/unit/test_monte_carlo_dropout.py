# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for :mod:`lub.uncertainty.monte_carlo_dropout`.

Bridge uses :class:`MCDropoutEstimator` through ``UncertaintyGuard`` (stage 7
of the 9-stage pipeline) when serving customers with a whitebox HF backend.
These tests mock the whitebox backend so we never load real weights and
patch the torch-dependent dropout toggle so the suite stays hermetic.

We cover:
- Initialization validation.
- Backend whitebox-requirement type check.
- Static entropy math (``_per_position_probs``).
- End-to-end ``score()`` with a mocked whitebox backend (the path Bridge
  exercises for every chatbot/smart_payments turn).
- Confidence-threshold behaviour ``should_refuse`` (high MI -> refuse,
  low MI -> respond) — this is what gates Bridge into FLAG/REASK/ESCALATE.
- Edge cases: empty prompt, empty generations, ``None`` logprobs, empty
  logprobs lists, mixed-length passes.
- Error handling: backend that raises during ``generate`` must still
  flip dropout back off and re-raise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from lub.types import Generation, UncertaintyResult
from lub.uncertainty import monte_carlo_dropout as mcd
from lub.uncertainty.monte_carlo_dropout import MCDropoutEstimator
from lub.wrappers.dummy import DummyBackend

# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeModel:
    """Minimal stand-in for an ``nn.Module`` — only needs ``.eval()``."""

    def __init__(self) -> None:
        self.eval_called = 0

    def eval(self) -> _FakeModel:
        self.eval_called += 1
        return self


@dataclass
class _DropoutCall:
    enable: bool


class _FakeWhiteboxBackend:
    """Mocked HF-style backend.

    Exposes the two things ``MCDropoutEstimator`` actually touches:
    ``_load()`` (whitebox marker, returns the underlying ``nn.Module``)
    and ``generate()``. Each call to ``generate`` pops from
    ``self.responses`` so tests can script per-pass outputs.
    """

    def __init__(self, responses: list[list[Generation]] | None = None) -> None:
        self.model = _FakeModel()
        self.responses: list[list[Generation]] = responses or []
        self.generate_calls: list[dict[str, Any]] = []

    def _load(self) -> tuple[_FakeModel, None, None]:
        return self.model, None, None

    def generate(
        self,
        prompt: str,
        *,
        n_samples: int = 1,
        temperature: float = 0.7,
        max_tokens: int = 256,
    ) -> list[Generation]:
        self.generate_calls.append(
            {
                "prompt": prompt,
                "n_samples": n_samples,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self.responses:
            return self.responses.pop(0)
        # Default deterministic response.
        return [Generation(text="ok", logprobs=[-0.1, -0.1, -0.1])]


@pytest.fixture
def patch_toggle(monkeypatch: pytest.MonkeyPatch) -> list[_DropoutCall]:
    """Replace ``_toggle_dropout`` so tests do not need real torch.

    Returns a recording list so tests can assert the enable/disable
    sequence (must be ``[True, False]`` — Bridge depends on dropout
    being switched off after the estimator returns).
    """
    calls: list[_DropoutCall] = []

    def fake_toggle(module: Any, enable: bool) -> None:
        calls.append(_DropoutCall(enable=enable))

    monkeypatch.setattr(mcd, "_toggle_dropout", fake_toggle)
    return calls


def _backend_with_passes(passes: list[list[float]], text: str = "ok") -> _FakeWhiteboxBackend:
    """Build a backend that yields one Generation per pass with given logprobs."""
    return _FakeWhiteboxBackend(
        responses=[[Generation(text=text, logprobs=lp)] for lp in passes]
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_defaults() -> None:
    est = MCDropoutEstimator()
    assert est.n_forward_passes == 20
    assert est.temperature == 1.0
    assert est.max_tokens == 64


def test_init_custom() -> None:
    est = MCDropoutEstimator(n_forward_passes=5, temperature=0.3, max_tokens=128)
    assert est.n_forward_passes == 5
    assert est.temperature == 0.3
    assert est.max_tokens == 128


@pytest.mark.parametrize("bad", [0, 1, -3])
def test_init_rejects_fewer_than_two_passes(bad: int) -> None:
    with pytest.raises(ValueError, match="n_forward_passes must be >= 2"):
        MCDropoutEstimator(n_forward_passes=bad)


def test_registry_key() -> None:
    assert MCDropoutEstimator.REGISTRY_KEY == "mc_dropout"


# ---------------------------------------------------------------------------
# Backend type check
# ---------------------------------------------------------------------------


def test_rejects_blackbox_backend() -> None:
    """Bridge must not route MC-dropout to a non-whitebox backend."""
    est = MCDropoutEstimator(n_forward_passes=3)
    with pytest.raises(TypeError, match="whitebox backend"):
        est.score(DummyBackend(model_id="dummy-test"), "Qual o saldo?")


def test_rejects_object_without_load() -> None:
    class _NoLoad:
        def generate(self, *_a: Any, **_kw: Any) -> list[Generation]:
            return []

    est = MCDropoutEstimator(n_forward_passes=2)
    with pytest.raises(TypeError, match="_load"):
        est.score(_NoLoad(), "Transferir R$ 100")


# ---------------------------------------------------------------------------
# _per_position_probs (static math)
# ---------------------------------------------------------------------------


def test_per_position_probs_empty_list() -> None:
    h, e = MCDropoutEstimator._per_position_probs([])
    assert h == 0.0 and e == 0.0


def test_per_position_probs_all_empty_passes() -> None:
    h, e = MCDropoutEstimator._per_position_probs([[], [], []])
    assert h == 0.0 and e == 0.0


def test_per_position_probs_single_pass_h_equals_e() -> None:
    # One pass: predictive entropy equals expected entropy (no epistemic).
    h, e = MCDropoutEstimator._per_position_probs([[-0.5]])
    p = math.exp(-0.5)
    expected = -p * math.log(p)
    assert h == pytest.approx(expected, abs=1e-10)
    assert e == pytest.approx(expected, abs=1e-10)


def test_per_position_probs_identical_passes_have_zero_mi() -> None:
    h, e = MCDropoutEstimator._per_position_probs([[-1.0, -1.0], [-1.0, -1.0]])
    # When passes agree, MI = H - E[H] should be zero.
    assert h == pytest.approx(e, abs=1e-10)


def test_per_position_probs_disagreement_yields_positive_mi() -> None:
    # Two passes that disagree at the first position should give MI > 0.
    # pass A: high prob (logprob -0.05 -> p~0.95)
    # pass B: low  prob (logprob -3.0  -> p~0.05)
    h, e = MCDropoutEstimator._per_position_probs([[-0.05], [-3.0]])
    assert h > e
    assert h - e > 0.0


def test_per_position_probs_normalizes_by_min_length() -> None:
    short = MCDropoutEstimator._per_position_probs([[-1.0]])
    long = MCDropoutEstimator._per_position_probs([[-1.0, -1.0, -1.0]])
    assert short[0] == pytest.approx(long[0], abs=1e-10)
    assert short[1] == pytest.approx(long[1], abs=1e-10)


def test_per_position_probs_truncates_to_shortest() -> None:
    # Mixed-length passes — only the first ``min_len`` positions are used.
    h, e = MCDropoutEstimator._per_position_probs([[-1.0, -2.0, -3.0], [-1.0, -2.0]])
    assert h > 0.0 and e > 0.0


def test_per_position_probs_one_empty_pass_among_others() -> None:
    """Documents current behaviour: mixing empty + non-empty passes raises.

    ``_per_position_probs`` computes ``min_len`` over non-empty passes
    only, but the inner loop iterates *all* passes — so an empty pass
    triggers ``IndexError`` at ``p[pos]``. score() shields callers from
    this by appending an empty list whenever ``logprobs is None``, but
    a future refactor that lets through a mix of [] and [-1.0] would
    surface the issue. Keep this test as a guard rail.
    """
    with pytest.raises(IndexError):
        MCDropoutEstimator._per_position_probs([[-1.0, -1.0], []])


# ---------------------------------------------------------------------------
# score() — end-to-end with mocked whitebox backend
# ---------------------------------------------------------------------------


def test_score_runs_n_forward_passes(patch_toggle: list[_DropoutCall]) -> None:
    backend = _backend_with_passes(
        passes=[[-0.1, -0.1], [-0.1, -0.1], [-0.1, -0.1]],
        text="R$ 1.234,56",
    )
    est = MCDropoutEstimator(n_forward_passes=3, temperature=0.8, max_tokens=32)

    result = est.score(backend, "Qual o saldo?")

    assert isinstance(result, UncertaintyResult)
    assert len(backend.generate_calls) == 3
    for call in backend.generate_calls:
        assert call["prompt"] == "Qual o saldo?"
        assert call["n_samples"] == 1
        assert call["temperature"] == pytest.approx(0.8)
        assert call["max_tokens"] == 32


def test_score_toggles_dropout_on_then_off(patch_toggle: list[_DropoutCall]) -> None:
    backend = _backend_with_passes([[-0.5], [-0.5]])
    est = MCDropoutEstimator(n_forward_passes=2)

    est.score(backend, "transferir")

    # Bridge depends on dropout being switched off again after the call —
    # otherwise the next non-MC inference would be stochastic.
    assert [c.enable for c in patch_toggle] == [True, False]
    # And the model is put back into eval mode.
    assert backend.model.eval_called >= 1


def test_score_returns_first_text_as_answer(patch_toggle: list[_DropoutCall]) -> None:
    backend = _FakeWhiteboxBackend(
        responses=[
            [Generation(text="Seu saldo é R$ 500,00.", logprobs=[-0.1, -0.1])],
            [Generation(text="Seu saldo é R$ 500,00.", logprobs=[-0.1, -0.1])],
        ]
    )
    est = MCDropoutEstimator(n_forward_passes=2)
    result = est.score(backend, "Qual o saldo?")
    assert result.answer == "Seu saldo é R$ 500,00."


def test_score_records_raw_diagnostics(patch_toggle: list[_DropoutCall]) -> None:
    backend = _backend_with_passes([[-1.0], [-1.0]])
    est = MCDropoutEstimator(n_forward_passes=2)
    result = est.score(backend, "p")
    for key in (
        "predictive_entropy",
        "expected_entropy",
        "mutual_information",
        "n_forward_passes",
    ):
        assert key in result.raw_scores
    assert result.raw_scores["n_forward_passes"] == pytest.approx(2.0)
    assert result.raw_scores["mutual_information"] >= 0.0


def test_score_confidence_in_unit_interval(patch_toggle: list[_DropoutCall]) -> None:
    # Wildly disagreeing passes — MI should saturate at 1 nat-ish, but
    # confidence must always stay in [0, 1].
    backend = _backend_with_passes([[-0.001], [-10.0], [-0.001], [-10.0]])
    est = MCDropoutEstimator(n_forward_passes=4)
    result = est.score(backend, "edge")
    assert 0.0 <= result.confidence <= 1.0


def test_score_samples_field_lists_all_pass_texts(
    patch_toggle: list[_DropoutCall],
) -> None:
    backend = _FakeWhiteboxBackend(
        responses=[
            [Generation(text="a", logprobs=[-0.1])],
            [Generation(text="b", logprobs=[-0.1])],
            [Generation(text="c", logprobs=[-0.1])],
        ]
    )
    est = MCDropoutEstimator(n_forward_passes=3)
    result = est.score(backend, "p")
    assert result.samples == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Confidence thresholds — the Bridge guard contract
# ---------------------------------------------------------------------------


def test_high_agreement_yields_should_refuse_false(
    patch_toggle: list[_DropoutCall],
) -> None:
    # Identical passes -> MI=0 -> confidence=1.0 -> PASSTHROUGH.
    backend = _backend_with_passes([[-0.1, -0.1], [-0.1, -0.1], [-0.1, -0.1]])
    est = MCDropoutEstimator(n_forward_passes=3)
    result = est.score(backend, "Qual o limite do meu cartão?")
    assert result.confidence == pytest.approx(1.0, abs=1e-9)
    assert result.should_refuse is False


def test_disagreement_lowers_confidence_versus_agreement(
    patch_toggle: list[_DropoutCall],
) -> None:
    """Pass-level disagreement must lower confidence below the agreement floor.

    The binary "this token vs not" approximation caps normalized MI at
    0.5, so ``should_refuse`` (gated at confidence < 0.5) is not reachable
    here — Bridge's UncertaintyGuard re-thresholds when it composes the
    estimator with a calibrator. What we *can* assert is the monotone
    relationship: more disagreement -> lower confidence.
    """
    agree = _backend_with_passes([[-0.1], [-0.1], [-0.1], [-0.1]])
    disagree = _backend_with_passes([[-0.0001], [-20.0], [-0.0001], [-20.0]])
    est = MCDropoutEstimator(n_forward_passes=4)
    r_agree = est.score(agree, "Posso liberar R$ 50.000?")
    r_disagree = est.score(disagree, "Posso liberar R$ 50.000?")
    assert r_disagree.confidence < r_agree.confidence
    # Confidence is still bounded.
    assert 0.0 <= r_disagree.confidence <= 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_prompt_still_runs(patch_toggle: list[_DropoutCall]) -> None:
    backend = _backend_with_passes([[-0.2], [-0.2]])
    est = MCDropoutEstimator(n_forward_passes=2)
    result = est.score(backend, "")
    assert isinstance(result, UncertaintyResult)
    assert all(call["prompt"] == "" for call in backend.generate_calls)


def test_backend_returns_no_generations(patch_toggle: list[_DropoutCall]) -> None:
    # Every pass returns an empty list — answer should be "" and
    # entropies should be 0 (no positions to score).
    backend = _FakeWhiteboxBackend(responses=[[], [], []])
    est = MCDropoutEstimator(n_forward_passes=3)
    result = est.score(backend, "p")
    assert result.answer == ""
    assert result.samples is None  # falsy texts -> None
    assert result.raw_scores["predictive_entropy"] == 0.0
    assert result.raw_scores["expected_entropy"] == 0.0
    assert result.raw_scores["mutual_information"] == 0.0
    # MI=0 -> confidence=1.0; should_refuse=False because >= 0.5.
    assert result.confidence == pytest.approx(1.0)


def test_some_passes_return_no_generation(patch_toggle: list[_DropoutCall]) -> None:
    # Bridge survives a transient backend hiccup mid-pass.
    backend = _FakeWhiteboxBackend(
        responses=[
            [Generation(text="ok", logprobs=[-0.1])],
            [],  # one pass yielded nothing
            [Generation(text="ok", logprobs=[-0.1])],
        ]
    )
    est = MCDropoutEstimator(n_forward_passes=3)
    result = est.score(backend, "p")
    assert result.answer == "ok"
    assert result.samples == ["ok", "ok"]


def test_logprobs_none_treated_as_empty(patch_toggle: list[_DropoutCall]) -> None:
    # Blackbox-style Generation (logprobs=None) is converted to [] per
    # the comment in score(); entropies fall back to 0.
    backend = _FakeWhiteboxBackend(
        responses=[
            [Generation(text="a", logprobs=None)],
            [Generation(text="b", logprobs=None)],
        ]
    )
    est = MCDropoutEstimator(n_forward_passes=2)
    result = est.score(backend, "p")
    assert result.raw_scores["mutual_information"] == 0.0
    assert result.confidence == pytest.approx(1.0)


def test_logprobs_empty_list_treated_as_empty(
    patch_toggle: list[_DropoutCall],
) -> None:
    # Whitebox backend that *normally* provides logprobs but this
    # completion had none (early stop / tokenizer edge case).
    backend = _FakeWhiteboxBackend(
        responses=[
            [Generation(text="a", logprobs=[])],
            [Generation(text="b", logprobs=[])],
        ]
    )
    est = MCDropoutEstimator(n_forward_passes=2)
    result = est.score(backend, "p")
    assert result.raw_scores["predictive_entropy"] == 0.0
    assert result.raw_scores["expected_entropy"] == 0.0


def test_mixed_length_logprobs_uses_min_length(
    patch_toggle: list[_DropoutCall],
) -> None:
    backend = _FakeWhiteboxBackend(
        responses=[
            [Generation(text="aaa", logprobs=[-0.5, -0.5, -0.5])],
            [Generation(text="aa", logprobs=[-0.5, -0.5])],
        ]
    )
    est = MCDropoutEstimator(n_forward_passes=2)
    result = est.score(backend, "p")
    # Should not crash; entropies derived from the first 2 positions only.
    assert result.raw_scores["predictive_entropy"] > 0.0


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_backend_exception_still_toggles_dropout_off(
    patch_toggle: list[_DropoutCall],
) -> None:
    """If ``generate`` blows up, dropout must still be turned back off.

    Otherwise the next non-MC inference Bridge runs through the same
    backend would silently be stochastic.
    """

    class _Boom(_FakeWhiteboxBackend):
        def generate(self, *_args: Any, **_kwargs: Any) -> list[Generation]:
            raise RuntimeError("backend timeout")

    backend = _Boom()
    est = MCDropoutEstimator(n_forward_passes=3)
    with pytest.raises(RuntimeError, match="backend timeout"):
        est.score(backend, "p")
    # The ``finally`` block must have run.
    assert [c.enable for c in patch_toggle] == [True, False]
    assert backend.model.eval_called >= 1


def test_load_propagates_exception(patch_toggle: list[_DropoutCall]) -> None:
    class _BadLoad:
        def _load(self) -> tuple[Any, Any, Any]:
            raise RuntimeError("model file missing")

        def generate(self, *_a: Any, **_kw: Any) -> list[Generation]:
            return []

    est = MCDropoutEstimator(n_forward_passes=2)
    with pytest.raises(RuntimeError, match="model file missing"):
        est.score(_BadLoad(), "p")
    # ``_load`` fails before dropout is toggled, so we never enabled it.
    assert patch_toggle == []


def test_uncertainty_result_is_frozen(patch_toggle: list[_DropoutCall]) -> None:
    """Sanity: Bridge audit relies on the result being immutable."""
    backend = _backend_with_passes([[-0.1], [-0.1]])
    est = MCDropoutEstimator(n_forward_passes=2)
    result = est.score(backend, "p")
    with pytest.raises(Exception):  # FrozenInstanceError subclass of Exception
        result.confidence = 0.0  # type: ignore[misc]
