# third_party/ruflo/

This directory is the **single allowed home** for code copied verbatim
from [`ruvnet/ruflo`](https://github.com/ruvnet/ruflo) (MIT licensed,
npm package: `claude-flow`) into `llm-uncertainty-banking`.

## Why this exists

`lub` core (`src/lub/`) is an original contribution by the project
owner and is the basis of an EB-2 NIW petition. To keep that argument
clean, copied code is segregated here -- the source-tree structure
itself signals which lines are original and which are imported from
ruflo.

The full policy lives in
`planning/ADRs/ADR-003_ruflo_pattern_adoption_policy_2026-04-25.md`.

## Status (2026-04-25, pass 26)

**No source files have been copied yet.** This directory ships
infrastructure only:

- `README.md` -- this file (policy explainer + attribution template).
- `CANDIDATES.md` -- list of ruflo files identified as good candidates
  for verbatim copy, awaiting counsel review.
- `NOTICE` -- MIT license text from ruflo, ready to apply once any
  copy lands.

The first commit that adds a copied file must:

1. Reference ADR-003 in the commit message.
2. Cite counsel sign-off (counsel name + date).
3. Use the attribution template below at the top of the copied file.

## Attribution template (every copied file must carry this)

```python
# Adapted from ruvnet/ruflo, MIT licensed.
# See third_party/ruflo/NOTICE for the full license text.
#
# Copy date: YYYY-MM-DD
# Source path: <path-in-ruvnet/ruflo>
# Source commit: <upstream commit SHA>
# Counsel sign-off: <counsel name>, <YYYY-MM-DD>
#
# This file lives in third_party/ruflo/ and is NOT imported from
# src/lub/ directly. The lub core consumes it only via the documented
# adapter at <link to adapter>, if any.
```

## What does NOT belong here

- Files inspired by ruflo patterns but written from scratch in Python
  -- those go in `src/lub/`. (Examples: `src/lub/runtime/swarm_config.py`
  borrows the data shape from `swarm.config.ts` but is original code.)
- ruflo configuration files used at runtime (npm `claude-flow`
  install, MCP plugin manifests). Those stay in their installed
  location; we never copy them.
- TypeScript or JavaScript source. `lub` is Python only; copying TS
  would just be dead weight.
