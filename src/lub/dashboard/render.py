# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""lub.dashboard.render -- render a DashboardSnapshot to HTML or JSON.

Pure functions of the snapshot. Stdlib-only (no Jinja2). The HTML
renderer mirrors the layout of ``docs/dashboard_mockup.html`` but is
data-driven; the JSON renderer dumps the snapshot for API consumers.

Spec: planning/29_Dashboard_Spec_2026-04-25.md section 3.
Status: real implementation as of pass 31 (2026-04-25); both renderers
auto-register in lub.dashboard.protocols._RENDERER_REGISTRY at import
time as part of the pass-33 genericity refactor (they carry
.content_type attributes so they satisfy the SnapshotRenderer Protocol).
"""

from __future__ import annotations

import dataclasses
import html
import json
from datetime import datetime
from typing import Any

import structlog

from lub.dashboard.query import DashboardSnapshot

_LOG = structlog.get_logger("lub.dashboard.render")

# Chart.js CDN coordinates -- extracted so a local-bundle swap (or a CDN
# pin update) can happen without editing the HTML template body.
CHARTJS_VERSION = "4.4.1"
CHARTJS_CDN_URL = f"https://cdn.jsdelivr.net/npm/chart.js@{CHARTJS_VERSION}/dist/chart.umd.min.js"

__all__ = ["CHARTJS_CDN_URL", "CHARTJS_VERSION", "render_html", "render_json"]


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return dataclasses.asdict(o)
    to_dict = getattr(o, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception as exc:
            # Don't let a single bad to_dict() break the whole dashboard
            # render -- log the failure and emit a marker the consumer can
            # spot in the JSON output (instead of silently coercing to
            # repr() and pretending nothing went wrong).
            _LOG.warning(
                "dashboard.json_serialise_failed",
                obj_type=type(o).__name__,
                error=str(exc),
            )
            return {
                "_error": "to_dict_failed",
                "type": type(o).__name__,
                "repr": repr(o),
            }
    return repr(o)


def render_json(snapshot: DashboardSnapshot, *, indent: int | None = 2) -> str:
    """Serialise a :class:`DashboardSnapshot` to a JSON string.

    Uses :func:`_json_default` so dataclasses, ``datetime`` instances,
    and any object exposing a ``to_dict()`` method round-trip cleanly.
    Pass ``indent=None`` for a compact single-line payload (used
    internally by :func:`render_html` to embed the snapshot in the
    rendered page); the default ``indent=2`` is preferred for API
    responses where readability matters.

    Auto-registered as the ``"json"`` renderer in
    :mod:`lub.dashboard.protocols` (``content_type = "application/json"``).
    """
    payload = dataclasses.asdict(snapshot)
    return json.dumps(payload, indent=indent, default=_json_default, sort_keys=False)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>LUB Dashboard -- {tenant}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <!-- TODO(supply-chain): pin chart.js@4.4.1 with SRI hash. Generate with:
       curl -sL https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js \
         | openssl dgst -sha384 -binary | openssl base64 -A
       then add integrity="sha384-..." to the <script> tag below. -->
  <script src="{chartjs_url}" crossorigin="anonymous" referrerpolicy="no-referrer"></script>
  <style>
    :root {{
      --bg: #f7f8fa; --panel: #fff; --border: #e3e6eb;
      --text: #1a1a1a; --muted: #6b7280; --accent: #2b5fd9;
      --good: #1f9d55; --warn: #d97706; --bad: #c0392b;
    }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
      margin: 0; padding: 24px; background: var(--bg); color: var(--text); }}
    header {{ margin-bottom: 16px; }}
    h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
    h2 {{ font-size: 14px; margin: 0 0 8px 0; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.05em; }}
    .meta {{ color: var(--muted); font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 16px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--border);
      border-radius: 6px; padding: 16px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.03); }}
    .span-3 {{ grid-column: span 3; }}
    .span-6 {{ grid-column: span 6; }}
    .span-12 {{ grid-column: span 12; }}
    .kpi {{ display: flex; flex-direction: column; }}
    .kpi-value {{ font-size: 28px; font-weight: 600; }}
    .kpi-label {{ color: var(--muted); font-size: 12px;
      text-transform: uppercase; letter-spacing: 0.05em; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }}
    th {{ font-weight: 600; color: var(--muted); }}
    .badge {{ display: inline-block; padding: 2px 6px; font-size: 11px; border-radius: 3px; }}
    .badge.passed {{ background: #e6f4ed; color: var(--good); }}
    .badge.refused {{ background: #fdecea; color: var(--bad); }}
    pre.oscal {{ background: #f4f5f7; border: 1px solid var(--border);
      border-radius: 4px; padding: 12px; font-size: 11px;
      overflow-x: auto; max-height: 300px; }}
    .empty {{ color: var(--muted); font-style: italic; }}
  </style>
</head>
<body>
  <header>
    <h1>LUB Dashboard <span class="meta">/ tenant: {tenant}</span></h1>
    <div class="meta">Period: {period_start} -- {period_end} &middot; git: {git_sha}</div>
  </header>
  <section class="grid">
    <div class="panel span-3 kpi">
      <span class="kpi-label">Decisions in window</span>
      <span class="kpi-value">{decisions_in_window}</span>
    </div>
    <div class="panel span-3 kpi">
      <span class="kpi-label">Abstention rate</span>
      <span class="kpi-value">{abstention_rate_pct}</span>
    </div>
    <div class="panel span-3 kpi">
      <span class="kpi-label">Correctness ({n_outcomes_recorded} labelled)</span>
      <span class="kpi-value">{correctness_rate_pct}</span>
    </div>
    <div class="panel span-3 kpi">
      <span class="kpi-label">Meta-calibration ECE</span>
      <span class="kpi-value">{meta_calibration_ece_str}</span>
    </div>
    <div class="panel span-6">
      <h2>Recent decisions</h2>
      {recent_decisions_html}
    </div>
    <div class="panel span-6">
      <h2>Meta-calibration reliability</h2>
      <canvas id="reliabilityChart" width="400" height="240"></canvas>
    </div>
    <div class="panel span-12">
      <h2>OSCAL Assessment-Results envelope</h2>
      <pre class="oscal">{oscal_pretty}</pre>
    </div>
  </section>
  <script>
    const SNAPSHOT = {snapshot_json};
    if (window.Chart) {{
      const ctx = document.getElementById('reliabilityChart').getContext('2d');
      const buckets = (SNAPSHOT.cec_report && SNAPSHOT.cec_report.meta_calibration_buckets) || [];
      const labels = buckets.map(b => b.bucket_low.toFixed(1));
      const conf = buckets.map(b => b.confidence_mean);
      const acc = buckets.map(b => b.accuracy);
      new Chart(ctx, {{
        type: 'line',
        data: {{ labels: labels, datasets: [
          {{ label: 'Accuracy', data: acc, borderColor: '#2b5fd9' }},
          {{ label: 'Confidence', data: conf, borderColor: '#999', borderDash: [5, 5] }}
        ] }},
        options: {{ scales: {{ y: {{ min: 0, max: 1 }} }} }}
      }});
    }}
  </script>
</body>
</html>
"""


