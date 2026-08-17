# Exhibit D-09 — Bridge demonstrator: Governança panels (captured 2026-06-10)

Prong-2 progress-to-date corroboration of the lub crosswalk + calibration.
Code version pinned by git tag `petition-exhibit-2026-07-01` (commit e6fdf22 — incl. B3 cache-confidentiality fix + P2 evidence package + P5 vulnerability scan).
Backend: FakeBackend (no real banking data). Frontend :3002 / backend :8000.

## Files
- governanca-exhibit-2026-06-10.png — full Governança tab (Pacote de Evidência, Vulnerability Scan, Fleet, Model Card, Calibração, Cobertura Regulatória, SR 11-7, AI Visibility)
- evidence_package.json — assembled model-risk evidence record (Model Card + calibration + crosswalk + SR 11-7) with sha256 content hash + timestamp; the regulator-filable export (SR 11-7 effective challenge)
- vulnerability_scan.json — adversarial probe battery (injection / credential / PII / crisis / fraud) run through the real defenses in defense-in-depth; 8/8 defended, sha256-hashed
- compliance_frameworks.json — 7 frameworks / 36 controls across jurisdictions (renders the lub crosswalk; maps E-02/E-03/E-04/E-08)
- compliance_sr_11_7.json — SR 11-7 three-pillar mapping (calibration metrics graded pass/fail)
- calibration.json — real ECE/Brier/refusal-AUROC + reliability bins (per-bin n + 95% CI)
- model_card.json — SR 11-7 §III model inventory (live fingerprints)
- fleet.json — portfolio (1 LIVE Bridge row + 6 MOCK siblings)
- version.json, health.json — runtime fingerprints + fake-mode confirmation

## Framing (per Prong-1 RFE #2 / #5)
Describe as the lub crosswalk/calibration *rendered live* — "bridge/translate", NOT "implement/apply".
Prong-2 evidence only; do NOT use for Prong-1 (government-anchored).
