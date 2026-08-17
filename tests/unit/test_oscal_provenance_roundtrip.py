# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Audit-trail loop: a rendered OSCAL document must be self-describing.

Petition claim (ARCHITECTURE §2.4 / Cap 1.4): evidence records are
"auditable, per-response" — an auditor reading the OSCAL JSON months
later can identify the producing package/version without external
context. This test builds a minimal ``BenchmarkResult`` generically
(so it survives additive schema changes), renders the OSCAL component
definition, and asserts the JSON round-trips with identifying metadata.

Written 2026-07-01; sandbox runs Python 3.10 while lub targets 3.11+,
so first execution/validation happens Windows-side (same convention as
the CEC test batch of 2026-04-25).
"""

from __future__ import annotations

import enum
import inspect
import json
import typing as t

import pytest
from pydantic import BaseModel

from lub import types as lub_types
from lub.reports import oscal as oscal_mod


def _minimal_value(annotation: t.Any) -> t.Any:
    """Build a defensible placeholder for a required pydantic field."""
    origin = t.get_origin(annotation)
    # typing.Union (Optional[X]/Union[X,Y]) OR the X | Y form, whose origin is
    # types.UnionType. NB: UnionType lives in `types`, not `typing` — the old
    # getattr(t, "UnionType", None) was always None, so plain types (origin None)
    # wrongly matched and hit args[0] on an empty list.
    if origin is t.Union or origin is type(int | None):
        args = [a for a in t.get_args(annotation) if a is not type(None)]
        return None if len(args) < len(t.get_args(annotation)) else _minimal_value(args[0])
    if origin in (list, set, tuple, frozenset):
        return origin() if origin is not tuple else ()
    if origin is dict:
        return {}
    if annotation in (str, t.Any):
        return "petition-roundtrip"
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    if inspect.isclass(annotation):
        if issubclass(annotation, enum.Enum):
            return next(iter(annotation))
        if issubclass(annotation, BaseModel):
            return _minimal_instance(annotation)
    return "petition-roundtrip"


def _minimal_instance(model: type[BaseModel]) -> BaseModel:
    kwargs: dict[str, t.Any] = {}
    for name, field in model.model_fields.items():
        if field.is_required():
            kwargs[name] = _minimal_value(field.annotation)
    return model(**kwargs)


def _render(record: BaseModel) -> str:
    """Render OSCAL JSON via whichever public entry point is available."""
    candidates = ("render_oscal_json", "build_component_definition")
    for name in candidates:
        fn = getattr(oscal_mod, name, None)
        if fn is None:
            continue
        sig = inspect.signature(fn)
        kwargs: dict[str, t.Any] = {}
        for pname, param in sig.parameters.items():
            if param.default is not inspect.Parameter.empty:
                continue
            lowered = pname.lower()
            if "record" in lowered or "result" in lowered:
                ann = param.annotation
                kwargs[pname] = record if "Benchmark" in str(ann) and "list" not in str(ann).lower() else [record]
            else:
                kwargs[pname] = _minimal_value(param.annotation)
        out = fn(**kwargs)
        if isinstance(out, str):
            return out
        if isinstance(out, BaseModel):
            return out.model_dump_json(by_alias=True)
        return json.dumps(out)
    pytest.fail(f"no known OSCAL entry point among {candidates}")


def test_oscal_json_roundtrips_with_identifying_metadata() -> None:
    record = _minimal_instance(lub_types.BenchmarkResult)
    rendered = _render(record)

    doc = json.loads(rendered)  # (1) valid JSON
    flat = json.dumps(doc).lower()

    # (2) it is an OSCAL component definition with metadata
    assert "component" in flat, "no component structure in OSCAL output"
    assert "metadata" in flat, "no metadata block in OSCAL output"

    # (3) self-describing provenance: the producing package is identifiable
    assert "lub" in flat or "llm-uncertainty-banking" in flat, (
        "OSCAL output does not identify the producing package — "
        "audit-trail claim (ARCHITECTURE §2.4) would not hold"
    )
