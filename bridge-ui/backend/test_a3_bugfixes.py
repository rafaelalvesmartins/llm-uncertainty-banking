# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Regression tests for the three Bloco-A3 bugs found in UI testing.

Each test fails on the pre-fix code and passes after the fix:

  A3.1  "clonaram meu cartao" was classified as `card` (FLAG + fatura
        template) because the fraud marker stems were "clonad"/"clonag"
        and missed the verb conjugation "clonaram". Now `card_fraud`
        → ESCALATE → antifraud canned response.
  A3.2  /stats iterated the watchdog deques directly while concurrent
        /query handlers appended to them, raising "RuntimeError: deque
        mutated during iteration". Now it snapshots to a list first.
  A3.3  /query/stream emitted the pipeline result as a raw `event: result`
        when the heartbeat loop consumed it before the worker thread was
        observed dead, so the `event: done` the UI waits on never fired
        ("Stream ended without a done event"). Now both loops translate
        the terminal message identically.

Run from the project root::

    pytest bridge-ui/backend/test_a3_bugfixes.py -v
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402  — must follow sys.path setup

# ---------------------------------------------------------------------------
# A3.1 — fraud verb conjugations route to card_fraud, not card
# ---------------------------------------------------------------------------


class TestFraudConjugationClassification:
    """A 'clonaram meu cartao' report must escalate to antifraud, never be
    answered with the fatura template. Covers verb conjugations the old
    'clonad'/'clonag' stems missed while keeping the participle forms."""

    @pytest.mark.parametrize(
        "query",
        [
            "clonaram meu cartao",
            "clonaram meu cartão",
            "alguem clonou meu cartao",
            "meu cartao foi clonado",  # participle — must still work
            "cartao clonado, o que faco?",
            # v2-prompt requested markers (roubad / nao-reconheco) WITH a card
            # keyword, so they reach the card_fraud intent (not just the reply).
            "meu cartao foi roubado",
            "cartão roubado",
            "compra que nao reconheco no cartao",
        ],
        ids=lambda q: q[:25],
    )
    def test_card_fraud_conjugations(self, query: str) -> None:
        intent, conf = server.classify_intent(query)
        assert intent == "card_fraud", (
            f"{query!r} classified as {intent!r}; expected 'card_fraud'. "
            f"The fraud marker stem must catch this conjugation."
        )

        decision, _reason = server.apply_guard(conf, intent=intent)
        assert decision == "ESCALATE", (
            f"{query!r} → {decision!r}; fraud must ESCALATE to antifraud."
        )

        reply = server._CallCenterAgent().handle(query, context={})
        assert reply == server._RESPONSES["card_fraud"], (
            f"{query!r} did not get the card_fraud canned reply — it would "
            f"have answered with the fatura template."
        )

    def test_innocent_card_query_still_routes_to_card(self) -> None:
        """The fix must not over-trigger: a plain fatura question stays `card`."""
        intent, _conf = server.classify_intent("qual o valor da fatura do meu cartao?")
        assert intent == "card", (
            f"Innocent card query mis-classified as {intent!r}; the 'clon' "
            f"stem should not fire on non-fraud card queries."
        )

    @pytest.mark.parametrize(
        "query",
        ["nao reconheco essa compra", "compra que nao reconheço"],
        ids=lambda q: q[:25],
    )
    def test_unrecognized_charge_without_card_kw_still_gets_fraud_reply(self, query: str) -> None:
        """A 'compra não reconhecida' with NO card/transfer/pix keyword does not
        reach the card_fraud *intent* (classify_intent finds no base intent to
        append _fraud to, so it routes to 'complaint'), but the call-center
        agent's own fraud-marker check still returns the antifraud reply — never
        the fatura template. Pin that behavior so it can't silently regress."""
        intent, _conf = server.classify_intent(query)
        assert intent == "complaint", (
            f"{query!r} (no card keyword) classified as {intent!r}; expected "
            f"'complaint' (fraud markers without a card kw route to complaint)."
        )
        reply = server._CallCenterAgent().handle(query, context={})
        assert reply == server._RESPONSES["card_fraud"], (
            f"{query!r} must still get the card_fraud antifraud reply via the "
            f"agent's marker check, not the generic complaint/fatura template."
        )


