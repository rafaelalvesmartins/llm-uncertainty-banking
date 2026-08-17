# Copyright 2026 Rafael Martins Alves — Apache-2.0
"""Pytest test isolation for the Bridge backend.

Point every persistent SQLite store at an ephemeral per-run temp dir BEFORE any
test imports ``server`` (these env vars are read at module-import time). Without
this the suite shares the demo's real ``$TMP`` databases — ``bridge_changes.db``,
``bridge_audit.db`` and ``bridge_visibility.db``. Stale *approved* governed
changes left over from manual demo/QA sessions then get applied to the live
classifier mid-suite and tip the intent battery below its threshold, producing
flaky, order-dependent failures (e.g. ``test_classifier_battery_accuracy_is_strong``)
that vanish when a test is run in isolation.

``setdefault`` is used so CI or a developer can still pin a specific path
(including ``BRIDGE_AUDIT_DB=:memory:``) by exporting it before the run.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_ISOLATED_DIR = Path(tempfile.mkdtemp(prefix="bridge-tests-"))

os.environ.setdefault("BRIDGE_CHANGES_DB", str(_ISOLATED_DIR / "changes.db"))
os.environ.setdefault("BRIDGE_AUDIT_DB", str(_ISOLATED_DIR / "audit.db"))
os.environ.setdefault("BRIDGE_VISIBILITY_DB", str(_ISOLATED_DIR / "visibility.db"))


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Remove the ephemeral DB dir after the run."""
    shutil.rmtree(_ISOLATED_DIR, ignore_errors=True)
