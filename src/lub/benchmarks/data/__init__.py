# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Packaged benchmark data files.

Contents shipped with the wheel:

- ``br_regulatory.jsonl`` — the BR-Regulatory QA dataset (JSONL, one
  question/answer per line) loaded by
  :class:`lub.benchmarks.br_regulatory.BRRegulatoryDataset`.
- ``README.md`` — high-level pointer to the dataset and its loader.
- ``DATASHEET.md`` — Gebru et al. (2021) "Datasheets for Datasets"
  documentation for ``br_regulatory.jsonl`` (motivation, composition,
  collection process, intended uses, distribution, maintenance).

This is a docstring-only namespace package — it adds no public Python
symbols. The data files are read directly from the package via
``importlib.resources``; see the per-benchmark ``Dataset`` subclasses
under :mod:`lub.benchmarks` for the canonical loader entry points.
"""
