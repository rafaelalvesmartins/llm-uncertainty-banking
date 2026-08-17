# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""Smoke tests for lub.dashboard.cli and lub.dashboard.server (pass 32).

The CLI is exercised with both --format html and --format json, against a
seeded in-memory ledger written to a tmp_path file.

The server module is tested for two failure modes:
  1. fastapi missing -> ImportError with install hint
  2. fastapi present -> build_app returns a FastAPI app (skip if not installed)

Spec: planning/29_Dashboard_Spec_2026-04-25.md sections 4-5.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest


def _seed_ledger(path: Path) -> None:
    from lub.ledger import Ledger
    led = Ledger(path)
    try:
        qid = led.log_query("Q?", domain="banking")
        a1 = led.log_answer(qid, "gpt-4o", "openai", "y", tier="prime")
        a2 = led.log_answer(qid, "gpt-4o", "openai", "n", tier="prime")
        led.log_policy(a1, "EMIT", 0.7, True, "ok")
        led.log_policy(a2, "REFUSE", 0.7, False, "low")
        led.update_outcome(a1, correct=True)
    finally:
        led.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_render_html_to_file(tmp_path):
    from lub.dashboard.cli import main
    db = tmp_path / "uq.db"
    _seed_ledger(db)
    out = tmp_path / "dash.html"
    rc = main(["render", "--ledger", str(db), "--out", str(out), "--days", "3650"])
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert body.startswith("<!DOCTYPE html>")
    assert "</html>" in body
    assert "OSCAL" in body


def test_cli_render_json_to_stdout(tmp_path, capsys):
    from lub.dashboard.cli import main
    db = tmp_path / "uq.db"
    _seed_ledger(db)
    rc = main([
        "render", "--ledger", str(db), "--out", "-", "--format", "json",
        "--days", "3650", "--tenant", "test",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["tenant"] == "test"
    assert parsed["decisions_in_window"] == 2
    assert parsed["abstention_rate"] == 0.5


def test_cli_missing_ledger_returns_error(tmp_path, capsys):
    from lub.dashboard.cli import main
    rc = main(["render", "--ledger", str(tmp_path / "nope.db"), "--out", "-"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "ledger not found" in captured.err


def test_cli_help_works():
    from lub.dashboard.cli import build_parser
    parser = build_parser()
    # argparse prints help and exits with SystemExit(0); just confirm it runs.
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--help"])
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


def test_build_app_raises_clear_importerror_when_fastapi_missing(tmp_path):
    """If fastapi is unavailable, build_app must raise ImportError with hint."""
    from lub.dashboard import server
    db = tmp_path / "uq.db"
    _seed_ledger(db)
    # Force the import to fail by stubbing sys.modules.
    with mock.patch.dict(sys.modules, {"fastapi": None}):
        with pytest.raises(ImportError, match="fastapi"):
            server.build_app(db)


def test_build_app_works_when_fastapi_available(tmp_path):
    fastapi = pytest.importorskip("fastapi")
    from lub.dashboard.server import build_app_from_ledger_path
    db = tmp_path / "uq.db"
    _seed_ledger(db)
    app = build_app_from_ledger_path(db, tenant="t1")
    assert isinstance(app, fastapi.FastAPI)
    # Health endpoint should be wired.
    routes = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/healthz" in routes
    assert "/" in routes
    assert "/api/snapshot" in routes


def test_server_endpoints_return_data_when_fastapi_available(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")  # TestClient dep
    from fastapi.testclient import TestClient

    from lub.dashboard.server import build_app_from_ledger_path
    db = tmp_path / "uq.db"
    _seed_ledger(db)
    app = build_app_from_ledger_path(db, tenant="t1")
    client = TestClient(app)
    h = client.get("/healthz")
    assert h.status_code == 200 and h.json()["status"] == "ok"
    s = client.get("/api/snapshot?days=3650")
    assert s.status_code == 200
    payload = s.json()
    assert payload["tenant"] == "t1"
    assert payload["decisions_in_window"] == 2
    r = client.get("/?days=3650")
    assert r.status_code == 200
    assert r.text.startswith("<!DOCTYPE html>")
