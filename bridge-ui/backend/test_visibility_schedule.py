# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""The AI-Visibility collection scheduler is configurable at RUNTIME (no restart).

Before this, the scheduler was env-only (VISIBILITY_SCHEDULE_EVERY_S, read once at
startup) with no UI path — collection was effectively manual-only. Now
POST /visibility/schedule sets the interval live and GET /visibility/config
reflects it. Intervals are clamped (15s floor; <=0 = off) and bounded (<= 1440 min).

Run from the project root::

    pytest bridge-ui/backend/test_visibility_schedule.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

_client = TestClient(server.app)


def test_schedule_enable_disable_reflected_in_config() -> None:
    r = _client.post("/visibility/schedule", json={"every_minutes": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["schedule_every_s"] == 300.0
    cfg = _client.get("/visibility/config").json()
    assert cfg["schedule_every_s"] == 300.0
    assert cfg["schedule_every_minutes"] == 5.0

    off = _client.post("/visibility/schedule", json={"every_minutes": 0}).json()
    assert off["enabled"] is False
    assert _client.get("/visibility/config").json()["schedule_every_s"] == 0.0


def test_schedule_clamps_tiny_and_rejects_out_of_range() -> None:
    # a sub-minute interval is clamped to the 15s floor (no self-DoS)
    assert _client.post("/visibility/schedule", json={"every_minutes": 0.1}).json()["schedule_every_s"] == 15.0
    # out-of-range is a 422 (Pydantic bound), not a silent clamp
    assert _client.post("/visibility/schedule", json={"every_minutes": 99999}).status_code == 422
    _client.post("/visibility/schedule", json={"every_minutes": 0})  # leave the scheduler off