# ---------------------------------------------------------------------------
# A3.2 — /stats survives concurrent mutation of the watchdog deques
# ---------------------------------------------------------------------------


class TestStatsConcurrentDequeMutation:
    """Reproduces the 'deque mutated during iteration' RuntimeError by
    hammering the watchdog deques from a writer thread while reading /stats.
    Pre-fix this raised within a few iterations; post-fix it never does."""

    def test_stats_no_runtime_error_under_concurrent_append(self) -> None:
        import sys

        try:
            from backend.routers import metrics
        except ImportError:
            from routers import metrics  # type: ignore[no-redef]

        # Fill the deques so each read iterates a wide window (longer the
        # collision window, the more reliable the repro).
        now = time.time()
        for i in range(10_000):
            server._WATCHDOG_REQUEST_TS.append(now - i * 0.01)
            server._WATCHDOG_ERROR_TS.append(now - i * 0.02)

        stop = threading.Event()
        errors: list[BaseException] = []

        def writer() -> None:
            # Hot loop, no sleep: must append WHILE the reader iterates so the
            # pre-fix code (which iterates the deque directly) hits "deque
            # mutated during iteration".
            while not stop.is_set():
                ts = time.time()
                server._WATCHDOG_REQUEST_TS.append(ts)
                server._WATCHDOG_ERROR_TS.append(ts)

        # Shrink the GIL switch interval so the hot writer preempts the reader
        # MID-iteration (at the default 5ms a whole count_within can finish
        # before the writer is scheduled, and the race never shows). Restored
        # in finally. Pre-fix this raises within the first read or two and
        # breaks immediately; post-fix list() snapshots are atomic so the
        # loop runs to the short wall-clock deadline and passes.
        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-5)
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    out = metrics.stats()
                    assert "windows" in out and "uptime_seconds" in out
                except BaseException as exc:  # noqa: BLE001 — capture for assert
                    errors.append(exc)
                    break
        finally:
            stop.set()
            t.join(timeout=2.0)
            sys.setswitchinterval(old_interval)

        assert not errors, (
            f"/stats raised under concurrent deque mutation: {errors[0]!r}. "
            f"It must snapshot the deque before iterating."
        )


# ---------------------------------------------------------------------------
# A3.3 — /query/stream always closes with a `done` event
# ---------------------------------------------------------------------------


class TestStreamEmitsDoneEvent:
    """The SSE stream must end with `event: done` (carrying the full result)
    and never emit a bare `event: result`, regardless of how fast the
    pipeline thread finishes relative to the heartbeat loop."""

    def test_done_event_present_and_result_not_raw(self) -> None:
        from fastapi.testclient import TestClient

        # Reuse one client (each TestClient context re-runs FastAPI startup,
        # which reloads the SQLite audit). Repeat a few posts: the heartbeat-
        # vs-drain race is timing-dependent, and FakeBackend returns fast —
        # exactly the path that consumed the result in the heartbeat loop and
        # triggered the old bug.
        with TestClient(server.app) as client:
            for _ in range(3):
                resp = client.post(
                    "/query/stream",
                    json={"query": "qual meu saldo?", "channel": "app", "customer_id": "test-a3"},
                )
                assert resp.status_code == 200
                body = resp.text
                assert "event: done" in body, (
                    "Stream did not emit `event: done` — the UI would show "
                    "'Stream ended without a done event'."
                )
                assert "event: result" not in body, (
                    "Stream emitted a raw `event: result`; the result must be "
                    "translated into stage events + a done event."
                )
