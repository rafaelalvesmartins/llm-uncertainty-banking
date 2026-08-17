# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""R4a regression — Ollama circuit-breaker thread-safety (architecture audit 2026-06-14).

Covers:
  (a) breaker opens after _OLLAMA_BREAKER_THRESHOLD failures within the window.
  (b) breaker stays closed when fewer than threshold failures occur.
  (c) thread-safety smoke: 20 concurrent threads each calling _ollama_record_failure
      must produce no exception and leave the breaker in a coherent state.

Run from the project root::

    pytest bridge-ui/backend/test_ollama_resilience.py -v
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

try:
    import backend.backends as backends_mod  # package-mode
except ImportError:
    import backends as backends_mod  # type: ignore[no-redef]  # module-mode


def _reset_breaker(monkeypatch, fake_now: float) -> None:
    """Reset breaker state and freeze time.time() to *fake_now*."""
    backends_mod._OLLAMA_FAILURES.clear()
    monkeypatch.setattr(backends_mod, "_OLLAMA_BREAKER_OPEN_UNTIL", 0.0)
    monkeypatch.setattr(time, "time", lambda: fake_now)


# ---------------------------------------------------------------------------
# (a) breaker opens after THRESHOLD failures within the window
# ---------------------------------------------------------------------------

def test_breaker_opens_after_threshold_failures(monkeypatch) -> None:
    T0 = 1_000_000.0  # arbitrary frozen epoch
    _reset_breaker(monkeypatch, T0)

    threshold = backends_mod._OLLAMA_BREAKER_THRESHOLD

    # Fire exactly threshold failures — all at T0 (within the 60-s window).
    for _ in range(threshold):
        assert not backends_mod._ollama_breaker_open(), "breaker should be closed before threshold"
        backends_mod._ollama_record_failure()

    # The last call should have tripped the breaker.
    assert backends_mod._OLLAMA_BREAKER_OPEN_UNTIL > T0, (
        "_OLLAMA_BREAKER_OPEN_UNTIL was not advanced after threshold failures"
    )
    assert backends_mod._ollama_breaker_open(), "breaker should be open after threshold failures"


# ---------------------------------------------------------------------------
# (b) breaker stays closed below threshold
# ---------------------------------------------------------------------------

def test_breaker_stays_closed_below_threshold(monkeypatch) -> None:
    T0 = 2_000_000.0
    _reset_breaker(monkeypatch, T0)

    threshold = backends_mod._OLLAMA_BREAKER_THRESHOLD

    # Fire threshold-1 failures.
    for _ in range(threshold - 1):
        backends_mod._ollama_record_failure()

    assert not backends_mod._ollama_breaker_open(), (
        "breaker must stay closed with fewer than threshold failures"
    )
    assert backends_mod._OLLAMA_BREAKER_OPEN_UNTIL == 0.0, (
        "_OLLAMA_BREAKER_OPEN_UNTIL must not have been set"
    )


# ---------------------------------------------------------------------------
# (c) thread-safety smoke: 20 threads, no exception, coherent end-state
# ---------------------------------------------------------------------------

def test_concurrent_record_failure_is_safe(monkeypatch) -> None:
    """20 threads concurrently calling _ollama_record_failure must not raise
    and the resulting breaker state must be coherent (open XOR closed, never
    partially written).
    """
    T0 = 3_000_000.0
    _reset_breaker(monkeypatch, T0)

    THREADS = 20
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            backends_mod._ollama_record_failure()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = [ex.submit(_worker) for _ in range(THREADS)]
        for f in futs:
            f.result()  # re-raises if _worker itself raised outside try/except

    assert not errors, f"exceptions in worker threads: {errors}"

    # Coherence: _OLLAMA_BREAKER_OPEN_UNTIL must be either exactly 0.0
    # (never tripped) or > T0 (cleanly tripped) — never a partial float.
    open_until = backends_mod._OLLAMA_BREAKER_OPEN_UNTIL
    assert open_until == 0.0 or open_until > T0, (
        f"_OLLAMA_BREAKER_OPEN_UNTIL={open_until!r} is neither 0.0 nor > T0={T0}"
    )

    # Because THREADS >= threshold, the breaker must have been tripped at
    # least once. After the first trip _OLLAMA_FAILURES is cleared and the
    # subsequent calls may or may not re-trip depending on ordering — but
    # open_until must be > T0 at minimum.
    threshold = backends_mod._OLLAMA_BREAKER_THRESHOLD
    if THREADS >= threshold:
        assert open_until > T0, (
            "breaker should have been tripped at least once with THREADS >= threshold"
        )
