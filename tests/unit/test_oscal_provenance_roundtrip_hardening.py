# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Hardening: a BenchmarkResult -> OSCAL JSON -> parsed model roundtrip
must preserve every provenance field and control mapping.

The petition's auditability claim rests on OSCAL artifacts carrying
tamper-evident provenance (which model, which data, which code, which
seed). ``render_oscal_json`` emits an OSCAL 1.1.2 Component Definition;
re-parsing it through the Pydantic ``OscalComponentDefinition`` must
return the same provenance byte-for-byte.

Why a new file rather than extending ``test_oscal_provenance_roundtrip.py``:
that test only asserts a few substrings appear in flattened JSON and
(as of writing) does not survive on Python 3.13. This one builds the
record explicitly via the ``make_benchmark_result`` fixture-helper and
asserts field-level preservation plus a byte-identical re-dump — the
strongest form of the roundtrip.

Note on fields: provenance lives in ``components[0].props`` as string
values (so numeric fields roundtrip as strings). The integrity hash is
``dataset_hash`` (64-char SHA of the eval data) with ``git_sha`` +
``repo_version`` for code provenance; there is no ``config_hash`` field in
the library.
"""

from __future__ import annotations

import json

from lub.reports.oscal import OscalComponentDefinition, render_oscal_json
from tests import make_benchmark_result

# Fixed, identifiable provenance so a roundtrip failure is unambiguous.
REPO_VERSION = "1.2.3"
DATASET_HASH = "d" * 64
GIT_SHA = "cafebabe1234"
SEED = 1234
N = 20


def _record():
    """A frozen BenchmarkResult with pinned provenance."""
    return make_benchmark_result(
        repo_version=REPO_VERSION,
        dataset_hash=DATASET_HASH,
        git_sha=GIT_SHA,
        seed=SEED,
        n=N,
    )


def _roundtrip(record) -> OscalComponentDefinition:
    """Render to OSCAL JSON and parse it back through the Pydantic model."""
    envelope = json.loads(render_oscal_json(record))
    assert "component-definition" in envelope
    return OscalComponentDefinition.model_validate(envelope["component-definition"])


def test_provenance_fields_survive_the_roundtrip() -> None:
    """Every identifying provenance field is preserved through OSCAL."""
    record = _record()
    component_def = _roundtrip(record)
    props = {p.name: p.value for p in component_def.components[0].props}

    assert props["repo_version"] == REPO_VERSION
    assert props["dataset_hash"] == DATASET_HASH
    assert props["git_sha"] == GIT_SHA
    # numeric provenance roundtrips as strings via OSCAL props
    assert props["seed"] == str(SEED)
    assert props["n"] == str(N)
    # timestamp is record-specific (default_factory now); compare to source
    assert props["timestamp"] == record.timestamp
    assert props["backend"] == record.backend
    assert props["estimator"] == record.estimator
    assert props["dataset"] == record.dataset


def test_control_mappings_survive_the_roundtrip() -> None:
    """Regulatory control-id mappings are preserved (not dropped)."""
    component_def = _roundtrip(_record())
    control_ids = [
        implemented.control_id
        for component in component_def.components
        for impl in component.control_implementations
        for implemented in impl.implemented_requirements
    ]
    assert control_ids, "no control mappings emitted"
    assert any("measure" in cid for cid in control_ids)


def test_oscal_metadata_is_pinned() -> None:
    """The emitted artifact declares OSCAL 1.1.2 and the repo version."""
    component_def = _roundtrip(_record())
    assert component_def.metadata.oscal_version == "1.1.2"
    assert component_def.metadata.version == REPO_VERSION


def test_reparse_is_byte_identical() -> None:
    """Re-dumping the parsed model reproduces the original JSON exactly —
    the tightest possible roundtrip stability check."""
    record = _record()
    original = render_oscal_json(record)
    component_def = OscalComponentDefinition.model_validate(
        json.loads(original)["component-definition"]
    )
    redumped = json.dumps(
        {"component-definition": component_def.model_dump(by_alias=True, exclude_none=True)},
        indent=2,
    )
    assert redumped == original
