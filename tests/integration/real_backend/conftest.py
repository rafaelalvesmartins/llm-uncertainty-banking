# Copyright 2026 Rafael Martins Alves - Apache-2.0
"""Auto-apply @pytest.mark.real_backend to tests in this subtree.

The parent conftest (tests/integration/conftest.py) already tags every
test here as @pytest.mark.integration via its path hook, so these
tests get BOTH markers. Selectors:

    pytest -m "not integration"             -> skip all e2e + real
    pytest -m "integration and not real_backend" -> hermetic e2e only
    pytest -m real_backend                  -> only real-backend smokes
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REAL_DIR = Path(__file__).parent.resolve()


def pytest_collection_modifyitems(config, items):
    for item in items:
        item_path_str = getattr(item, "path", None) or getattr(item, "fspath", None)
        if item_path_str is None:
            continue
        item_path = Path(str(item_path_str)).resolve()
        try:
            item_path.relative_to(_REAL_DIR)
        except ValueError:
            continue
        item.add_marker(pytest.mark.real_backend)
