# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Tests for the abstract :class:`Estimator` base and its registry helpers."""

from __future__ import annotations

import pytest

from lub.types import Generation, UncertaintyResult
from lub.uncertainty.base import Estimator, get_estimator_cls, list_estimators
from lub.wrappers.dummy import DummyBackend


class _FakeEstimator(Estimator):
    """Minimal concrete subclass used to exercise base-class helpers."""

    REGISTRY_KEY = ""  # intentionally empty so auto-registration is skipped

    def score(self, backend, prompt, **kwargs):  # type: ignore[no-untyped-def]
        return UncertaintyResult(answer="x", confidence=0.5)


def test_validate_threshold_accepts_edges() -> None:
    assert _FakeEstimator._validate_threshold(0.0) == 0.0
    assert _FakeEstimator._validate_threshold(1.0) == 1.0


def test_validate_threshold_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="must be in .0, 1."):
        _FakeEstimator._validate_threshold(1.5)
    with pytest.raises(ValueError):
        _FakeEstimator._validate_threshold(-0.1)


def test_validate_n_samples_rejects_below_min() -> None:
    with pytest.raises(ValueError, match="n_samples"):
        _FakeEstimator._validate_n_samples(1, minimum=2)


def test_validate_temperature_zero_disallowed_by_default() -> None:
    with pytest.raises(ValueError, match="temperature"):
        _FakeEstimator._validate_temperature(0.0)


def test_validate_temperature_zero_ok_when_flag_set() -> None:
    assert _FakeEstimator._validate_temperature(0.0, allow_zero=True) == 0.0


def test_validate_temperature_rejects_negative() -> None:
    with pytest.raises(ValueError):
        _FakeEstimator._validate_temperature(-0.1, allow_zero=True)


def test_clip01_clamps_below_zero_and_above_one() -> None:
    assert _FakeEstimator._clip01(-0.5) == 0.0
    assert _FakeEstimator._clip01(1.2) == 1.0
    assert _FakeEstimator._clip01(0.3) == 0.3


def test_require_generations_raises_on_empty() -> None:
    with pytest.raises(RuntimeError, match="no generations"):
        _FakeEstimator._require_generations([])


def test_require_generations_passes_through_populated() -> None:
    gens = [Generation(text="x")]
    assert _FakeEstimator._require_generations(gens) is gens


def test_logprobs_or_empty_none_returns_empty() -> None:
    assert _FakeEstimator._logprobs_or_empty(Generation(text="x")) == []


def test_logprobs_or_empty_returns_copy_of_list() -> None:
    gen = Generation(text="x", logprobs=[-0.1, -0.2])
    out = _FakeEstimator._logprobs_or_empty(gen)
    assert out == [-0.1, -0.2]


def test_registry_contains_expected_core_estimators() -> None:
    keys = set(list_estimators())
    for required in ("token_logprob", "perplexity", "verbalized_1s", "conformal"):
        assert required in keys


def test_get_estimator_cls_round_trips() -> None:
    cls = get_estimator_cls("token_logprob")
    assert cls.REGISTRY_KEY == "token_logprob"
    # Class is a concrete Estimator subclass, so score(DummyBackend, "x") works.
    est = cls()
    r = est.score(DummyBackend(), "q")
    assert 0.0 <= r.confidence <= 1.0


def test_get_estimator_cls_unknown_raises_with_choices() -> None:
    with pytest.raises(ValueError, match="unknown estimator"):
        get_estimator_cls("not-a-real-estimator")


def test_subclass_without_name_does_not_register() -> None:
    before = dict(Estimator._registry)

    class _Unnamed(Estimator):
        REGISTRY_KEY = ""

        def score(self, backend, prompt, **kwargs):  # type: ignore[no-untyped-def]
            return UncertaintyResult(answer="", confidence=0.0)

    assert dict(Estimator._registry) == before


def test_subclass_with_name_auto_registers_and_can_be_removed() -> None:
    class _Named(Estimator):
        REGISTRY_KEY = "test_estimator_base_sentinel"

        def score(self, backend, prompt, **kwargs):  # type: ignore[no-untyped-def]
            return UncertaintyResult(answer="", confidence=0.0)

    try:
        assert "test_estimator_base_sentinel" in Estimator._registry
        assert get_estimator_cls("test_estimator_base_sentinel") is _Named
    finally:
        Estimator._registry.pop("test_estimator_base_sentinel", None)


def test_every_advertised_estimator_resolves_to_itself() -> None:
    """Registry round-trip invariant: every key ``list_estimators()`` advertises MUST resolve
    via ``get_estimator_cls()``, and the resolved class must register under that same key.

    Regression guard. ``_LAZY_REGISTRY`` used to be keyed by MODULE BASENAME while three
    modules register a *different* ``REGISTRY_KEY``:
        monte_carlo_dropout -> mc_dropout
        sar                 -> token_sar
        verbalized          -> verbalized_1s / verbalized_2s
    So the library advertised 3 names that ALWAYS raised ValueError (the CLI help even used
    'sar' as its example), and the 4 real estimators behind them were unreachable by name from
    a cold process. The headline "22 estimators" did not survive the most obvious inspection:
    instantiating each advertised estimator.
    """
    broken: list[tuple[str, str]] = []
    for key in list_estimators():
        try:
            cls = get_estimator_cls(key)
        except Exception as exc:  # noqa: BLE001 - we want to report any failure mode
            broken.append((key, f"{type(exc).__name__}"))
            continue
        if cls.REGISTRY_KEY != key:
            broken.append((key, f"resolves to a class registered as {cls.REGISTRY_KEY!r}"))
    assert not broken, f"advertised estimators that do not resolve to themselves: {broken}"


def test_the_real_registry_keys_are_reachable_by_name() -> None:
    """The 4 estimators whose module name differs from their REGISTRY_KEY must be reachable."""
    for key in ("mc_dropout", "token_sar", "verbalized_1s", "verbalized_2s"):
        cls = get_estimator_cls(key)
        assert cls.REGISTRY_KEY == key, f"{key} resolved to {cls.REGISTRY_KEY}"
