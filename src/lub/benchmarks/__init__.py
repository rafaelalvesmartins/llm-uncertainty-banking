# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""L4 regulated-domain benchmarks.

Dataset classes are lazy-loaded on first access via ``__getattr__``.
The ``_LAZY_REGISTRY`` in :mod:`lub.benchmarks.base` ensures
``Dataset.get_dataset_cls("br_regulatory")`` works without eagerly
importing all dataset modules.
"""

from lub.benchmarks.base import Dataset, Example
from lub.benchmarks.protocol import (
    BenchmarkProtocol,
    list_external_benchmarks,
    register_external_benchmark,
)
from lub.benchmarks.runner import BenchmarkRunner, content_hash, exact_match

_LAZY_MAP: dict[str, tuple[str, str]] = {
    "BrazilianRegulatoryDataset": ("lub.benchmarks.br_regulatory", "BrazilianRegulatoryDataset"),
    "FinQADataset": ("lub.benchmarks.finqa", "FinQADataset"),
    "ConvFinQADataset": ("lub.benchmarks.convfinqa", "ConvFinQADataset"),
    "TATQADataset": ("lub.benchmarks.tatqa", "TATQADataset"),
    "GermanCreditDataset": ("lub.benchmarks.credit_scoring", "GermanCreditDataset"),
    "AustralianCreditDataset": ("lub.benchmarks.credit_scoring", "AustralianCreditDataset"),
    "FPBDataset": ("lub.benchmarks.financial_sentiment", "FPBDataset"),
    "FiQASADataset": ("lub.benchmarks.financial_sentiment", "FiQASADataset"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_MAP:
        module_path, class_name = _LAZY_MAP[name]
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AustralianCreditDataset",
    "BenchmarkProtocol",
    "BenchmarkRunner",
    "BrazilianRegulatoryDataset",
    "Dataset",
    "Example",
    "FiQASADataset",
    "FPBDataset",
    "GermanCreditDataset",
    "content_hash",
    "exact_match",
    "list_external_benchmarks",
    "register_external_benchmark",
]
