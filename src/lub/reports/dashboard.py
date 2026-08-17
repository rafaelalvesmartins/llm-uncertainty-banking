# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Static evidence dashboard -- single self-contained HTML for offline audit.

.. note::
   **Two dashboards in lub, by design.** This module
   (:mod:`lub.reports.dashboard`) is the **static, post-run** evidence
   viewer: takes a directory of finished JSON results, emits a single
   self-contained HTML file the audit team opens offline.
   The sibling :mod:`lub.dashboard` is the **live, in-process**
   observability surface (FastAPI scaffold pending v0.3.x) that reads
   the ledger directly. Use this module for evidence packets that
   ship to auditors; use :mod:`lub.dashboard` when you want a live
   monitoring surface for an actively-running deployment.

Composes existing artifacts (per-estimator BenchmarkResult JSON, OSCAL
Assessment Results JSON, AI RMF reports, reliability diagrams) into a single
``index.html`` that the bank's MRM team can open without a server, without
network access, and without database.

This is the v0.1 answer to RUFLO_VS_LUB_GAP_2026-04-25.md section 3.2: ruflo
provides the live operational UI; LUB ships the static post-run audit-evidence
dashboard. The two are complementary, not competing.

Usage::

    from pathlib import Path
    from lub.reports.dashboard import build_dashboard

    build_dashboard(
        results_dir=Path("benchmarks/results/"),
        out=Path("dist/evidence_dashboard.html"),
        title="lub evidence dashboard -- Q2 2026",
    )

Design constraints:
  - No server, no JS framework, no database.
  - Single-file HTML output (PNG charts already base64-embedded by L5 reporter
    are linked, not re-embedded; ECE/PRR/etc. plotted as inline SVG).
  - Pure stdlib + jinja2 (jinja2 is already a hard dep of lub).
  - Banks must be able to copy the file to a USB stick and open it offline.
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DashboardCard",
    "DashboardData",
    "build_dashboard",
    "collect_dashboard_data",
    "render_dashboard_html",
]


@dataclass(frozen=True)
class DashboardCard:
    """One summary card on the dashboard top strip."""

    label: str
    value: str
    sublabel: str = ""
    status: str = "neutral"  # one of: "ok", "warn", "fail", "neutral"


@dataclass
class DashboardData:
    """Pre-rendered data ready for the HTML template.

    Built from a directory of BenchmarkResult JSONs plus any sibling
    OSCAL / AIRMF outputs. Tests construct it directly to skip the
    filesystem walk.
    """

    title: str
    generated_at: str
    cards: list[DashboardCard] = field(default_factory=list)
    estimator_rows: list[dict[str, Any]] = field(default_factory=list)
    regime_coverage: list[dict[str, Any]] = field(default_factory=list)
    drift_events: list[dict[str, Any]] = field(default_factory=list)
    cec_findings: list[dict[str, Any]] = field(default_factory=list)
    artefacts: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File-system collectors
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return None


def _is_benchmark_result(payload: dict[str, Any]) -> bool:
    """Heuristic: BenchmarkResult JSONs have these top-level keys."""
    return all(k in payload for k in ("estimator", "dataset", "n", "accuracy", "ece"))


def _is_oscal_assessment(payload: dict[str, Any]) -> bool:
    return "assessment-results" in payload


def _format_metric(value: Any, places: int = 4) -> str:
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(v):
        return "NaN"
    return f"{v:.{places}f}"


def _classify_ece(ece: float | None) -> str:
    if ece is None or math.isnan(ece):
        return "neutral"
    if ece <= 0.05:
        return "ok"
    if ece <= 0.15:
        return "warn"
    return "fail"


def _summary_cards(rows: list[dict[str, Any]]) -> list[DashboardCard]:
    cards: list[DashboardCard] = []
    if not rows:
        cards.append(DashboardCard("runs", "0", "no benchmark JSONs found", "warn"))
        return cards
    n_runs = len(rows)
    eces = [r["ece"] for r in rows if isinstance(r.get("ece"), (int, float))]
    accs = [r["accuracy"] for r in rows if isinstance(r.get("accuracy"), (int, float))]
    estimators = sorted({r.get("estimator", "?") for r in rows})
    datasets = sorted({r.get("dataset", "?") for r in rows})
    avg_ece = (sum(eces) / len(eces)) if eces else float("nan")
    avg_acc = (sum(accs) / len(accs)) if accs else float("nan")
    cards.append(DashboardCard("runs", str(n_runs), "BenchmarkResult JSONs"))
    cards.append(DashboardCard("estimators", str(len(estimators)), "distinct in run set"))
    cards.append(DashboardCard("datasets", str(len(datasets)), "distinct in run set"))
    cards.append(
        DashboardCard(
            "avg ECE",
            _format_metric(avg_ece),
            "lower is better; gate 0.05",
            _classify_ece(avg_ece),
        )
    )
    cards.append(
        DashboardCard(
            "avg accuracy",
            _format_metric(avg_acc),
            "task-correctness baseline",
            "warn" if (not math.isnan(avg_acc) and avg_acc < 0.20) else "neutral",
        )
    )
    return cards


