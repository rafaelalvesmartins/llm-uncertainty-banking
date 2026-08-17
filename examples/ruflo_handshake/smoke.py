# Copyright 2026 Rafael Martins Alves -- Apache-2.0

"""
Post-ADR-002 ruflo handshake -- end-to-end smoke example.

Per ADR-002 (2026-04-25), the recommended user-facing entry point for
``llm-uncertainty-banking`` is **not** ``UncertaintyPipeline`` directly,
but a calibrated swarm pack handed to a ruflo runtime. This script
demonstrates the full handshake without requiring a live ruflo Node.js
process: it builds two ``CalibratedAgent`` workers, materializes them
into ruflo-shaped agents via :func:`lub.runtime.build_swarm_pack`, and
verifies each output satisfies :class:`RufloAgentProtocol`.

Run::

    cd llm-uncertainty-banking
    python examples/ruflo_handshake/smoke.py

Expected output: each worker name + a `[OK]` confirmation line, then
a final summary. No network calls, no real LLM. Uses ``DummyBackend``
deterministic mode so the script is hermetic and reproducible.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the script self-contained: prepend src/ if running from the repo root
# without `pip install -e .`. Skipped silently if lub is already importable.
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
SRC = REPO_ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    """Run the smoke and exit 0 on success, 1 on failure."""
    from lub.agents.adapters.ruflo import RufloAgentProtocol
    from lub.agents.core import CalibratedAgent
    from lub.agents.policies import RefusalPolicy
    from lub.runtime import SwarmMemberSpec, build_swarm_pack
    from lub.uncertainty.token_logprob import TokenLogprobEstimator
    from lub.wrappers.dummy import DummyBackend

    backend = DummyBackend()

    class BaselReporter(CalibratedAgent):
        """Toy CalibratedAgent that quotes the prompt back, gated by UQ."""

        prompt_template = "BASEL_PILLAR3: {q}"

        def parse(self, raw: str) -> str:
            return raw.strip()

    class CETReporter(CalibratedAgent):
        prompt_template = "CET1_LOOKUP: {q}"

        def parse(self, raw: str) -> str:
            return raw.strip()

    specs = [
        SwarmMemberSpec(
            name="basel_reporter",
            description="Basel III Pillar 3 reporter",
            agent_factory=lambda: BaselReporter(
                backend=backend,
                uncertainty=TokenLogprobEstimator(),
                policy=RefusalPolicy(threshold=0.5),
            ),
            tags=("regulatory", "basel-iii"),
        ),
        SwarmMemberSpec(
            name="cet1_reporter",
            description="Common Equity Tier 1 ratio reporter",
            agent_factory=lambda: CETReporter(
                backend=backend,
                uncertainty=TokenLogprobEstimator(),
                policy=RefusalPolicy(threshold=0.7),
            ),
            tags=("regulatory", "cet1"),
        ),
    ]

    pack = build_swarm_pack(specs)

    # Verify each worker satisfies the Protocol.
    failures = 0
    print("=" * 60)
    print("Post-ADR-002 ruflo handshake smoke")
    print("=" * 60)
    for shaped in pack:
        name = shaped.name
        is_protocol = isinstance(shaped, RufloAgentProtocol)
        tags = shaped.metadata.get("tags", [])
        if is_protocol and tags:
            print(f"  [OK]    {name:18s} tags={tags}")
        else:
            print(f"  [FAIL]  {name:18s} protocol={is_protocol} tags={tags}")
            failures += 1

    print("-" * 60)
    print(f"  swarm_pack contains {len(pack)} ruflo-shaped workers")
    print(f"  every worker: {failures} failures, {len(pack) - failures} ok")
    print()

    if failures == 0:
        print("RESULT: handshake OK")
        print("Hand `pack` to a ruflo runtime via the JSON-RPC bridge or")
        print("the MCP plugin loader; the swarm calls .run(input) on each.")
        return 0
    else:
        print("RESULT: handshake FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
