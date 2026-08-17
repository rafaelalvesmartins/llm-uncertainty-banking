# `examples/ruflo_handshake/` — post-ADR-002 entry-point smoke

Demonstrates the recommended user entry point per ADR-002:
`lub.runtime.build_swarm_pack(...)`.

The script builds two `CalibratedAgent` workers (a Basel III Pillar 3
reporter and a CET1 ratio reporter), materializes them via the
`SwarmMemberSpec` factory, and verifies each output object satisfies
`RufloAgentProtocol`. Hermetic — uses `DummyBackend`, no network, no
real LLM, no ruflo Node.js process required.

Run from the repo root:

```bash
python examples/ruflo_handshake/smoke.py
```

Expected output: 2 `[OK]` lines + `RESULT: handshake OK`.

If you have a real ruflo process running, the same `pack` object can be
handed to its JSON-RPC bridge (see
`Visa_Genius/apps/api/src/visa_genius/orchestrator/ruflo_bridge.py` for
a reference bridge). The Python side does NOT `import ruflo`.

References:
- `planning/ADRs/ADR-002_ruflo_as_orchestration_core_2026-04-25.md`
- `src/lub/runtime/ruflo_engine.py`
- `src/lub/agents/adapters/ruflo.py` (back-compat shim)
- `src/lub/agents/adapters/orchestrator.py` (generic)
