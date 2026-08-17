# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Tests for ``lub.compliance.frameworks`` and ``lub.domains.banking`` skeletons.

The two namespaces shipped 2026-04-26 (pass 33) per spec 30
(``planning/30_Generic_Architecture_Spec_2026-04-25.md``). They are
**lazy aliases** -- v0.1 keeps the data under TOML / under
``lub.benchmarks.*`` while v0.3-targeted code can already import from
the framework-shaped path. These tests pin the contract so the next
refactor does not silently change the surface.

Hermetic: no network, no real backend, no slow paths.
"""

from __future__ import annotations

import importlib

import pytest

from lub.reports.crosswalk import Regime

# ---------------------------------------------------------------------------
# lub.compliance.frameworks -- per-regime skeletons
# ---------------------------------------------------------------------------


_FRAMEWORK_NAMES: tuple[str, ...] = (
    "bcb_4893",
    "bcbs_239",
    "eu_ai_act",
    "iso_23894",
    "iso_42001",
    "nist_airmf",
    "sr_11_7",
)


_REGIME_BACKED_FRAMEWORKS: tuple[tuple[str, Regime], ...] = (
    ("bcb_4893", Regime.BCB),
    ("bcbs_239", Regime.BCBS),
    ("eu_ai_act", Regime.EU_AI_ACT),
    ("iso_23894", Regime.ISO_23894),
    ("iso_42001", Regime.ISO_42001),
    ("nist_airmf", Regime.NIST_GENAI),
)


def test_frameworks_namespace_exports_seven_modules() -> None:
    """The seven per-regime skeleton modules must be reachable from the namespace.

    The namespace's ``__all__`` is a superset: it lists the seven module
    names plus the ``ComplianceFrameworkProtocol`` re-export. This test
    pins the seven module names; the Protocol export is pinned separately
    by ``test_compliance_framework_protocol_is_re_exported``.
    """
    from lub.compliance import frameworks

    assert set(_FRAMEWORK_NAMES).issubset(set(frameworks.__all__))


@pytest.mark.parametrize("module_name", _FRAMEWORK_NAMES)
def test_each_framework_module_exposes_metadata_pointers(module_name: str) -> None:
    """Each framework exposes the contract metadata."""
    mod = importlib.import_module(f"lub.compliance.frameworks.{module_name}")
    # Contract: REGIME, CROSSWALK_KEY, TITLE, get_controls all present.
    assert hasattr(mod, "REGIME"), f"{module_name} missing REGIME"
    assert hasattr(mod, "CROSSWALK_KEY"), f"{module_name} missing CROSSWALK_KEY"
    assert hasattr(mod, "TITLE"), f"{module_name} missing TITLE"
    assert callable(mod.get_controls), f"{module_name}.get_controls not callable"
    assert isinstance(mod.CROSSWALK_KEY, str)
    assert mod.CROSSWALK_KEY  # non-empty
    assert isinstance(mod.TITLE, str)
    assert mod.TITLE  # non-empty


@pytest.mark.parametrize(("module_name", "expected_regime"), _REGIME_BACKED_FRAMEWORKS)
def test_regime_backed_framework_get_controls_returns_list(
    module_name: str, expected_regime: Regime,
) -> None:
    """Regime-backed frameworks return a list of control dicts from the crosswalk."""
    mod = importlib.import_module(f"lub.compliance.frameworks.{module_name}")
    assert mod.REGIME is expected_regime
    controls = mod.get_controls()
    assert isinstance(controls, list)
    # Each control is a dict with the ControlMapping shape.
    for c in controls:
        assert isinstance(c, dict)
        assert "control_id" in c
        assert "control_title" in c
        assert "description" in c


def test_sr_11_7_is_cross_referenced_not_a_regime() -> None:
    """SR 11-7 stays out of the Regime enum, but controls are now populated.

    Updated 2026-05-16: SR 11-7 left v0.1 skeleton state when the five pillar
    controls (V.A, V.B, VI.A, VI.B, VI.C) were added to
    ``crosswalk_data.toml`` under ``[controls.SR_11_7_*]`` and
    ``[sr_11_7.pillars.*]``. ``get_controls`` and the new
    ``get_pillar_controls`` / ``get_pillar_metrics`` accessors now return real
    data. ``REGIME`` deliberately remains ``None`` -- promoting SR 11-7 into
    the Regime enum would pull it into per-regime OSCAL emission and
    crosswalk filtering, which is the path SR 11-7 intentionally sits outside
    of. Pinning that boundary here so a future contributor does not flip it
    without a CANONICAL_FACTS update.
    """
    from lub.compliance.frameworks import sr_11_7

    assert sr_11_7.REGIME is None
    assert sr_11_7.CROSSWALK_KEY == "SR_11_7"
    # Three-pillar structure must survive any future tweak.
    assert sr_11_7.PILLARS == (
        "Conceptual Soundness",
        "Outcome Analysis",
        "Ongoing Monitoring",
    )
    # Populated controls (V.A, V.B, VI.A, VI.B, VI.C). Shape is the
    # ControlMapping TypedDict; the Protocol checks the call site already.
    controls = sr_11_7.get_controls()
    assert len(controls) == 5
    control_ids = {c["control_id"] for c in controls}
    assert control_ids == {
        "SR-11-7-V.A",
        "SR-11-7-V.B",
        "SR-11-7-VI.A",
        "SR-11-7-VI.B",
        "SR-11-7-VI.C",
    }
    # Pillar accessors are keyed by the three PILLARS names and each pillar
    # has at least one control and at least one evidencing metric.
    pillar_controls = sr_11_7.get_pillar_controls()
    pillar_metrics = sr_11_7.get_pillar_metrics()
    assert set(pillar_controls) == set(sr_11_7.PILLARS)
    assert set(pillar_metrics) == set(sr_11_7.PILLARS)
    for pillar in sr_11_7.PILLARS:
        assert pillar_controls[pillar], f"{pillar} has no controls"
        assert pillar_metrics[pillar], f"{pillar} has no metrics"


def test_framework_crosswalk_keys_match_regime_string_prefix() -> None:
    """For regime-backed frameworks, CROSSWALK_KEY should equal the Regime enum name."""
    for module_name, regime in _REGIME_BACKED_FRAMEWORKS:
        mod = importlib.import_module(f"lub.compliance.frameworks.{module_name}")
        assert mod.CROSSWALK_KEY == regime.name, (
            f"{module_name}.CROSSWALK_KEY={mod.CROSSWALK_KEY!r} "
            f"does not match Regime.{regime.name}"
        )


@pytest.mark.parametrize("module_name", _FRAMEWORK_NAMES)
def test_each_framework_satisfies_compliance_framework_protocol(module_name: str) -> None:
    """Every shipped framework must structurally satisfy the Protocol.

    :class:`lub.compliance.frameworks.protocols.ComplianceFrameworkProtocol`
    is ``runtime_checkable``; a future contributor adding a new framework
    module under this namespace will pass this test only if the module
    exposes the four contract members. This is the v0.3 plug-in contract
    -- catching drift now keeps the lazy-alias surface honest.
    """
    from lub.compliance.frameworks.protocols import ComplianceFrameworkProtocol

    mod = importlib.import_module(f"lub.compliance.frameworks.{module_name}")
    assert isinstance(mod, ComplianceFrameworkProtocol), (
        f"lub.compliance.frameworks.{module_name} does not satisfy "
        f"ComplianceFrameworkProtocol (missing one of: REGIME, "
        f"CROSSWALK_KEY, TITLE, get_controls)"
    )


def test_compliance_framework_protocol_is_re_exported() -> None:
    """``ComplianceFrameworkProtocol`` is reachable from the namespace's ``__all__``."""
    from lub.compliance import frameworks

    assert "ComplianceFrameworkProtocol" in frameworks.__all__
    # And the alias is the same object as the canonical home.
    from lub.compliance.frameworks.protocols import ComplianceFrameworkProtocol

    assert frameworks.ComplianceFrameworkProtocol is ComplianceFrameworkProtocol