def _estimator_rows(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project BenchmarkResult JSONs to display-ready rows."""
    rows: list[dict[str, Any]] = []
    for p in payloads:
        rows.append(
            {
                "estimator": p.get("estimator", "?"),
                "backend": p.get("backend", "?"),
                "dataset": p.get("dataset", "?"),
                "n": p.get("n", 0),
                "accuracy": _format_metric(p.get("accuracy")),
                "ece": _format_metric(p.get("ece")),
                "ece_class": _classify_ece(p.get("ece")),
                "auroc": _format_metric(p.get("refusal_auroc") or p.get("auroc")),
                "prr": _format_metric(p.get("prr")),
                "brier": _format_metric(p.get("brier")),
                "rmsce": _format_metric(p.get("rmsce")),
                "timestamp": p.get("timestamp", ""),
                "git_sha": (p.get("git_sha") or "")[:8],
            }
        )
    rows.sort(key=lambda r: (r["dataset"], r["estimator"], r["timestamp"]))
    return rows


def _extract_oscal_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull human-readable findings out of an OSCAL Assessment Results payload."""
    out: list[dict[str, Any]] = []
    results = payload.get("assessment-results", {}).get("results", [])
    for result in results:
        for finding in result.get("findings", []):
            out.append(
                {
                    "title": finding.get("title", "(untitled)"),
                    "description": finding.get("description", ""),
                    "target": (finding.get("target") or {}).get("target-id", "-"),
                    "n_observations": len(finding.get("related-observations", [])),
                }
            )
    return out


def _regime_coverage_from_crosswalk() -> list[dict[str, Any]]:
    """Read the crosswalk_data.toml shipped with the package and project to a row list."""
    try:
        # tomllib is stdlib in 3.11+; the package already pins >=3.11.
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


def _coerce_to_evidence_source(obj: Any) -> EvidenceSource | None:
    """Return *obj* if it satisfies EvidenceSource; otherwise wrap a
    Path/str in a DirEvidenceSource. Returns None for anything else.

    The Path-wrapping branch is the back-compat shim: existing callers
    of ``collect_dashboard_data(results_dir)`` and
    ``build_dashboard(results_dir, out)`` keep working unchanged.
    """
    from lub.reports.dashboard_protocols import EvidenceSource

    if isinstance(obj, EvidenceSource):
        return obj
    if isinstance(obj, (Path, str)):
        from lub.reports.dashboard_sources import DirEvidenceSource

        return DirEvidenceSource(Path(obj))
    return None


def collect_dashboard_data(
    source: Any,
    *,
    title: str = "lub evidence dashboard",
    now: _dt.datetime | None = None,
) -> DashboardData:
    """Compose a :class:`DashboardData` from any :class:`EvidenceSource`.

    Args:
        source: Anything satisfying
            :class:`~lub.reports.dashboard_protocols.EvidenceSource`. For
            back-compat, a directory path (``Path`` or ``str``) is also
            accepted and gets wrapped in
            :class:`~lub.reports.dashboard_sources.DirEvidenceSource`
            automatically.
        title: Title shown at the top of the dashboard.
        now: Override the timestamp shown in the header. Mostly for tests.

    Returns:
        A populated :class:`DashboardData`. Never raises on an empty
        source; the resulting dashboard records a warning instead.
    """
    now = now or _dt.datetime.now(tz=_dt.UTC)
    data = DashboardData(
        title=title,
        generated_at=now.replace(microsecond=0).isoformat(),
    )

    ev_source = _coerce_to_evidence_source(source)
    if ev_source is None:
        data.warnings.append(
            f"unrecognised evidence source {type(source).__name__}; dashboard is empty."
        )
        data.cards = _summary_cards([])
        return data

    benchmark_payloads = list(ev_source.iter_benchmark_results())
    cec_findings: list[dict[str, Any]] = []
    for oscal_payload in ev_source.iter_oscal_assessments():
        cec_findings.extend(_extract_oscal_findings(oscal_payload))

    data.cards = _summary_cards(benchmark_payloads)
    data.estimator_rows = _estimator_rows(benchmark_payloads)
    data.cec_findings = cec_findings
    data.regime_coverage = ev_source.regime_coverage()
    data.artefacts = list(ev_source.iter_artefacts())
    data.warnings.extend(ev_source.warnings())

    if not benchmark_payloads:
        data.warnings.append(
            "no BenchmarkResult artefacts detected; the per-estimator table is empty."
        )

    return data


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --fg: #111827;
    --fg-muted: #6b7280;
    --bg: #ffffff;
    --bg-alt: #f9fafb;
    --border: #e5e7eb;
    --ok: #047857;
    --ok-bg: #ecfdf5;
    --warn: #b45309;
    --warn-bg: #fffbeb;
    --fail: #b91c1c;
    --fail-bg: #fef2f2;
    --neutral: #4b5563;
    --neutral-bg: #f3f4f6;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--fg); margin: 0; padding: 24px; background: var(--bg); }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  h2 {{ margin: 28px 0 8px; font-size: 16px; font-weight: 600; }}
  .muted {{ color: var(--fg-muted); font-size: 13px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-top: 16px; }}
  .card {{ border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: var(--bg); }}
  .card.ok {{ border-left: 3px solid var(--ok); }}
  .card.warn {{ border-left: 3px solid var(--warn); }}
  .card.fail {{ border-left: 3px solid var(--fail); }}
  .card.neutral {{ border-left: 3px solid var(--neutral); }}
  .card .label {{ color: var(--fg-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }}
  .card .value {{ font-size: 22px; font-weight: 600; margin: 2px 0; }}
  .card .sublabel {{ color: var(--fg-muted); font-size: 11px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); }}
  th {{ font-weight: 600; color: var(--fg-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; background: var(--bg-alt); }}
  tr:hover td {{ background: var(--bg-alt); }}
  .pill {{ display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; }}
  .pill.ok {{ background: var(--ok-bg); color: var(--ok); }}
  .pill.warn {{ background: var(--warn-bg); color: var(--warn); }}
  .pill.fail {{ background: var(--fail-bg); color: var(--fail); }}
  .pill.neutral {{ background: var(--neutral-bg); color: var(--neutral); }}
  .warnings {{ background: var(--warn-bg); border: 1px solid var(--warn); border-radius: 8px; padding: 12px 14px; margin-top: 16px; }}
  .warnings strong {{ color: var(--warn); }}
  ul.bare {{ list-style: none; padding: 0; margin: 0; }}
  ul.bare li {{ padding: 6px 0; border-bottom: 1px solid var(--border); }}
  footer {{ color: var(--fg-muted); font-size: 11px; margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border); }}
  .empty {{ color: var(--fg-muted); font-style: italic; padding: 8px 0; }}
  code {{ font: 12px ui-monospace, "SF Mono", Consolas, monospace; background: var(--bg-alt); padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<header>
<h1>{title}</h1>
<div class="muted">generated {generated_at} &middot; offline static dashboard &middot; <code>lub.reports.dashboard</code></div>
</header>

{warnings_block}

<section>
<h2>Summary</h2>
<div class="cards">
{cards_html}
</div>
</section>

<section>
<h2>Per-estimator results</h2>
{estimator_table}
</section>

<section>
<h2>Regulatory regime coverage</h2>
{regime_table}
</section>

<section>
<h2>CEC / OSCAL findings</h2>
{findings_block}
</section>

<section>
<h2>Source artefacts</h2>
{artefacts_block}
</section>

<footer>
This file was generated offline by <code>lub.reports.dashboard</code>. It contains
only LUB outputs already present in the results directory; no external resources are loaded.
Open from a USB stick if your audit policy requires it.
</footer>
</body>
</html>
"""


def _render_card(card: DashboardCard) -> str:
    return (
        f'<div class="card {_html.escape(card.status)}">'
        f'<div class="label">{_html.escape(card.label)}</div>'
        f'<div class="value">{_html.escape(card.value)}</div>'
        f'<div class="sublabel">{_html.escape(card.sublabel)}</div>'
        "</div>"
    )


def _render_estimator_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No BenchmarkResult JSONs found in results directory.</div>'
    head = (
        "<table><thead><tr>"
        "<th>estimator</th><th>backend</th><th>dataset</th>"
        "<th>n</th><th>acc</th><th>ECE</th><th>AUROC</th><th>PRR</th>"
        "<th>Brier</th><th>RMSCE</th><th>git</th>"
        "</tr></thead><tbody>"
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td><code>{_html.escape(str(r['estimator']))}</code></td>"
            f"<td>{_html.escape(str(r['backend']))}</td>"
            f"<td>{_html.escape(str(r['dataset']))}</td>"
            f"<td>{_html.escape(str(r['n']))}</td>"
            f"<td>{_html.escape(r['accuracy'])}</td>"
            f'<td><span class="pill {_html.escape(r["ece_class"])}">{_html.escape(r["ece"])}</span></td>'
            f"<td>{_html.escape(r['auroc'])}</td>"
            f"<td>{_html.escape(r['prr'])}</td>"
            f"<td>{_html.escape(r['brier'])}</td>"
            f"<td>{_html.escape(r['rmsce'])}</td>"
            f"<td><code>{_html.escape(r['git_sha'])}</code></td>"
            "</tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def _render_regime_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<div class="empty">crosswalk_data.toml not found; regime coverage unavailable.</div>'
        )
    head = (
        "<table><thead><tr>"
        "<th>regime key</th><th>name</th><th>controls in TOML</th>"
        "</tr></thead><tbody>"
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td><code>{_html.escape(r['key'])}</code></td>"
            f"<td>{_html.escape(r['name'])}</td>"
            f"<td>{_html.escape(str(r['n_controls']))}</td>"
            "</tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def _render_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return '<div class="empty">No CEC or OSCAL findings in this run set.</div>'
    items = []
    for f in findings:
        items.append(
            "<li>"
            f"<strong>{_html.escape(str(f.get('title', '')))}</strong> "
            f'<span class="muted">[target {_html.escape(str(f.get("target", "-")))}, '
            f"{int(f.get('n_observations', 0))} observations]</span><br>"
            f'<span class="muted">{_html.escape(str(f.get("description", "")))}</span>'
            "</li>"
        )
    return '<ul class="bare">' + "".join(items) + "</ul>"


def _render_artefacts(artefacts: list[dict[str, str]]) -> str:
    if not artefacts:
        return '<div class="empty">No source artefacts catalogued.</div>'
    items = []
    for a in artefacts:
        items.append(
            f"<li><code>{_html.escape(a['name'])}</code> "
            f'<span class="pill neutral">{_html.escape(a["kind"])}</span></li>'
        )
    return '<ul class="bare">' + "".join(items) + "</ul>"


def _render_warnings(warnings: list[str]) -> str:
    if not warnings:
        return ""
    items = "".join(f"<li>{_html.escape(w)}</li>" for w in warnings)
    return f'<div class="warnings"><strong>Warnings</strong><ul class="bare">{items}</ul></div>'


def render_dashboard_html(data: DashboardData) -> str:
    """Render a :class:`DashboardData` to a single self-contained HTML string."""
    cards_html = "".join(_render_card(c) for c in data.cards)
    return _HTML_TEMPLATE.format(
        title=_html.escape(data.title),
        generated_at=_html.escape(data.generated_at),
        warnings_block=_render_warnings(data.warnings),
        cards_html=cards_html,
        estimator_table=_render_estimator_table(data.estimator_rows),
        regime_table=_render_regime_table(data.regime_coverage),
        findings_block=_render_findings(data.cec_findings),
        artefacts_block=_render_artefacts(data.artefacts),
    )


def build_dashboard(
    source: Any,
    out: Path,
    *,
    title: str = "lub evidence dashboard",
    now: _dt.datetime | None = None,
    format: str = "html",
) -> Path:
    """Build a self-contained dashboard from any :class:`EvidenceSource`.

    Args:
        source: Anything satisfying :class:`EvidenceSource`. For
            back-compat, a directory path (``Path`` or ``str``) is also
            accepted and gets wrapped in :class:`DirEvidenceSource`
            automatically.
        out: Output file path. Parent directory is created if missing.
        title: Title shown at the top of the dashboard.
        now: Override the timestamp shown in the header. Mostly for tests.
        format: Renderer key (default ``"html"``). Any name registered
            via :func:`register_evidence_renderer` is accepted.

    Returns:
        The path the dashboard was written to (same as ``out``).
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = collect_dashboard_data(source, title=title, now=now)
    from lub.reports.dashboard_protocols import get_evidence_renderer

    renderer = get_evidence_renderer(format)
    out.write_text(renderer(data), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Renderer Protocol conformance + auto-registration (pass-34 refactor)
# ---------------------------------------------------------------------------

# Mark render_dashboard_html as EvidenceRenderer-conformant (content_type).
render_dashboard_html.content_type = "text/html"  # type: ignore[attr-defined]

from lub.reports.dashboard_protocols import (  # noqa: E402
    EvidenceSource,
)
from lub.reports.dashboard_protocols import (  # noqa: E402
    register_evidence_renderer as _register_evidence_renderer,
)

_register_evidence_renderer("html", render_dashboard_html)  # type: ignore[arg-type]
