# DESIGN_DECISIONS.md — Hand-writing outline for Rafael

**⚠️ IMPORTANT: Do NOT let an LLM fill this file in.**

The point of `DESIGN_DECISIONS.md` is to be **Rafael's voice** — a human engineering-memoir artifact that an adjudicator can contrast with LLM-generated prose elsewhere in the repo. It is the strongest Prong 2 "well-positioned to advance the endeavor" evidence in the repository because no one but Rafael can write it.

**How to use this outline:**

1. Open a blank `DESIGN_DECISIONS.md` in the repo root (create it if it does not exist).
2. Read each numbered question below.
3. Write a 1-3 paragraph answer in your own voice. Keep it conversational, technical, occasionally imperfect — the imperfections are evidence of authorship.
4. Do not paste the outline questions into the final file — use them as prompts, then delete this outline file when done (or keep it committed as an audit trail; your call).
5. Target total length: 2,500-4,500 words. Anything shorter reads thin; anything longer reads padded.

**Estimated time:** 3-5 hours, single sitting preferred (tonal consistency is part of the signal).

**Author voice reminder:** You are a Brazilian PhD candidate writing for an audience of (a) open-source engineers who might contribute, (b) academic reviewers who might cite, and (c) a USCIS adjudicator three years from now. Write for the first two — the third benefits when the first two are well served.

---

## Section 1 — Why this library exists at all (why not just use X?)

Questions to answer:

1.1. **What problem did you keep hitting that existing tools didn't solve?** Describe the moment you realized `lm-evaluation-harness` / TruLens / Ragas / DeepEval did not give you what a model-risk reviewer would actually need. Be specific — a single concrete example from your own experience (anonymized if BRB-sourced) carries more weight than a survey.

1.2. **Why an AI RMF mapping instead of a generic eval framework?** Reviewers will ask whether this is "just another eval library with marketing skin." Answer in your voice: what does the AI RMF layer buy that a generic report does not?

1.3. **Why banking specifically, not healthcare / insurance / legal?** Even one sentence is fine — but it must be *your* sentence, not a generic justification.

---

## Section 2 — Architectural decisions

2.1. **Why 5 layers (L1 Wrappers → L5 Reporter), strict downward imports only?** What went wrong in an earlier version that made you adopt this? (Or: what did you predict would go wrong, and what evidence convinced you?)

2.2. **Why a uniform `ModelBackend` ABC instead of just importing HuggingFace / OpenAI clients directly in the estimators?** Write the argument for the abstraction from the perspective of someone who will add a new backend in 2027.

2.3. **Why Apache 2.0 and not MIT / BSD-3 / GPL / AGPL?** Adjudicators and OSS community both read license choices as character statements. Explain yours.

2.4. **Why Python 3.11+ as minimum?** Why not 3.10 (still widely supported) or 3.12+ (narrower but modern)? What features actually required 3.11?

---

## Section 3 — Estimator choices

3.1. **Why these four estimators for v0.1 (token-logprob, semantic-entropy, self-consistency, split-conformal) and not others?** Answer for each: what does it buy that the other three don't?

3.2. **Why Kuhn et al. 2023 semantic-entropy instead of Farquhar et al. 2024 discrete-semantic-entropy?** (Or if you used both — why?)

3.3. **What failure modes did you encounter with `cross-encoder/nli-deberta-v3-small` on numeric QA, and how did you handle them?** This is the concrete engineering narrative that proves you actually ran this on banking data, not just plugged in library calls. The Week 2 Raghunathan email is pre-empting a question about this — your answer here should be consistent with that email.

3.4. **Why split conformal and not full conformal / jackknife+ / CV+?** What tradeoff did you accept?

3.5. **What estimator did you almost ship but cut, and why?** (Eigenscore? P(True)? Lexical similarity? Write the cut justification — cuts are evidence of judgment.)

---

## Section 4 — Calibration and metrics

4.1. **Why ECE, Brier, and AUROC-for-refusal specifically?** What does each one catch that the others miss?

4.2. **What did you find when you first ran the metrics on Qwen2.5-0.5B against FinQA?** Numbers if you have them — and the interpretation you drew at the time, not the polished one after the fact.

4.3. **When a calibration metric disagrees with another (e.g., good ECE but bad Brier), which one do you trust for banking use and why?**

---

## Section 5 — Benchmark design

