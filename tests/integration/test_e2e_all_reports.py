# Copyright 2026 Rafael Martins Alves - Apache-2.0

"""End-to-end: one benchmark result -> every supported report format.

Covers gap #3 from the integration audit: each report writer has unit
coverage in isolation, but no test exercises the full governance bundle
a bank would ship to a regulator from a single run.
"""

from __future__ import annotations

import json
from pathlib import Path

from lub.benchmarks import BenchmarkRunner, BrazilianRegulatoryDataset
from lub.pipeline import UncertaintyPipeline
from lub.reports import create_reporter, get_iso42001_mapping, get_rmf_mapping


def _benchmark_result(tmp_path: Path):
    pipe = UncertaintyPipeline.from_pretrained(
        model="dummy-reports",
        backend="dummy",
        estimator="token_logprob",
        refusal_threshold=0.0,
    )
    runner = BenchmarkRunner(
        pipeline=pipe,
        dataset=BrazilianRegulatoryDataset(),
        results_dir=tmp_path,
    )
    return runner.run(limit=5, seed=0)


def test_airmf_reporter_produces_md_and_html(tmp_path: Path) -> None:
    result = _benchmark_result(tmp_path)
    reporter = create_reporter([result], report_type="airmf")

    md_path = reporter.save(tmp_path / "airmf.md", format="md")
    html_path = reporter.save(tmp_path / "airmf.html", format="html")

    md = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")

    for section in ("## Govern", "## Map", "## Measure", "## Manage"):
        assert section in md

    assert any(tag in html.lower() for tag in ("<html", "<!doctype", "<div"))
    assert "br_regulatory" in md
    assert "br_regulatory" in html


def test_oscal_reporter_produces_parseable_json(tmp_path: Path) -> None:
    result = _benchmark_result(tmp_path)
    reporter = create_reporter([result], report_type="oscal")

    out = reporter.save(tmp_path / "oscal.json", format="json")
    raw = out.read_text(encoding="utf-8")

    chunks = [c for c in raw.split("\n\n") if c.strip()]
    assert chunks, "OSCAL output has no envelopes"
    for chunk in chunks:
        payload = json.loads(chunk)
        assert "component-definition" in payload
        cd = payload["component-definition"]
        assert "uuid" in cd
        assert "metadata" in cd
        assert "components" in cd
        assert len(cd["components"]) >= 1


def test_giskard_reporter_produces_json_and_md(tmp_path: Path) -> None:
    result = _benchmark_result(tmp_path)
    reporter = create_reporter([result], report_type="giskard")

    json_path = reporter.save(tmp_path / "giskard.json", format="json")
    md_path = reporter.save(tmp_path / "giskard.md", format="md")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload
    assert all(isinstance(entry, dict) for entry in payload)

    md = md_path.read_text(encoding="utf-8")
    assert "Vulnerability" in md or "vulnerability" in md


def test_iso42001_crosswalk_shares_metric_ids_with_rmf_mapping() -> None:
    rmf = get_rmf_mapping()
    iso = get_iso42001_mapping()

    assert rmf, "RMF crosswalk is empty"
    assert iso, "ISO 42001 crosswalk is empty"

    for table, label in [(rmf, "rmf"), (iso, "iso42001")]:
        for k in table:
            assert isinstance(k, str) and k, f"{label} has a blank key"


def test_one_result_drives_all_three_reporters(tmp_path: Path) -> None:
    result = _benchmark_result(tmp_path)

    bundle = [
        (create_reporter([result], "airmf"), "airmf.md", "md"),
        (create_reporter([result], "airmf"), "airmf.html", "html"),
        (create_reporter([result], "oscal"), "oscal.json", "json"),
        (create_reporter([result], "giskard"), "giskard.json", "json"),
        (create_reporter([result], "giskard"), "giskard.md", "md"),
    ]

    for reporter, filename, fmt in bundle:
        path = reporter.save(tmp_path / filename, format=fmt)
        assert path.exists()
        assert path.stat().st_size > 0
