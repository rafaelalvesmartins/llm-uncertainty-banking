# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared pytest fixtures.

All tests run hermetically: no network calls, no real model loading, no
writes outside of pytest-managed ``tmp_path``. The :func:`dummy_backend`
fixture gives every test a fresh deterministic backend; :func:`tmp_cache`
points :class:`lub.config.LubConfig` at a throwaway cache directory.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lub.benchmarks.base import _LAZY_REGISTRY as _DATASET_LAZY_REGISTRY
from lub.benchmarks.base import Dataset
from lub.config import LubConfig
from lub.uncertainty.base import Estimator
from lub.wrappers.base import _LAZY_REGISTRY, ModelBackend
from lub.wrappers.dummy import DummyBackend


@pytest.fixture(autouse=True)
def _reset_registries() -> Iterator[None]:
    """Snapshot and restore class registries between tests.

    Prevents test-defined subclasses from polluting the global registry.
    Only removes keys that were added during the test ? keys that existed
    before (including lazy-loaded ones from previous tests) are kept.
    Production lazy entries (backends and datasets listed in their
    respective ``_LAZY_REGISTRY`` tables) are preserved unconditionally:
    re-importing a cached module is a no-op so ``__init_subclass__``
    cannot re-register, and popping ``sys.modules`` to force a reload
    breaks module-identity aliases held elsewhere (e.g.
    ``lub.domains.banking.br_regulatory``).
    """
    backend_before = set(ModelBackend._registry)
    estimator_before = set(Estimator._registry)
    dataset_before = set(Dataset._registry)
    yield
    for key in list(ModelBackend._registry):
        if key not in backend_before and key not in _LAZY_REGISTRY:
            del ModelBackend._registry[key]
    for key in list(Estimator._registry):
        if key not in estimator_before:
            del Estimator._registry[key]
    for key in list(Dataset._registry):
        if key not in dataset_before and key not in _DATASET_LAZY_REGISTRY:
            del Dataset._registry[key]


@pytest.fixture
def dummy_backend() -> DummyBackend:
    """Fresh deterministic :class:`DummyBackend` for a single test."""
    return DummyBackend(model_id="dummy-test")


@pytest.fixture
def backend() -> DummyBackend:
    """Alias used by conformal and estimator tests."""
    return DummyBackend(model_id="dummy-0")


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point ``LUB_CACHE_DIR`` at a pytest tmp directory for the test's duration."""
    cache_dir = tmp_path / "lub-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LUB_CACHE_DIR", str(cache_dir))
    cfg = LubConfig()
    cfg.ensure_cache_dir()
    yield cache_dir
