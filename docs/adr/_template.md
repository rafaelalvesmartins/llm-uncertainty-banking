---
id: "NNNN"
title: "<short imperative title>"
status: proposed | accepted | superseded | deprecated
date: YYYY-MM-DD
supersedes: null
superseded_by: null
invariants: {}
---

# ADR NNNN — <title>

## Context

What's the problem? What forces are at play? Keep this 3–6 sentences.
State the constraint that makes this decision non-obvious.

## Decision

What did we decide? Be concrete and specific. If the decision pins
a number, a library choice, or a contract, state it explicitly.
Use an `invariants:` block in the front-matter for any value that
should be machine-checkable (CI assertions, importlinter contracts,
schema-version pins, etc.).

## Consequences

What we accept by deciding this. Include both the upside (what we
gain) and the downside (what we give up). One paragraph or a short
bulleted list. If the decision is reversible, name the conditions
under which it would be revisited.

## Alternatives considered

Briefly, what else was on the table and why it lost. Two to four
bullets is enough; this is not an essay.

## References

- Code: `src/...` / `tests/...`
- Specs: `planning/NN_*.md`
- Upstream: Bibtex citation or URL of the source paper / standard

---

## Authoring rules

- One decision per ADR. If you find yourself writing "and also...",
  split into two ADRs.
- Front-matter `id` is monotonically increasing. Never re-use a
  number, even after deprecation.
- `status` transitions: `proposed` → `accepted` → (optional)
  `superseded` / `deprecated`. Don't skip states.
- When superseding, set both `superseded_by` here and `supersedes`
  on the new ADR. Cross-link is enforced by `lub.governance.adr`.
- Keep it short. The point of an ADR is to capture *why*, not to
  re-document *how*. Implementation details belong in module
  docstrings.
