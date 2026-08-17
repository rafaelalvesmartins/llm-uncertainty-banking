# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Credit-scoring benchmark datasets — German Credit & Australian Credit.

Two classical UCI credit-approval datasets surfaced as LLM-friendly QA
tasks: each applicant record becomes a structured English prompt that
asks the model whether to approve or deny the loan, with the gold
answer being the label. This mirrors the conversion used by PIXIU
(Xie et al. 2023) but stays within LUB's simple JSONL loader protocol.

Both datasets are small (1000 + 690 rows) and public. They are
distributed packaged inside the wheel under ``benchmarks/data/`` so
LUB stays hermetic; re-generation from UCI is covered by
``scripts/fetch_datasets.sh``.

References:
    German Credit — UCI ML Repository, Hofmann (1994).
    Australian Credit — UCI ML Repository, Quinlan (1987).
    LLM framing — PIXIU / FLARE, Xie et al. 2023 (arXiv:2306.05443).
"""

from lub.benchmarks._jsonl_dataset import JsonlDataset


class GermanCreditDataset(JsonlDataset):
    """UCI German Credit (statlog) — 1000 applicants, 2-class."""

    REGISTRY_KEY = "german_credit"
    _FILENAME = "german_credit.jsonl"
    _NAME = "german_credit"
    _METADATA_KEYS = ("label",)


class AustralianCreditDataset(JsonlDataset):
    """UCI Australian Credit Approval — 690 applicants, 2-class."""

    REGISTRY_KEY = "australian_credit"
    _FILENAME = "australian_credit.jsonl"
    _NAME = "australian_credit"
    _METADATA_KEYS = ("label",)


__all__ = ["AustralianCreditDataset", "GermanCreditDataset"]
