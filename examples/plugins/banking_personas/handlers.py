# Copyright 2026 Rafael Martins Alves — Apache-2.0

"""banking_personas — skeleton plugin pack of 10 calibrated banking agents.

Per RUFLO_VS_LUB_GAP §4.3, this is **post-filing v0.4+ scope**. The
skeleton ships now (counsel-friendly, no orchestrator import, no
network) so the contract surface is reviewable; real persona logic
will land after the petition is filed and counsel approves the framing.

Usage::

    from examples.plugins.banking_personas.handlers import build_pack
    from lub.runtime import build_orchestrated_pack

    pack = build_orchestrated_pack(build_pack())
    # hand `pack` to ruflo via JSON-RPC bridge or MCP plugin loader.

The factory below produces ten ``OrchestratedAgentSpec`` rows, one per
persona in ``manifest.json``. Each spec wires a ``StubBankingAgent``
(deterministic, DummyBackend-only) to the uncertainty estimator and
threshold listed in the manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

from lub.agents.core import CalibratedAgent
from lub.agents.policies import RefusalPolicy
from lub.runtime.engine import OrchestratedAgentSpec
from lub.uncertainty import (
    SelfConsistency,
    SemanticEntropy,
    Verbalized,  # type: ignore[attr-defined]  # may be VerbalizedOneShot
)
from lub.wrappers.dummy import DummyBackend

_MANIFEST = Path(__file__).parent / "manifest.json"


class StubBankingAgent(CalibratedAgent):
    """Deterministic stub. Returns a one-line acknowledgement.

    Real personas (post-filing) will subclass this and override
    ``prompt_template`` / ``parse`` with banking-specific logic.
    """

    prompt_template = "[stub-{persona}] Question: {q}"

    def __init__(self, persona: str, **kwargs):
        super().__init__(**kwargs)
        self._persona = persona

    def parse(self, raw: str) -> str:
        return f"<{self._persona}-stub-response> {raw.strip()[:80]}"


def _resolve_uncertainty(name: str, backend):
    """Map manifest uncertainty string -> instantiated estimator.

    Falls back to SelfConsistency for any estimator not yet wired in
    the stub; the real plugin pack will resolve the full set.
    """
    if name == "semantic_entropy":
        return SemanticEntropy(backend)
    if name == "verbalized":
        return Verbalized(backend)
    # default — covers self_consistency, p_true, conformal, ensemble,
    # claim_level, epistemic_aleatoric in the stub.
    return SelfConsistency(backend, n_samples=4)


def build_pack() -> list[OrchestratedAgentSpec]:
    """Return the 10-persona orchestrated-pack spec list.

    Reads ``manifest.json`` so the tags / thresholds / RMF mappings
    stay declarative and reviewable without touching Python.
    """
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    backend = DummyBackend()
    specs: list[OrchestratedAgentSpec] = []
    for persona in manifest["personas"]:
        name = persona["name"]
        threshold = float(persona.get("refusal_threshold", 0.6))
        uq_name = persona.get("uncertainty", "self_consistency")
        rmf = persona.get("rmf_subcategory", "")
        tags = tuple(persona.get("tags", ()))

        def _factory(_name=name, _uq_name=uq_name, _threshold=threshold):
            return StubBankingAgent(
                persona=_name,
                backend=backend,
                uncertainty=_resolve_uncertainty(_uq_name, backend),
                policy=RefusalPolicy(threshold=_threshold),
            )

        specs.append(
            OrchestratedAgentSpec(
                name=name,
                description=persona["description"],
                agent_factory=_factory,
                tags=tags,
                metadata={
                    "rmf_subcategory": rmf,
                    "uncertainty": uq_name,
                    "refusal_threshold": threshold,
                    "skeleton": True,  # marker: stub, not production
                },
            )
        )
    return specs


__all__ = ["StubBankingAgent", "build_pack"]
