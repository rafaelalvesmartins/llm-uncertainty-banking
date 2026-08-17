# Copyright 2026 Rafael Martins Alves - Apache-2.0

"""Subpackage conftest: apply the ``integration`` marker to every test
whose source file lives inside ``tests/integration/``.

Parent ``tests/conftest.py`` fixtures (``dummy_backend``, ``backend``,
``tmp_cache``, and the registry-snapshot autouse) are inherited
automatically by pytest without any re-import needed here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_INTEGRATION_DIR = Path(__file__).parent.resolve()


def pytest_collection_modifyitems(config, items):
    """Mark every test in ``tests/integration/`` as ``integration``.

    Pytest invokes every conftest's ``pytest_collection_modifyitems``
    against the full collection, so we filter by path to avoid touching
    tests under ``tests/test_*.py``.
    """
    for item in items:
        item_path_str = getattr(item, "path", None) or getattr(item, "fspath", None)
        if item_path_str is None:
            continue
        item_path = Path(str(item_path_str)).resolve()
        try:
            item_path.relative_to(_INTEGRATION_DIR)
        except ValueError:
            continue
        item.add_marker(pytest.mark.integration)
