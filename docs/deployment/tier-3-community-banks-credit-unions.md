# Tier 3 Deployment Guide — Community Banks and Credit Unions

Companion to [`docs/integration_tiers.md`](../integration_tiers.md) (Tier 3).
An **implementation pattern** for OCC-supervised community banks (≤ $30B
total assets per OCC News Release 2025-89) and NCUA-supervised federally
insured credit unions — reached through **vendor-mediated adoption** (core
service providers, vendor-licensed platforms, AI-governance platforms).
Not a guaranteed adoption outcome. Start from the
[Tier 1 guide](tier-1-systemically-important.md) for the dummy-backend
wiring; this guide covers Tier-3 specifics.

## Profile

Smaller MRM teams; inventories centered on credit scoring and fraud
detection; typically no in-house generative-AI validation staffing. OCC
Bulletin 2025-26 (Oct 6, 2025) articulates tailored expectations; the June
2023 *Interagency Guidance on Third-Party Relationships* applies — using a
vendor does **not** diminish the institution's own responsibility.

## Integration pattern (vendor-operated, institution-owned)

1. **Single use case first.** Begin with internal-documentation
   summarization or one equivalent low-blast-radius workflow.
2. **Conservative defaults.** Default refusal thresholds are configured
   conservatively at this tier — prefer abstention over confident error;
   loosen only with observed calibration evidence.
3. **Audit trail is load-bearing.** The NCUA does not currently have
   statutory authority to examine technology service providers directly
   (GAO-25-107197), so the per-response evidence records the framework
   emits are the institution's primary independent artifact. Retain the
   OSCAL Assessment Results (`lub.reports.oscal`) under the institution's
   own retention policy, not only the vendor's.
4. **Contractual mapping.** The vendor operates the pipeline; the
   institution owns: threshold sign-off, evidence retention, periodic
   review cadence, and exit/portability (Apache-2.0 licensing means the
   framework itself carries no license fee — integration, hosting,
   security review and staffing remain institutional decisions).

```python
# Minimal evidence-obligation view for a Tier 3 scope (verified API):
from lub.reports.crosswalk import Regime, get_all_controls_for_regime

for regime in (Regime.NIST_GENAI,):          # start narrow
    for control in get_all_controls_for_regime(regime):
        print(control["control_id"], "-", control["control_title"])
```

## Configuration checklist

- [ ] One use case selected and documented
- [ ] Refusal thresholds at conservative defaults, with sign-off recorded
- [ ] OSCAL evidence records retained by the institution (not vendor-only)
- [ ] Third-party risk file updated per June 2023 Interagency Guidance
- [ ] Exit/portability clause references the open-source distribution

## References

OCC Bulletin 2025-26; OCC NR 2025-89; GAO-25-107197; Interagency
Third-Party Guidance (Jun 2023); `docs/integration_tiers.md`.
