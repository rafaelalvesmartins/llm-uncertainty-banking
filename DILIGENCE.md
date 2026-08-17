# Diligence room — everything a reviewer needs, in one place

> **Who this page is for:** a model-risk reviewer, TPRM analyst, or security
> engineer deciding whether this project can enter their evaluation pipeline.
> Every claim below links to the artefact that proves it — or says plainly
> that the artefact does not exist yet. Nothing here requires talking to us
> first.

## The one-paragraph description

`lub` measures whether an LLM deployment's stated confidence matches how often
it is actually right, in a regulated setting: uncertainty estimators,
calibration metrics, a guard that can answer / refuse / escalate / defer to a
human, an auditable decision ledger, a scheduled self-challenge with tri-state
verdicts (PASS / FAIL / INCONCLUSIVE), and machine-readable evidence (OSCAL).
Apache-2.0, air-gap-runnable.

## Verify it yourself — the artefact map

| Question a reviewer asks | Where the answer lives |
|---|---|
| What exactly do you claim, and what do you NOT claim? | [`PRICING.md`](PRICING.md) — free vs paid vs **roadmap**, marked honestly; [`docs/sr-11-7.md`](docs/sr-11-7.md) scope limits |
| What is the security posture? | [`SECURITY.md`](SECURITY.md) — including what is absent (stated, not implied) |
| Can it run inside our perimeter? | [`docs/bank-deployment.md`](docs/bank-deployment.md); the air-gapped profile (`LUB_LOCAL_ONLY`) is **enforced at construction** — see `src/lub/governance/local_only.py` for the exact scope of the guarantee |
| What components does it ship? (SBOM) | CycloneDX SBOM attached to releases by the root CI workflow (`lub-release.yml`). If the release you are looking at has no SBOM artefact, treat the claim as unproven and tell us |
| Is the calibration verdict real? | Run it: `lub challenge-nightly --ledger <your ledger>`. Tri-state, fail-closed, insufficient evidence is INCONCLUSIVE — never a pass |
| Does the project pass its own gates? | CI at the repository root: tests, mypy --strict, ruff, import-linter layer contracts. The nightly job asserts the enforcement fires |
| Can we reproduce your numbers? | Every benchmark records pip freeze + git SHA + rolling dataset SHA-256; `lub repro` re-executes and verifies within tolerance |
| Regulatory mapping? | [`docs/regulatory-triggers.md`](docs/regulatory-triggers.md) — six coded regimes, SR 11-7 cross-mapped, honesty notes inline |

## What does NOT exist today (so your checklist is faster)

- **No SOC 2 report.** Roadmap, not fact.
- **No SLA.** Community best-effort; contractual support is a paid-engagement
  item, currently roadmap.
- **No hosted service.** Single-tenant, self-deployed only.
- **No reference customer.** You would be early, and we say so.
- **No penetration test report.**

If a diligence process requires any of the above as a hard gate, this project
fails that gate today — better to know in the first five minutes.

## The posture, in one sentence

The repository's own history contains the audits where our claims were checked
against the code and corrected in the direction of the truth — we would rather
show you a FAIL we published than a PASS we cannot reproduce.

## Contact

Issues on this repository are the preferred channel — a stack trace is worth
more than a meeting.
