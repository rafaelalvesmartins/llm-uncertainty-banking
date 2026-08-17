# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Tests for the extension namespaces created in pass 30 (updated post-pass-33).

`lub.domains` and `lub.compliance` were originally introduced as
intentionally-empty namespace packages reserved for domain-specific
and compliance-framework extensions. Pass 33 (CHANGES_2026-04-26
section 1.11) populated each with one documented skeleton sub-namespace:

* ``lub.domains.banking`` -- lazy-aliases the six banking benchmarks.
* ``lub.compliance.frameworks`` -- seven per-regime skeleton modules.

The post-pass-33 contract is therefore:

1. They MUST remain importable so downstream extensions can register
   themselves as namespace-package siblings (PEP 420 implicit nspkg
   pattern is *not* used here -- these are explicit `__init__.py`
   packages so the contract surface is greppable).
2. The only public symbols at each namespace root are the documented
   skeleton sub-namespaces (`banking`, `frameworks`). New domain or
   framework extensions add modules *under* the namespace, not as
   attributes bolted onto the namespace `__init__.py` itself.
3. They MUST stay free of heavy dependencies. Importing
   ``lub.domains`` should not trigger torch / transformers /
   matplotlib loads -- those belong at the leaf-extension level.

This file fixes that contract in CI so a contributor cannot
accidentally turn one of these namespaces into a stuffed module that
breaks the layered-architecture story. The positive contract for the
shipped skeletons themselves lives in ``test_compliance_frameworks.py``.
"""

from __future__ import annotations

import importlib
import sys

_ALLOWED_DOMAINS_PUBLIC: frozenset[str] = frozenset({"banking", "annotations"})
_ALLOWED_COMPLIANCE_PUBLIC: frozenset[str] = frozenset({"frameworks", "annotations"})


def test_lub_domains_imports_cleanly() -> None:
    mod = importlib.import_module("lub.domains")
    assert mod is not None
    assert mod.__name__ == "lub.domains"


def test_lub_compliance_imports_cleanly() -> None:
    mod = importlib.import_module("lub.compliance")
    assert mod is not None
    assert mod.__name__ == "lub.compliance"


def test_lub_domains_has_no_public_symbols() -> None:
    """The namespace root only re-exports the documented skeleton(s).

    Post-pass-33 (CHANGES_2026-04-26 section 1.11) the namespace ships
    ``lub.domains.banking``. Any other public attribute on the
    namespace root means a contributor accidentally bolted a class
    or function onto the namespace ``__init__.py`` -- extensions
    must be added as submodules (``lub.domains.healthcare`` etc.).
    """
    mod = importlib.import_module("lub.domains")
    public_attrs = {a for a in dir(mod) if not a.startswith("_")}
    extra = public_attrs - _ALLOWED_DOMAINS_PUBLIC
    assert extra == set(), (
        f"lub.domains has unexpected public attrs: {sorted(extra)!r}. "
        f"Allowed: {sorted(_ALLOWED_DOMAINS_PUBLIC)!r}. "
        f"Add new domain extensions as submodules "
        f"(lub.domains.healthcare, ...) not as attributes on the "
        f"namespace itself."
    )


def test_lub_compliance_has_no_public_symbols() -> None:
    """Same contract as lub.domains.

    Post-pass-33 the namespace re-exports
    :mod:`lub.compliance.frameworks`; any other public symbol means
    accidental bolt-on rather than a sibling submodule.
    """
    mod = importlib.import_module("lub.compliance")
    public_attrs = {a for a in dir(mod) if not a.startswith("_")}
    extra = public_attrs - _ALLOWED_COMPLIANCE_PUBLIC
    assert extra == set(), (
        f"lub.compliance has unexpected public attrs: {sorted(extra)!r}. "
        f"Allowed: {sorted(_ALLOWED_COMPLIANCE_PUBLIC)!r}. "
        f"Add new compliance frameworks as submodules "
        f"(lub.compliance.<jurisdiction>, ...) not as attributes."
    )


def test_lub_domains_does_not_pull_heavy_deps() -> None:
    """Importing the namespace must not trigger torch / transformers / mpl."""
    # Snapshot heavy modules that should NOT be loaded by `lub.domains`.
    heavy = {"torch", "transformers", "matplotlib", "datasets"}
    before = heavy & set(sys.modules.keys())
    importlib.import_module("lub.domains")
    after = heavy & set(sys.modules.keys())
    newly_loaded = after - before
    assert newly_loaded == set(), (
        f"lub.domains import pulled heavy deps: {newly_loaded!r}. "
        f"Keep the namespace lazy."
    )


def test_lub_compliance_does_not_pull_heavy_deps() -> None:
    """Same lazy-import contract as lub.domains."""
    heavy = {"torch", "transformers", "matplotlib", "datasets"}
    before = heavy & set(sys.modules.keys())
    importlib.import_module("lub.compliance")
    after = heavy & set(sys.modules.keys())
    newly_loaded = after - before
    assert newly_loaded == set(), (
        f"lub.compliance import pulled heavy deps: {newly_loaded!r}. "
        f"Keep the namespace lazy."
    )
