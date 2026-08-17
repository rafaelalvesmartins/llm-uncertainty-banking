# Tier 2 Deployment Guide — Regional and Mid-Sized Institutions

Companion to [`docs/integration_tiers.md`](../integration_tiers.md) (Tier 2).
An **implementation pattern** for banking organizations under Federal Reserve
Regulation YY Categories III and IV — the beachhead tier of the initial
24-month focus — not a guaranteed adoption outcome. For the full end-to-end
dummy-backend wiring walkthrough, start from the
[Tier 1 guide](tier-1-systemically-important.md); this guide covers what is
*different* at Tier 2.

## Profile

Formal MRM programs with smaller validation teams and focused model
inventories. Adoption is configured for a **defined set of priority
workflows** (regulatory/compliance document summarization, entity
extraction, documentation tasks) rather than an institution-wide inventory.
Second-line review is typically **partner-enabled** (RegTech providers,
model-risk boutiques, advisory firms).

## Integration pattern

1. **Scope selection.** Run the readiness assessment to pick 1–3 priority
   workflows. Do not deploy inventory-wide in the first cycle.
2. **Hybrid second line.** The framework runs alongside the existing
   validation workflow; the integration partner operates it under the
   institution's effective-challenge expectation (SR 11-7 Pillar II).
   Knowledge transfer to the internal MRM team is a deliverable of the
   engagement, not an afterthought.
3. **Per-use-case thresholds.** Unlike Tier 1 (central threshold policy),
   configure calibration/refusal thresholds **per use case**:

   ```python
   from lub.reports.crosswalk import Regime, get_all_controls_for_regime

   # Evidence obligations for the regimes this deployment reports against.
   controls = {
       regime: get_all_controls_for_regime(regime)
       for regime in (Regime.NIST_GENAI, Regime.ISO_42001)  # adjust per GRC scope
   }
   ```

   Validate the wiring first against the deterministic `dummy` backend
   exactly as in the Tier 1 guide, then swap the model provider.
4. **GRC hand-off.** OSCAL Assessment Results (see `lub.reports.oscal`,
   e.g. `OscalBatchReporter`) flow into the institution's existing GRC
   tooling; the partner should map OSCAL findings to the GRC system's
   control catalog once, then automate.

## Configuration checklist

- [ ] Priority workflows documented (readiness assessment §6.3.2 framing)
- [ ] Partner roles vs. institution roles recorded (effective challenge stays with the institution)
- [ ] Thresholds set per use case, with rationale in the model file
- [ ] OSCAL output ingested by GRC tooling; evidence retention period set
- [ ] Knowledge-transfer plan with dates (internal MRM self-sufficiency)

## References

Regulation YY tailoring (12 CFR 252); SR 11-7 / Revised Interagency
Supervisory Guidance on MRM (Apr 17, 2026); `docs/integration_tiers.md`
Cross-Tier Summary.
