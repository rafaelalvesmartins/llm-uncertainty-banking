# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Datasets & Experiments — effective challenge, operationalized (product v1).

A bank's second-line validator needs to re-run a labelled validation battery on
every model/prompt change and FILE the pass/fail result (SR 11-7 effective
challenge). This module exposes the demonstrator's labelled intent battery
(`_INTENT_CATALOG`) as a versioned **Dataset**, and an **Experiment run** that
classifies every case through the live classifier + guard, scores predicted-vs-
expected, and returns a reproducible, content-hashed report — the same evidence
discipline as the model-risk package.

Deterministic, so the run is cached (the panel polls under dashboard load);
``?refresh=1`` re-runs (e.g. after a classifier change, to catch a regression).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from types import ModuleType

router = APIRouter()

_DATASET_ID = "intent-battery"
_RUN_CACHE: dict[str, Any] | None = None


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


def _cases() -> list[dict[str, str]]:
    """Labelled cases (input → expected intent) from the intent catalog."""
    s = _server()
    out: list[dict[str, str]] = []
    for spec in s._INTENT_CATALOG:
        name = spec["name"]
        for i, sample in enumerate(spec.get("samples", [])):
            out.append({"id": f"{name}-{i}", "input": sample, "expected_intent": name})
    return out


def _dataset_version(cases: list[dict[str, str]]) -> str:
    canonical = json.dumps(
        [(c["input"], c["expected_intent"]) for c in cases],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def run_experiment(refresh: bool = False) -> dict[str, Any]:
    """Classify every case through the live classifier and score pass/fail."""
    global _RUN_CACHE
    if _RUN_CACHE is not None and not refresh:
        return _RUN_CACHE
    s = _server()
    cases = _cases()
    results: list[dict[str, Any]] = []
    by_intent: dict[str, dict[str, int]] = {}
    for c in cases:
        predicted, conf = s.classify_intent(c["input"])
        ok = predicted == c["expected_intent"]
        results.append(
            {
                "id": c["id"],
                "input": c["input"],
                "expected": c["expected_intent"],
                "predicted": predicted,
                "confidence": round(conf, 3),
                "pass": ok,
            }
        )
        bi = by_intent.setdefault(c["expected_intent"], {"total": 0, "pass": 0})
        bi["total"] += 1
        bi["pass"] += 1 if ok else 0

    n_pass = sum(1 for r in results if r["pass"])
    failures = [
        {"id": r["id"], "input": r["input"], "expected": r["expected"], "predicted": r["predicted"]}
        for r in results
        if not r["pass"]
    ]
    digest = hashlib.sha256(
        json.dumps([(r["id"], r["pass"]) for r in results], sort_keys=True).encode("utf-8")
    ).hexdigest()

    _RUN_CACHE = {
        "dataset": _DATASET_ID,
        "dataset_version": _dataset_version(cases),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_cases": len(results),
        "n_pass": n_pass,
        "accuracy": round(n_pass / len(results), 4) if results else 0.0,
        "by_intent": by_intent,
        "failures": failures,
        "content_sha256": digest,
        "note": (
            "Deterministic experiment: classifies each labelled case through the REAL "
            "classifier and scores predicted-vs-expected. Reproducible sha256 hash over the "
            "verdicts — re-run after changing the classifier to detect regression. Fake/Ollama backend."
        ),
    }
    return _RUN_CACHE


@router.get("/datasets")
def datasets() -> dict[str, Any]:
    cases = _cases()
    return {
        "datasets": [
            {
                "id": _DATASET_ID,
                "name": "Labelled intent battery",
                "n_cases": len(cases),
                "version": _dataset_version(cases),
            }
        ]
    }


@router.get("/datasets/{dataset_id}")
def dataset_detail(dataset_id: str) -> dict[str, Any]:
    cases = _cases()
    return {"id": dataset_id, "n_cases": len(cases), "version": _dataset_version(cases), "cases": cases}


@router.get("/experiments/run")
def experiments_run(refresh: bool = False) -> dict[str, Any]:
    """Run the labelled battery through the live classifier (cached; ?refresh=1 re-runs)."""
    return run_experiment(refresh=refresh)


__all__ = ["router"]
