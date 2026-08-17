"""Reference API gateway — written by the INSTITUTION, not shipped by lub.

This is the ~50 lines of integration code a bank would write to embed
lub into its existing API gateway.  See Section 7 of the tech report.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import psycopg2
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel

from lub.guard import UncertaintyGuard
from lub.pipeline import UncertaintyPipeline
from lub.policies import PolicyDecision

# ---------------------------------------------------------------------------
# Configuration — in production these come from the institution's secret store
# ---------------------------------------------------------------------------
ESTIMATOR = os.environ.get("LUB_ESTIMATOR", "self_consistency")
THRESHOLD = float(os.environ.get("LUB_THRESHOLD", "0.7"))
BACKEND = os.environ.get("LUB_BACKEND", "dummy")
MODEL = os.environ.get("LUB_MODEL", "dummy-ref")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# lub setup — this is the only lub-specific code
# ---------------------------------------------------------------------------
pipe = UncertaintyPipeline(backend=BACKEND, model=MODEL, estimator=ESTIMATOR)
guard = UncertaintyGuard(pipe, threshold=THRESHOLD, on_fail=PolicyDecision.ABSTAIN)

# ---------------------------------------------------------------------------
# Observability — institution's Prometheus stack
# ---------------------------------------------------------------------------
REQUEST_COUNT = Counter("lub_requests_total", "Total requests", ["estimator", "refused"])
CONFIDENCE_HIST = Histogram("lub_confidence", "Confidence distribution", buckets=[0.1 * i for i in range(11)])
LATENCY_HIST = Histogram("lub_latency_seconds", "Request latency")

# ---------------------------------------------------------------------------
# FastAPI app — institution's gateway
# ---------------------------------------------------------------------------
app = FastAPI(title="LUB Reference Gateway", version="0.1.0")
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    confidence: float
    should_refuse: bool
    policy: str
    estimator: str


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    with LATENCY_HIST.time():
        result = guard(req.question)

    CONFIDENCE_HIST.observe(result.raw.confidence)
    REQUEST_COUNT.labels(estimator=ESTIMATOR, refused=str(result.raw.should_refuse)).inc()

    # Persist to institution's database
    if DATABASE_URL:
        _persist(req.question, result)

    return AskResponse(
        answer=result.raw.answer,
        confidence=result.raw.confidence,
        should_refuse=result.raw.should_refuse,
        policy=result.outcome.value,
        estimator=ESTIMATOR,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "estimator": ESTIMATOR, "backend": BACKEND}


def _persist(question: str, result: object) -> None:
    """Write GuardResult to the institution's database."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO lub_results (ts, question, result_json) VALUES (%s, %s, %s)",
            (datetime.now(UTC), question, json.dumps(result.raw.to_dict())),  # type: ignore[union-attr]
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        # In production: report to the institution's error tracker (Sentry,
        # Datadog, Splunk, etc.). Never swallow silently — even reference
        # code that pretends to be "demo" gets copy-pasted into prod.
        import logging
        logging.getLogger("lub.reference.gateway").exception(
            "ledger.write_failed: %s", exc
        )
