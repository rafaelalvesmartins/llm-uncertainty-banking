# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Structural protocol for ``lub.compliance.frameworks.<name>`` modules.

Per spec 30 (`planning/30_Generic_Architecture_Spec_2026-04-25.md`)
each compliance regime should eventually own its catalog of controls,
its emit format, and its crosswalk to the others; v0.1 ships seven
skeleton modules under :mod:`lub.compliance.frameworks` that already
satisfy a uniform contract via module-level attributes (``REGIME``,
``CROSSWALK_KEY``, ``TITLE``, ``get_controls()``). This module makes
that contract explicit so v0.3+ plug-ins can drop in by structural
typing alone -- no registry, no metaclass, no central edit point.

.. note::
   The Protocol is **structural**: any module (or object) that exposes
   the four members below already conforms. Concrete classes, namespace
   packages, and importable modules can all satisfy it. This is the
   "registry where a Protocol would do" pattern from the architecture
   brief: a contributor adds a new framework module under
   ``lub.compliance.frameworks.<name>`` and ``isinstance(module, ...)``
   verifies the contract without modifying core.

.. note::
   This is a sibling of the lazy-alias namespace; see
   :mod:`lub.compliance.frameworks` for the seven shipped frameworks
   and :class:`lub.reports.crosswalk.Regime` for the regime enum.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from lub.reports.crosswalk import ControlMapping, Regime


@runtime_checkable
class ComplianceFrameworkProtocol(Protocol):
    """Structural contract for a compliance-framework module.

    Each ``lub.compliance.frameworks.<name>`` module exposes four
    module-level members. The Protocol formalizes that contract so
    callers (the dashboard, OSCAL emitters, future plug-ins) can
    iterate over an arbitrary set of frameworks without depending
    on the concrete module names.

    Attributes:
        REGIME: The :class:`Regime` enum value the framework backs,
            or ``None`` for cross-referenced frameworks (e.g. SR 11-7
            in v0.1, which is documented via the README three-pillar
            table rather than as a Regime enum value).
        CROSSWALK_KEY: The string key used in
            ``crosswalk_data.toml`` -- equals ``REGIME.name`` for
            regime-backed frameworks, or a free-form identifier
            (``"SR_11_7"``) for cross-referenced frameworks.
        TITLE: Human-readable framework title for report headers.

    Methods:
        get_controls: Return the list of control mappings the
            framework asserts. Implementations typically delegate
            to :func:`lub.reports.crosswalk.get_all_controls_for_regime`
            for regime-backed frameworks, or return ``[]`` for
            cross-referenced frameworks in v0.1.
    """

    REGIME: Regime | None
    CROSSWALK_KEY: str
    TITLE: str

    def get_controls(self) -> list[ControlMapping]:
        """Return this framework's control mappings (or ``[]``)."""
        ...


__all__ = ["ComplianceFrameworkProtocol"]
