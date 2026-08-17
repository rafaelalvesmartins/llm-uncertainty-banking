---
id: "0010"
title: "Method count vs registry-key count duality"
status: accepted
date: 2026-04-25
supersedes: null
superseded_by: null
invariants:
  canonical_method_count: 22
  registry_key_count: 23
  difference_explanation: "VerbalizedOneShot and VerbalizedTwoShot register as two keys but count as one method"
  petition_narrative_uses: 22
---

# ADR 0010 — Method count vs registry-key count duality

## Context

The library exposes uncertainty estimators in two ways:

1. As a **method count** for narrative / paper / petition purposes:
   "the library implements N estimators in K families."
2. As a **registry-key count** for code introspection: every
   `Estimator` subclass with a `REGISTRY_KEY` is callable via
   `lub.uncertainty.get(key)`.

These two counts are not identical. `VerbalizedOneShot` and
`VerbalizedTwoShot` are two prompting variants of one method
("verbalized self-assessment"); they share a paper, share a
calibration story, and share a row in `docs/estimators.md`, but
they register as separate keys for runtime dispatch.

## Decision

Both counts are canonical, used in different contexts:

- **Petition narrative, README, abstract:** 22 methods.
- **Registry / code introspection:** 23 keys.

`docs/estimators.md` carries an explicit "counting note" explaining
the split. `planning/CANONICAL_FACTS.md` pins 22 as the method
count and references this ADR for the rationale. Any new estimator
either (a) adds one row to the method table and one registry key
(both counters go up by 1) or (b) adds a new prompting variant of
an existing method (only the registry counter goes up; an ADR must
amend this one to record the new variant).

## Consequences

- Adversarial reviewers can verify both numbers and find the same
  rationale in three places.
- "22" stays stable for petition / outreach / arXiv abstract use,
  even if a future variant pushes the registry count to 24, 25.
- Trade-off accepted: a casual reader can be momentarily confused
  by the discrepancy. Mitigated by the counting note in
  `docs/estimators.md` and by every petition-facing doc citing
  the same number (22).

## Alternatives considered

- **One number only (drop one of the two).** Rejected: removing
  the registry-key count would break `lub.uncertainty.list_keys()`;
  removing the method count would force every paper / abstract to
  cite "23" with a footnote, every time.
- **Renumber to make them equal** (collapse the verbalized
  variants into one key). Rejected: the prompting variants behave
  differently and need separate calibration curves.

## References

- Method table: `docs/estimators.md` (22 rows + counting note)
- Registry: `src/lub/uncertainty/__init__.py` (23 `REGISTRY_KEY`
  entries)
- Canonical numbers: `planning/CANONICAL_FACTS.md`
- AUDIT_2026-04-25.md §3.2 — earlier "off by one" finding that
  was a false positive resolved here.