def test_frameworks_namespace_exposes_iteration_tuple() -> None:
    """``lub.compliance.frameworks.FRAMEWORKS`` is the contract-pinned iteration tuple.

    Closes the spec-30 domain x compliance plug-in matrix on the compliance
    axis: a refactor that drops or replaces a member of ``FRAMEWORKS`` while
    keeping ``__all__`` intact would slip past the
    ``test_frameworks_namespace_exports_seven_modules`` ``__all__``-only pin.
    Members must be the same module objects as
    ``lub.compliance.frameworks.<leaf>``; leaf-name set equality holds against
    ``_FRAMEWORK_NAMES``.
    """
    from lub.compliance import frameworks

    assert hasattr(frameworks, "FRAMEWORKS")
    assert isinstance(frameworks.FRAMEWORKS, tuple)
    seen_names: set[str] = set()
    for module in frameworks.FRAMEWORKS:
        leaf = module.__name__.rsplit(".", 1)[-1]
        canonical = importlib.import_module(f"lub.compliance.frameworks.{leaf}")
        assert module is canonical, (
            f"FRAMEWORKS member {module.__name__} is not "
            f"lub.compliance.frameworks.{leaf} -- alias drift detected"
        )
        seen_names.add(leaf)
    assert seen_names == set(_FRAMEWORK_NAMES)
    assert "FRAMEWORKS" in frameworks.__all__


