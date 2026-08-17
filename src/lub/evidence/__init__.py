# Copyright 2026 Rafael Martins Alves
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Retrieval-augmented selective prediction.

Given a new prompt, look up the *k* most similar past prompts in the
ledger and inspect their correctness. If the neighbours were mostly
right, trust the current answer more; if they were mostly wrong,
abstain more aggressively.

This is the Ruflo "RuVector" pattern scoped to UQ: vector + graph +
historical correctness, co-located. We keep it intentionally simple
(numpy hashed TF-IDF) so deployments without torch / faiss can use it.
"""

from __future__ import annotations

from lub.evidence.protocols import (
    EvidenceStoreProtocol,
    PersistentEvidenceStoreProtocol,
)
from lub.evidence.store import EvidenceStore, Neighbour, retrieval_adjusted

__all__ = [
    "EvidenceStore",
    "EvidenceStoreProtocol",
    "Neighbour",
    "PersistentEvidenceStoreProtocol",
    "retrieval_adjusted",
]
