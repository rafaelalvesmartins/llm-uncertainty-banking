# Candidates for verbatim copy from ruvnet/ruflo

**Status:** Awaiting counsel review (per ADR-003).
**Last updated:** 2026-04-25, pass 26.

This file lists code in `ruvnet/ruflo` (MIT) that meets ADR-003
criteria 1 (MIT) and 2 (self-contained), but has **not yet** been
reviewed by counsel under criterion 3.

Each candidate has:

- **Path** in the upstream repo
- **Why this is useful** (one paragraph)
- **Why this is safe to copy** (license + self-containment proof)
- **Estimated effort to reimplement instead** (so counsel can pick
  copy vs. clean-room reimplementation)

## Candidate 1: V3 shared types index

- **Upstream path:** `v3/src/shared/types/index.ts`
- **Why useful:** Defines the canonical type vocabulary (`AgentStatus`,
  `AgentRole`, `AgentType`, `SwarmConfig`, etc.) that the rest of the
  ruflo source consumes. Having the same Python-translated names in
  `lub` makes interop reading easier.
- **Why safe:** Type-definition file only (no runtime logic). MIT
  licensed at the file head and repo-root LICENSE. ~~~300 lines.
- **Effort to reimplement:** Low (a couple of hours). We have already
  reimplemented a subset in `src/lub/runtime/swarm_config.py` (pass
  26), so the marginal value of copying is small.
- **Recommendation:** Counsel-defer. We are already shipping the
  Python equivalent.

## Candidate 2: JSON-RPC framing utility

- **Upstream path:** `v3/@claude-flow/integration/src/jsonrpc/*.ts`
  (file path TBD on actual upstream).
- **Why useful:** A correct JSON-RPC 2.0 framing implementation is
  surprisingly fiddly (request IDs, batch handling, error envelopes).
  The Visa Genius bridge already does this in Python, but a side-by-side
  comparison with the ruflo implementation would catch corner cases.
- **Why safe:** Pure framing logic, no runtime dependencies. MIT.
- **Effort to reimplement:** Medium (already done in Visa Genius).
- **Recommendation:** Counsel-defer. Use as a reference, not a copy.

## Candidate 3: Performance-target schema

- **Upstream path:** the `PerformanceTargets` interface in
  `v3/src/shared/types/index.ts`.
- **Why useful:** Same as Candidate 1; the type-vocabulary point.
- **Why safe:** Type-definition only.
- **Recommendation:** Already reimplemented in
  `src/lub/runtime/swarm_config.py` (`PerformanceTargets` dataclass).
  No copy needed.

## Decision rule

If counsel signs off on a candidate, follow the procedure in ADR-003:
add the file under `third_party/ruflo/`, prepend the attribution
header from `README.md`, reference ADR-003 in the commit message, and
update this CANDIDATES.md to mark it adopted.

If counsel rejects, the candidate stays here as a "considered and
declined" record, useful for the petition narrative ("we
considered copying X from ruflo and declined; here's why").
