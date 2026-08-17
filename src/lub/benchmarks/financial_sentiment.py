# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Financial sentiment benchmark datasets — FPB & FiQA-SA.

Two established financial-sentiment classification benchmarks converted
to QA form (the prompt asks for one of ``positive`` / ``negative`` /
``neutral``). Relevant to the banking path because sentiment on
earnings-call transcripts and regulatory commentary is a direct input
to credit memos and market-risk dashboards.

- **FPB** (Financial PhraseBank, Malo et al. 2014): ~4,845 sentences
  from financial news, labeled by 16 annotators with a majority
  agreement threshold. Public, CC-BY-NC-SA 3.0.
- **FiQA-SA** (FiQA Task 1, Maia et al. 2018): aspect-based sentiment
  on financial microblogs + news headlines, scored on continuous
  [-1, 1]. Public.

LLM-QA framing follows the PIXIU (Xie et al. 2023) convention.

References:
    Malo, P., Sinha, A., Korhonen, P., Wallenius, J., & Takala, P.
    (2014). *Good debt or bad debt: Detecting semantic orientations in
    economic texts.* JASIST 65(4).
    Maia, M., Handschuh, S., Freitas, A., et al. (2018). *WWW'18 Open
    Challenge: Financial Opinion Mining and Question Answering.*
    PIXIU / FLARE — Xie et al. 2023 (arXiv:2306.05443).
"""

from lub.benchmarks._jsonl_dataset import JsonlDataset


class FPBDataset(JsonlDataset):
    """Financial PhraseBank (Malo et al. 2014) 3-class sentiment."""

    REGISTRY_KEY = "fpb"
    _FILENAME = "fpb.jsonl"
    _NAME = "fpb"
    _METADATA_KEYS = ("aspect",)


class FiQASADataset(JsonlDataset):
    """FiQA Task 1 aspect-based financial sentiment (Maia et al. 2018)."""

    REGISTRY_KEY = "fiqa_sa"
    _FILENAME = "fiqa_sa.jsonl"
    _NAME = "fiqa_sa"
    _METADATA_KEYS = ("aspect",)


__all__ = ["FPBDataset", "FiQASADataset"]
