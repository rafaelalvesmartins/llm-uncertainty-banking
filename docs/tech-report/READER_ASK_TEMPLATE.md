# Reader ask — email template

Send to 2 external readers after Sections 5 and 6 are filled with real numbers. One calibration researcher + one banking model-risk practitioner is the ideal pair.

**Timing:** send 7 days before target arXiv submission date. Ask for a 48-72 hour turnaround. Any longer and the submission slips; any shorter and the reader can't engage seriously.

**Do not mention:** EB-2 NIW, immigration, petition evidence. The ask is purely technical. The review carries more weight when it is not contaminated by non-technical framing.

---

## Template

**Subject:** Quick technical review ask — short arXiv draft on LLM calibration for banking

**To:** `<reader>@<institution>`
**From:** Rafael's personal email (not BRB corporate)
**CC:** (none on the first email)

---

{Greeting by appropriate title; "Hi {firstname}" if prior correspondence exists, otherwise "Dear Prof./Dr. {lastname},"}

I'm finishing a short arXiv tech report on an open-source library I built
for uncertainty quantification of LLM outputs in regulated banking
(`llm-uncertainty-banking`, Apache-2.0, Python). The paper's main
contribution is a NIST AI RMF-aligned report generator that maps
calibration metrics to specific sub-categories — the estimators and
metrics are well-established from the literature; the novelty is the
compliance-artifact layer.

Before I submit, I would really value a pair of expert eyes on the
draft. Specifically, I'd welcome a read focused on:

1. **Whether the AI RMF mapping (Table 5.4) is defensible** — are the
   metric-to-sub-category assignments ones a model-risk reviewer could
   actually use, or do any read as forced?
2. **Whether Section 5's limitations are honest enough** — especially
   around {semantic-entropy failure modes on numeric QA / conformal
   coverage claims under autoregressive generation / small calibration
   set size}.
3. **Any obvious missing references** — the related-work section
   cites {Kuhn 2023, Wang 2022, Kadavath 2022, Angelopoulos-Bates
   2021, …} but I'm sure I've missed work in your specific area.

The draft is {N} pages. A 48-hour turnaround would be ideal; I'm
targeting an arXiv submission on {YYYY-MM-DD}. If that window doesn't
work, even a few bullet-point comments on any of the three bullets
above would be useful, or a "pass" with no guilt.

Draft:  https://github.com/rafaelmartinsalves/llm-uncertainty-banking/blob/main/docs/tech-report/paper.pdf
Repo:   https://github.com/rafaelmartinsalves/llm-uncertainty-banking

Thank you for your time.

Best,
Rafael Martins Alves
{ORCID link}  ·  {Google Scholar link}

---

## Reader selection rubric

| Candidate type | What they catch | Ideal background |
|---|---|---|
| Calibration researcher | Math rigor, conformal claims, failure modes | Published on ECE, conformal prediction, semantic entropy, or selective prediction |
| Banking model-risk practitioner | Whether the AI RMF mapping is usable; whether the thresholds are realistic | SR 11-7 validator, CCAR / DFAST model-risk background, or fintech compliance lead |
| Compliance / governance researcher | Whether the AI RMF framing aligns with how standards bodies read it | NIST AI Safety Institute, AI governance academics, CISA adjacent |
| LLM systems engineer | Whether the library's API design is usable | Maintainer of lm-eval-harness, Inspect, Guardrails, or Giskard |

Aim for at least two of the first three types. The fourth is a luxury.

## Filing readers' responses

- Save the received response as `02_Evidencias_Profissionais/YYYY-MM-DD_reader_{lastname}_response.pdf` (export email, full headers preserved).
- If the reader gives substantive technical feedback that changes the draft, note the change in the `CHANGELOG.md` under the pre-release section and, in the final arXiv acknowledgments, thank them by name (only with their written permission).
- If no response within 7 days, send **one** short follow-up of the form: "No pressure if not — just flagging that I'll submit on {date} regardless and wanted to make sure the email didn't get lost." Never a second follow-up.

## Do not

- Do not send simultaneously to more than 2 readers — dilutes the ask.
- Do not offer co-authorship for a 48-hour review (asymmetric, creates awkward incentives).
- Do not share a preview to anyone inside BRB before arXiv submission.
- Do not mention the petition in any form.