def _format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _format_ece(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _render_recent_decisions(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="empty">No decisions in the selected window.</div>'
    head = (
        "<table><thead><tr>"
        "<th>When</th><th>Domain</th><th>Model / Tier</th><th>Decision</th><th>Reason</th>"
        "</tr></thead><tbody>"
    )
    body_parts: list[str] = []
    for r in rows:
        passed = bool(r.get("passed"))
        badge_cls = "passed" if passed else "refused"
        body_parts.append(
            "<tr>"
            f"<td>{html.escape(str(r.get('created_at', '')))}</td>"
            f"<td>{html.escape(str(r.get('domain', '')))}</td>"
            f"<td>{html.escape(str(r.get('model', '')))} / "
            f"{html.escape(str(r.get('tier') or '-'))}</td>"
            f'<td><span class="badge {badge_cls}">'
            f"{html.escape(str(r.get('decision', '')))}</span></td>"
            f"<td>{html.escape(str(r.get('reason') or ''))}</td>"
            "</tr>"
        )
    return head + "".join(body_parts) + "</tbody></table>"


def render_html(snapshot: DashboardSnapshot) -> str:
    """Render a snapshot as a self-contained HTML document."""
    oscal_pretty = json.dumps(
        snapshot.oscal_envelope
        or {"_status": "no OSCAL envelope; lub.challenge unavailable or empty"},
        indent=2,
        default=_json_default,
    )
    snapshot_json = render_json(snapshot, indent=None)
    # Escape `<`, `>`, `&`, U+2028, U+2029 so embedded JSON cannot break
    # out of the <script> tag (the </script> XSS vector). This is the
    # standard inline-JSON escaping pattern.
    snapshot_json = (
        snapshot_json.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return _HTML_TEMPLATE.format(
        chartjs_url=html.escape(CHARTJS_CDN_URL, quote=True),
        tenant=html.escape(snapshot.tenant),
        period_start=html.escape(snapshot.period_start.isoformat()),
        period_end=html.escape(snapshot.period_end.isoformat()),
        git_sha=html.escape(snapshot.git_sha),
        decisions_in_window=snapshot.decisions_in_window,
        abstention_rate_pct=_format_pct(snapshot.abstention_rate),
        correctness_rate_pct=_format_pct(snapshot.correctness_rate),
        n_outcomes_recorded=snapshot.n_outcomes_recorded,
        meta_calibration_ece_str=_format_ece(snapshot.meta_calibration_ece),
        recent_decisions_html=_render_recent_decisions(snapshot.recent_decisions),
        oscal_pretty=html.escape(oscal_pretty),
        snapshot_json=snapshot_json,
    )


# ---------------------------------------------------------------------------
# Renderer Protocol conformance + auto-registration (pass-33 refactor)
# ---------------------------------------------------------------------------

# Mark the two stdlib renderers as SnapshotRenderer-conformant (content_type)
render_html.content_type = "text/html"  # type: ignore[attr-defined]
render_json.content_type = "application/json"  # type: ignore[attr-defined]

from lub.dashboard.protocols import register_renderer as _register_renderer  # noqa: E402

_register_renderer("html", render_html)  # type: ignore[arg-type]
_register_renderer("json", render_json)  # type: ignore[arg-type]
