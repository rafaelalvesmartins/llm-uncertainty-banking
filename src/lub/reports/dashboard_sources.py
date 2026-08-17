# Copyright 2026 Rafael Martins Alves -- Apache-2.0
"""lub.reports.dashboard_sources -- default EvidenceSource implementations.

Pass-34 refactor: extracts the filesystem-walk + JSON-parse logic that
used to live inline in :mod:`lub.reports.dashboard.collect_dashboard_data`
so the composer can stay generic over any
:class:`~lub.reports.dashboard_protocols.EvidenceSource`.

Two implementations ship by default:

* :class:`DirEvidenceSource` -- the legacy directory walk (what
  ``build_dashboard(results_dir, ...)`` ends up using). One JSON file =
  one artefact; classified by heuristic on top-level keys.

* :class:`InMemoryEvidenceSource` -- pre-built lists. Useful for tests,
  for integration with non-FS data sources, and as the canonical
  "how do I write a new evidence source" reference for plug-in authors.

Other implementations (S3, ZIP archive, Git artefact bundle) plug in
symmetrically -- none is required, the Protocol is the only contract.

Spec: planning/29_Dashboard_Spec_2026-04-25.md (post pass-34 refactor).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

__all__ = ["DirEvidenceSource", "InMemoryEvidenceSource"]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return None


def _is_benchmark_result(payload: dict[str, Any]) -> bool:
    """BenchmarkResult JSONs have these top-level keys."""
    return all(k in payload for k in ("estimator", "dataset", "n", "accuracy", "ece"))


def _is_oscal_assessment(payload: dict[str, Any]) -> bool:
    return "assessment-results" in payload


def _regime_coverage_from_crosswalk() -> list[dict[str, Any]]:
    """Read the crosswalk_data.toml shipped with the package.

    Returns the same projection that the legacy
    ``_regime_coverage_from_crosswalk`` produced; empty list when the
    file or the toml parser is missing.
    """
    try:
        import tomllib
    except ImportError:  # pragma: no cover -- legacy 3.10 fallback
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return []
    here = Path(__file__).resolve().parent
    toml_path = here / "crosswalk_data.toml"
    if not toml_path.exists():
        return []
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows: list[dict[str, Any]] = []
    for key, regime in data.items():
        if key == "metadata" or not isinstance(regime, dict):
            continue
        controls = regime.get("controls", [])
        if not isinstance(controls, list):
            continue
        rows.append(
            {
                "key": key,
                "name": regime.get("name", key),
                "n_controls": len(controls),
            }
        )
    rows.sort(key=lambda r: r["key"])
    return rows


# ---------------------------------------------------------------------------
# DirEvidenceSource: default legacy implementation
# ---------------------------------------------------------------------------


class DirEvidenceSource:
    """EvidenceSource that walks a directory of JSON artefacts.

    The walk happens lazily on first access and the results are cached
    per instance so multiple ``iter_*`` calls don't re-read the disk.
    """

    def __init__(self, results_dir: Path | str) -> None:
        self._results_dir = Path(results_dir)
        self._scanned = False
        self._benchmark_payloads: list[dict[str, Any]] = []
        self._oscal_payloads: list[dict[str, Any]] = []
        self._artefacts: list[dict[str, str]] = []
        self._warnings: list[str] = []

    def _scan(self) -> None:
        if self._scanned:
            return
        self._scanned = True
        if not self._results_dir.exists() or not self._results_dir.is_dir():
            self._warnings.append(
                f"results_dir {self._results_dir} does not exist; dashboard is empty."
            )
            return
        for path in sorted(self._results_dir.glob("*.json")):
            payload = _read_json(path)
            if payload is None:
                self._warnings.append(f"failed to parse {path.name}; skipped")
                continue
            if _is_benchmark_result(payload):
                self._benchmark_payloads.append(payload)
                self._artefacts.append({"name": path.name, "kind": "benchmark"})
            elif _is_oscal_assessment(payload):
                self._oscal_payloads.append(payload)
                self._artefacts.append({"name": path.name, "kind": "oscal"})
            else:
                self._artefacts.append({"name": path.name, "kind": "other"})

    # -- EvidenceSource Protocol implementation ---------------------------

    def iter_benchmark_results(self) -> Iterable[dict[str, Any]]:
        """Yield cached BenchmarkResult payloads after a lazy directory scan."""
        self._scan()
        return list(self._benchmark_payloads)

    def iter_oscal_assessments(self) -> Iterable[dict[str, Any]]:
        """Yield cached OSCAL assessment payloads after a lazy directory scan."""
        self._scan()
        return list(self._oscal_payloads)

    def iter_artefacts(self) -> Iterable[dict[str, str]]:
        """Yield ``{name, kind}`` records for every JSON artefact discovered."""
        self._scan()
        return list(self._artefacts)

    def regime_coverage(self) -> list[dict[str, Any]]:
        """Return regime coverage rows from the bundled crosswalk TOML."""
        return _regime_coverage_from_crosswalk()

    def warnings(self) -> list[str]:
        """Return warnings accumulated during the directory scan."""
        self._scan()
        return list(self._warnings)


# ---------------------------------------------------------------------------
# InMemoryEvidenceSource: canonical "how to write a plug-in" reference
# ---------------------------------------------------------------------------


class InMemoryEvidenceSource:
    """EvidenceSource populated from pre-built lists.

    Use for tests and for non-filesystem integrations (e.g. an S3 walker
    that reads JSON keys into memory and then composes via this class).
    """

    def __init__(
        self,
        *,
        benchmark_results: list[dict[str, Any]] | None = None,
        oscal_assessments: list[dict[str, Any]] | None = None,
        artefacts: list[dict[str, str]] | None = None,
        regimes: list[dict[str, Any]] | None = None,
        warnings_list: list[str] | None = None,
    ) -> None:
        self._benchmark = list(benchmark_results or [])
        self._oscal = list(oscal_assessments or [])
        self._artefacts = list(artefacts or [])
        self._regimes = list(regimes or [])
        self._warnings = list(warnings_list or [])

    def iter_benchmark_results(self) -> Iterable[dict[str, Any]]:
        """Return a copy of the in-memory BenchmarkResult payloads."""
        return list(self._benchmark)

    def iter_oscal_assessments(self) -> Iterable[dict[str, Any]]:
        """Return a copy of the in-memory OSCAL assessment payloads."""
        return list(self._oscal)

    def iter_artefacts(self) -> Iterable[dict[str, str]]:
        """Return a copy of the in-memory artefact records."""
        return list(self._artefacts)

    def regime_coverage(self) -> list[dict[str, Any]]:
        """Return a copy of the in-memory regime coverage rows."""
        return list(self._regimes)

    def warnings(self) -> list[str]:
        """Return a copy of the in-memory warnings list."""
        return list(self._warnings)
