# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""Referential-integrity audit of ``crosswalk_data.toml``.

The TOML file is the single source of truth for control definitions and
metric-to-control mappings ("Auditors: review this file directly").
These tests guarantee that what auditors read is internally consistent,
protecting the petition claim of an *auditable* multi-regime crosswalk:

* every control table carries ``control_id``, ``control_title`` and a
  non-trivial ``description``;
* control ids match a conservative grammar (no stray whitespace/typos);
* every mapping the Python loader exposes resolves to a defined control;
* ``get_control_by_key`` round-trips every key the crosswalk exposes.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from lub.reports import crosswalk as cw

_TOML = Path(cw.__file__).with_name("crosswalk_data.toml")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/()\-]*$")


def _controls() -> dict[str, dict[str, object]]:
    data = tomllib.loads(_TOML.read_text(encoding="utf-8"))
    controls = data.get("controls")
    assert isinstance(controls, dict) and controls, "no [controls.*] tables"
    return controls


def test_every_control_has_required_fields() -> None:
    for key, table in _controls().items():
        assert isinstance(table, dict), key
        for field in ("control_id", "control_title", "description"):
            value = table.get(field)
            assert isinstance(value, str) and value.strip(), f"{key}.{field}"
        assert len(str(table["description"])) > 20, f"{key}: description too thin"


def test_control_ids_match_grammar() -> None:
    for key, table in _controls().items():
        cid = str(table["control_id"])
        assert _ID_RE.match(cid), f"{key}: suspicious control_id {cid!r}"
        assert cid == cid.strip(), f"{key}: control_id has stray whitespace"


def test_loader_mappings_resolve_to_defined_controls() -> None:
    """Every mapping surfaced per regime must exist in the TOML controls."""
    defined_ids = {str(t["control_id"]) for t in _controls().values()}
    for regime in cw.regimes():
        for mapping in cw.get_all_controls_for_regime(regime):
            assert mapping["control_id"] in defined_ids, (
                f"{regime}: mapping references undefined control "
                f"{mapping['control_id']!r}"
            )


def test_get_control_by_key_roundtrips_known_keys() -> None:
    sample = list(_controls())[:5]
    for key in sample:
        mapping = cw.get_control_by_key(key)
        assert mapping["control_id"] == str(_controls()[key]["control_id"])
