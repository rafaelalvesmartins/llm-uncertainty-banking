# arXiv submission checklist — `llm-uncertainty-banking` tech report

**Target submission window:** week of 2026-05-05.
**Primary:** `cs.LG`. **Cross-list:** `cs.CL`, `q-fin.CP`.
**Title (current working):** *Calibrated Uncertainty Quantification for LLMs in Regulated Banking: A Multi-Framework Compliance Library.*

---

## T-7 days — content gates

- [ ] Section 5 complete — every `TODO(real-number)` replaced. Table 5.4 pressure-tested.
- [ ] Section 6 complete — every `{bracket}` replaced. Acknowledgments hand-written.
- [ ] Appendix A (7B/8B replication) exists.
- [ ] Abstract final (≤ 250 words, cs.LG convention).
- [ ] Title final. Current working title fits arXiv metadata length (≤ 250 chars) — verify.
- [ ] Author block matches `CITATION.cff` exactly (name spelling, ORCID, affiliation).

## T-7 days — readers

- [ ] 2 external readers contacted via `READER_ASK_TEMPLATE.md`. Confirmations received.
- [ ] Overleaf or PDF draft shared, read-only. Comment capture mechanism decided (inline PDF comments, shared doc, email response).

## T-4 days — arXiv endorsement

- [ ] Endorsement for cs.LG obtained. arXiv requires one-time endorsement for first submission to any primary category; the endorser must have submitted ≥2 papers to cs.LG within the last 5 years. See https://arxiv.org/help/endorsement.
- [ ] Endorsement request email sent to a plausible senior (advisor / co-author / past collaborator). Do not ask a cold contact.

## T-3 days — LaTeX compile

- [ ] `docs/tech-report/paper.tex` compiles locally with TeX Live 2023+.
- [ ] Compiles on arXiv sandbox (https://arxiv.org/help/submit_index): upload the same tarball you intend to submit and confirm the auto-compile succeeds.
- [ ] Font-embedding clean (no Type 3 fonts; arXiv flags these).
- [ ] Figures: PDF preferred over PNG for vector content. All figures under `docs/tech-report/plots/`.
- [ ] Bibliography: single `references.bib`, compiled with BibTeX or biblatex-biber. No `.bbl` committed unless arXiv requires it (check style guide).

## T-2 days — reader feedback incorporated

- [ ] Both reader responses received (or one follow-up sent per template rule).
- [ ] Substantive technical changes merged into the draft with a commit trail.
- [ ] `CHANGELOG.md` under `## Unreleased` lists the key pre-submission changes.

## T-1 day — metadata & licensing

- [ ] Primary category: `cs.LG`.
- [ ] Cross-listing: `cs.CL`, `q-fin.CP`. (Verify `q-fin.CP` still exists at submission time.)
- [ ] MSC / ACM classification (optional but recommended): `68T50` (Natural language processing), `62P05` (Actuarial science and mathematical finance), `91G45` (Financial networks and systemic risk).
- [ ] License: arXiv non-exclusive license to distribute + Creative Commons CC-BY 4.0 (recommended — matches Apache 2.0 spirit of the code).
- [ ] Ancillary files uploaded:
    - `reproduce_release.sh`
    - `benchmarks/results/` JSON outputs
    - README explaining the ancillary files
- [ ] Comments field: "Code: https://github.com/rafaelmartinsalves/llm-uncertainty-banking · {N} pages · {N_figs} figures · {N_tables} tables"

## Submission day — final checks

- [ ] Submit tarball; arXiv assigns a paper ID (format: `YYMM.NNNNN`).
- [ ] Immediately paste the arXiv URL into:
    - `CITATION.cff` preferred-citation
    - `README.md` Provenance section
    - `docs/tech-report/paper.tex` abstract footnote (for the "camera-ready" version)
- [ ] Wayback Machine — archive the arXiv abstract page and PDF page.
- [ ] Google Scholar — wait ~48h for Scholar indexing, then claim the paper on your author profile.
- [ ] Papers With Code — submit the arXiv + repo pair.

## T+2 days — indexing verification

- [ ] Paper listed on arXiv listing for submission day.
- [ ] Scholar indexed the paper (search by title).
- [ ] Semantic Scholar indexed the paper.
- [ ] Papers With Code entry live, linked to repo.

## T+3 days — launch readiness

- [ ] Phase 3 HN / LinkedIn / Reddit posts ready to fire (see `planning/launch_posts/`).
- [ ] LinkedIn first post drafts explicitly reference the arXiv URL.
- [ ] arXiv URL added to LinkedIn headline or featured section.

---

## Things to NOT do before submission

- Do not post the paper publicly (GitHub, Twitter, LinkedIn, conference list) before arXiv assigns the ID. Wait for indexing.
- Do not submit to a journal simultaneously — most ML journals are arXiv-friendly but confirm policy before dual-submitting.
- Do not list "banking industry experience" in the author bio on arXiv — affiliation line is UNICAMP (research) or "independent researcher." BRB affiliation stays in the code's CITATION.cff only.
- Do not submit on a Friday — weekend moderator delays can push indexing by 48h.

---

## After submission

- [ ] Archive sent email copy.
- [ ] Capture arXiv ID + URL in evidence log (`02_Evidencias_Profissionais/YYYY-MM-DD_arxiv_submission.md`).
- [ ] Schedule T+14 day follow-up: check citation velocity, Altmetric pickup, any replies.

---

*When every box is checked and the paper is live: move to Phase 3 launch sequence.*