5.1. **Why FinQA + ConvFinQA + TAT-QA + a small hand-crafted Brazilian set?** Why those four and not, say, finance-bench, BizBench, or SEC-filings QA?

5.2. **Why 20 hand-crafted Brazilian regulatory items instead of 200?** Document the scoping choice. What would 200 have given you that 20 doesn't?

5.3. **Explain the synthetic-vs-real data line you drew.** What is in `data/br_regulatory.jsonl` and what did you deliberately exclude?

5.4. **Did you use any LLM to help generate or review the hand-crafted items?** If yes, disclose how. Honest disclosure beats pretended purity.

---

## Section 6 — The NIST AI RMF mapping (the wedge)

6.1. **Which MEASURE sub-categories did you target in v0.1 (2.3 / 2.7 / 2.8 / 2.9) and why those?** Why not 2.4 / 2.5 / 2.6?

6.2. **How did you decide which metric maps to which sub-category?** This is the core intellectual contribution of the library. Spend effort here — 2-3 paragraphs minimum.

6.3. **What mapping did you almost ship but revise, and what changed your mind?**

6.4. **Why markdown + HTML as the report format, not PDF or JSON?** (What does a model-risk reviewer actually do with the file?)

---

## Section 7 — Testing and coverage

7.1. **Why 732 tests / 93% coverage as the target?** Why not higher — at what point does coverage chasing become vanity?

7.2. **Which test would you write first if you could only have one?** The "smoke test of the whole pipeline" answer is too easy; give a specific one.

7.3. **Any test you almost deleted and then were glad you kept?**

---

## Section 8 — What you chose NOT to build (and why)

8.1. **Why no streamlit demo in v0.1?** Stretch feature — explain the cut.
8.2. **Why no LangChain integration in v0.1?** (This one re-enters in v0.3 as the agent wrapper — acknowledge that arc.)
8.3. **Why no red-team / jailbreak suite?** Arguably a great fit for banking. Explain why you cut it.
8.4. **Why no web UI / SaaS hosted version?** (This is the big one — answer carefully. Petition-strength argument: keep lub as a library, not a product.)

---

## Section 9 — The v0.3 direction (added 2026-04-23)

9.1. **Why add an agent wrapper (`src/lub/agents/`) at all, given the "does it strengthen the AI RMF report?" rule?** Connect the extension to the rule — show the intellectual continuity, not a break.

9.2. **Why LangGraph as the first adapter, not ruflo or CrewAI?** (Engineering answer + strategic answer — be honest about both.)

9.3. **What are you most worried about with this extension?** Write the worry in your own voice — reviewers weigh honest self-critique.

---

## Section 10 — What would you redesign if starting over?

10.1. Name three things you would do differently if starting the library today with today's knowledge. At least one should be a regret, not a brag.

10.2. **What will you defer to v1.0 that you wish you had time for now?**

10.3. **Where do you think someone will fork this library and do it better than you?** (Or: "where *should* someone fork and do better, because it would serve the ecosystem?")

---

## Section 11 — Acknowledgments (personal, not boilerplate)

11.1. Name three specific papers / libraries / people whose prior work made this possible. For each, say specifically what they contributed to your thinking.

11.2. (Optional) Name any collaborator or reviewer whose feedback changed a specific design decision. Write which decision.

---

## Section 12 — How to read this file

12.1. Close the document with 2-3 sentences on what the file is and is not. Make clear it is a design memoir, not a specification — specs live in the docs, this is the *why*.

---

## Final self-check before committing

- [ ] Every section has at least one answer in first-person voice ("I decided," "I tried," "we ran into").
- [ ] At least one regret, at least one cut, at least one honest uncertainty appears somewhere.
- [ ] No phrases that read as LLM boilerplate ("leveraging," "robust ecosystem," "paradigm shift," "unlock," "delve into," "cutting-edge").
- [ ] At least two concrete numbers from your own experience (benchmark result, time-to-fix, lines-of-code cut).
- [ ] At least one Portuguese-language comment or phrase somewhere — your accent in writing is a feature, not a bug, for petition purposes.
- [ ] Total length 2,500-4,500 words.
- [ ] Commit with a GPG-signed commit: `git commit -S -m "docs: write DESIGN_DECISIONS.md (human-authored)"`.

---

*When done: delete this outline file or commit it as `_scratch/DESIGN_DECISIONS_OUTLINE_2026-04-23.md` for audit trail. The `DESIGN_DECISIONS.md` itself lives at the repo root.*
