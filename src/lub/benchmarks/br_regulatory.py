# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Brazilian regulatory QA dataset loader.

Loads hand-crafted questions on BCB Resolution 4.658 (cybersecurity) and
Basel III from a packaged JSONL file. Each record is sourced from publicly
available BCB or BIS documents; see ``data/README.md`` for provenance.
No BRB-internal or otherwise proprietary content is included.
"""

from __future__ import annotations

from typing import ClassVar

from lub.benchmarks._jsonl_dataset import JsonlDataset


class BrazilianRegulatoryDataset(JsonlDataset):
    """Hand-crafted Brazilian banking-regulation QA dataset."""

    REGISTRY_KEY = "br_regulatory"

    _FILENAME: ClassVar[str] = "br_regulatory.jsonl"
    _NAME: ClassVar[str] = "br_regulatory"
    _VERSION: ClassVar[str] = "0.1.0"
    _METADATA_KEYS: ClassVar[tuple[str, ...]] = ("source_url", "topic")
    _MISSING_HINT: ClassVar[str] = (
        "this dataset is hand-crafted and bundled with the package; "
        "if missing, reinstall lub or check benchmarks/data/README.md."
    )


__all__ = ["BrazilianRegulatoryDataset"]