# ---------------------------------------------------------------------------
# lub.domains.banking -- lazy alias namespace
# ---------------------------------------------------------------------------


# __all__ exports include BENCHMARKS (the iteration tuple itself)
_BANKING_ALL: tuple[str, ...] = (
    "BENCHMARKS",
    "br_regulatory",
    "convfinqa",
    "credit_scoring",
    "financial_sentiment",
    "finqa",
    "tatqa",
)
# The actual benchmark MODULE names (what BENCHMARKS tuple contains)
_BANKING_BENCHMARKS: tuple[str, ...] = (
    "br_regulatory",
    "convfinqa",
    "credit_scoring",
    "financial_sentiment",
    "finqa",
    "tatqa",
)


def test_banking_namespace_re_exports_six_benchmarks() -> None:
    """``lub.domains.banking`` lazy-aliases the six banking benchmarks."""
    from lub.domains import banking

    assert set(banking.__all__) == set(_BANKING_ALL)


def test_banking_namespace_exposes_iteration_tuple() -> None:
    """``lub.domains.banking.BENCHMARKS`` is the contract-pinned iteration tuple.

    Mirrors :func:`test_frameworks_namespace_exposes_iteration_tuple` on the
    domain axis of the spec-30 plug-in matrix: members must be the same
    module objects as ``lub.benchmarks.<leaf>`` (the canonical home in v0.1)
    and leaf-name set equality holds against ``_BANKING_BENCHMARKS``. A
    refactor that drops or replaces a member of ``BENCHMARKS`` while keeping
    ``__all__`` intact would slip past the
    ``test_banking_namespace_re_exports_six_benchmarks`` ``__all__``-only pin.
    """
    from lub.domains import banking

    assert hasattr(banking, "BENCHMARKS")
    assert isinstance(banking.BENCHMARKS, tuple)
    seen_names: set[str] = set()
    for module in banking.BENCHMARKS:
        leaf = module.__name__.rsplit(".", 1)[-1]
        canonical = importlib.import_module(f"lub.benchmarks.{leaf}")
        assert module is canonical, (
            f"BENCHMARKS member {module.__name__} is not "
            f"lub.benchmarks.{leaf} -- alias drift detected"
        )
        seen_names.add(leaf)
    assert seen_names == set(_BANKING_BENCHMARKS)
    assert "BENCHMARKS" in banking.__all__


@pytest.mark.parametrize("benchmark_name", _BANKING_BENCHMARKS)
def test_banking_alias_points_at_lub_benchmarks(benchmark_name: str) -> None:
    """Each ``lub.domains.banking.<x>`` is the same module as ``lub.benchmarks.<x>``.

    This is the spec-30 lazy-alias contract -- the alias must be the *same*
    module object so callers can reach into it the same way they would on
    v0.3 (e.g. ``banking.finqa.FinQADataset is benchmarks.finqa.FinQADataset``).
    The alias is exposed as an attribute on the package init (via
    ``from lub.benchmarks import ...``) rather than as a real submodule, so
    we resolve it via ``getattr`` rather than ``import_module``.
    """
    from lub.domains import banking

    domain_mod = getattr(banking, benchmark_name)
    bench_mod = importlib.import_module(f"lub.benchmarks.{benchmark_name}")
    assert domain_mod is bench_mod, (
        f"lub.domains.banking.{benchmark_name} is not the same module as "
        f"lub.benchmarks.{benchmark_name} -- alias drift detected"
    )
