# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for the ``protocols.py`` (plural) lazy-alias shims.

CODE_ORGANIZATION_REVIEW_2026-04-25 §A.2 flagged the
``protocol.py`` (singular) vs ``protocols.py`` (plural) split across
the ``src/lub`` tree. CHANGES_2026-04-26 §2.2 shipped three plural
alias shims in pass 33 so v0.3-targeted code can already import from
the plural path while the singular form stays canonical in v0.1:

* :mod:`lub.benchmarks.protocols`  -> :mod:`lub.benchmarks.protocol`
* :mod:`lub.ledger.protocols`      -> :mod:`lub.ledger.protocol`
* :mod:`lub.reports.protocols`     -> :mod:`lub.reports.protocol`

The shims were untested at ship time. This module pins the contract:
each plural module imports cleanly, exposes the same ``__all__`` set as
its singular counterpart, and every re-exported name resolves to the
same Python object so callers cannot accidentally end up with two
different ``BenchmarkProtocol`` / ``LedgerProtocol`` / ``ReportGenerator``
classes depending on which import path they used.

Hermetic: no network, no real backend, no slow paths.
"""

from __future__ import annotations

import importlib

import pytest

_ALIAS_PAIRS: tuple[tuple[str, str], ...] = (
    ("lub.benchmarks.protocol", "lub.benchmarks.protocols"),
    ("lub.ledger.protocol", "lub.ledger.protocols"),
    ("lub.reports.protocol", "lub.reports.protocols"),
)


@pytest.mark.parametrize(("singular", "plural"), _ALIAS_PAIRS)
def test_plural_alias_imports_cleanly(singular: str, plural: str) -> None:
    """Both the singular and plural module forms import without error.

    The plural shim re-exports from the singular via star-import; if the
    star-import ever broke (typo in ``from X import *``) this would fail
    at import time.
    """
    # The singular form is the canonical home; importing it pre-warms the
    # module cache so the plural's star-import resolves predictably.
    importlib.import_module(singular)
    importlib.import_module(plural)


@pytest.mark.parametrize(("singular", "plural"), _ALIAS_PAIRS)
def test_plural_all_equals_singular_all(singular: str, plural: str) -> None:
    """``plural.__all__`` must equal ``singular.__all__`` (set equality).

    The shims build ``__all__`` from the singular's ``__all__`` so a
    contributor adding a name to the singular automatically gets it
    re-exported from the plural. This test catches the inverse failure
    mode -- a future hand-written ``__all__`` in the plural that drifts
    from the singular.
    """
    sing_mod = importlib.import_module(singular)
    plural_mod = importlib.import_module(plural)
    assert set(plural_mod.__all__) == set(sing_mod.__all__), (
        f"{plural}.__all__ drift: "
        f"only-in-plural={set(plural_mod.__all__) - set(sing_mod.__all__)}, "
        f"only-in-singular={set(sing_mod.__all__) - set(plural_mod.__all__)}"
    )


@pytest.mark.parametrize(("singular", "plural"), _ALIAS_PAIRS)
def test_plural_re_exports_same_objects_as_singular(singular: str, plural: str) -> None:
    """Each name in ``__all__`` resolves to the same object in both modules.

    The plural shim uses ``from X import *`` so the names should be the
    same Python objects (``is`` identity). If a future refactor ever
    changes the plural to declare its own classes, this test catches
    the divergence before downstream callers end up with two flavors of
    the same Protocol.
    """
    sing_mod = importlib.import_module(singular)
    plural_mod = importlib.import_module(plural)
    for name in sing_mod.__all__:
        sing_obj = getattr(sing_mod, name)
        plural_obj = getattr(plural_mod, name)
        assert plural_obj is sing_obj, (
            f"{plural}.{name} is not the same object as {singular}.{name} "
            f"-- alias drift detected"
        )
