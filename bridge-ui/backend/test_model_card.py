# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""Model Card / inventory endpoint (SR 11-7 §IV).

Asserts the card carries the core MRM sections and that its runtime block is
pinned to the SAME server fingerprints the audit trail / SR 11-7 crosswalk use,
so the card can't silently drift from what is actually running.

Run from the project root::

    pytest bridge-ui/backend/test_model_card.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "src"))

import server  # noqa: E402

try:
    from backend.routers import model_card as mc  # noqa: E402
except ImportError:
    from routers import model_card as mc  # type: ignore[no-redef]  # noqa: E402


def test_model_card_has_core_sections() -> None:
    card = mc.model_card()
    for key in (
        "identity",
        "runtime",
        "intended_use",
        "architecture",
        "controls",
        "limitations",
        "governance",
    ):
        assert key in card, f"missing section {key}"
    assert card["identity"]["version"] == "0.2.0"
    assert card["sr_11_7_section"].startswith("IV")
    assert card["identity"]["owner"]


def test_model_card_runtime_matches_server_fingerprints() -> None:
    rt = mc.model_card()["runtime"]
    assert rt["prompt_fingerprint"] == server._PROMPT_FINGERPRINT
    assert rt["corpus_fingerprint"] == server._CORPUS_FINGERPRINT
    assert rt["corpus_doc_count"] == server._DOC_STORE.size
    assert rt["dq_input_rules"] == len(server._DQ_INPUT.rules)
    assert rt["guard_threshold"] == round(float(server._RUNTIME_GUARD_THRESHOLD), 3)


def test_model_card_guard_threshold_tracks_runtime(monkeypatch) -> None:
    monkeypatch.setattr(server, "_RUNTIME_GUARD_THRESHOLD", 0.9)
    assert mc.model_card()["runtime"]["guard_threshold"] == 0.9


def test_model_card_lists_scope_controls_and_limitations() -> None:
    card = mc.model_card()
    assert len(card["intended_use"]["out_of_scope"]) >= 2
    assert len(card["limitations"]) >= 2
    assert len(card["architecture"]) >= 3
    assert len(card["controls"]) >= 3
