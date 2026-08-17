# Prompt: Market Research — LLM Uncertainty in Banking

Use this prompt with any LLM that has web search (Claude with web search,
ChatGPT with browsing, Perplexity, etc.) to map the competitive landscape
and validate the lub library's positioning.

Copy everything below the line and paste into the LLM.

---

## Prompt

I'm researching the market for **LLM uncertainty quantification and AI
governance tooling in regulated banking**. I need you to do deep web
research across four areas. Be specific — cite company names, product
names, URLs, pricing models, and exact feature gaps. No vague summaries.

### 1. Job Postings — What Banks Actually Hire For

Search LinkedIn, Indeed, Glassdoor, and bank career pages for roles that
combine LLM/AI with model risk management, uncertainty quantification,
or AI governance in financial services.

Search these exact queries:
- `"model risk" "LLM" OR "large language model" site:linkedin.com/jobs`
- `"AI governance" "banking" OR "financial services" site:indeed.com`
- `"uncertainty quantification" "NLP" OR "LLM" site:linkedin.com/jobs`
- `"SR 11-7" "machine learning" site:linkedin.com/jobs`
- `"NIST AI RMF" engineer OR scientist site:linkedin.com/jobs`
- `"AI risk" "banking" site:glassdoor.com/job`

For each relevant posting found, extract:
- Job title
- Company (bank or vendor)
- Required skills (especially: calibration, conformal prediction, NIST AI RMF, SR 11-7, OSCAL, EU AI Act)
- Tools/frameworks mentioned
- Salary range if available

**Key question to answer:** Do these roles mention ANY specific open-source
UQ library? Or do they say "build from scratch" / "develop internal tools"?

### 2. Competitor Products — What Exists Today

Research these specific companies and products. For each one, tell me:
(a) what they DO, (b) what they DON'T do, (c) pricing, (d) whether they
are open-source.

**AI Governance / MRM Platforms:**
- Holistic AI (holisticai.com)
- Credo AI (credo.ai)
- ValidMind (validmind.com)
- Monitaur (monitaur.ai)
- ModelOp (modelop.com)
- Fairly AI (fairly.ai)
- TrustibleAI
- Arthur AI (arthur.ai)
- Fiddler AI (fiddler.ai)
- Arize AI (arize.com)
- WhyLabs (whylabs.ai)

**LLM Evaluation / UQ Libraries:**
- LM-Polygraph (GitHub: IINemo/lm-polygraph)
- uncertainty-toolbox (GitHub: uncertainty-toolbox/uncertainty-toolbox)
- UQLM (GitHub: cvs-health/uqlm)
- Giskard (GitHub: Giskard-AI/giskard)
- TruLens (GitHub: truera/trulens)
- DeepChecks (deepchecks.com)
- Galileo (rungalileo.io)

For each, answer these specific questions:
1. Does it produce NIST AI RMF reports? (not just "mentions NIST")
2. Does it produce OSCAL-format output?
3. Does it implement conformal prediction for LLMs?
4. Does it compute ECE, Brier, PRR, AUROC on LLM outputs?
5. Does it map metrics to SR 11-7 model validation requirements?
6. Does it support multi-regime compliance (US + EU + Basel + ISO)?
7. Is it designed for banking specifically or general-purpose?
8. Does it work with multiple LLM backends (HF, OpenAI, Anthropic, vLLM)?

### 3. Regulatory Demand — What Regulators Are Asking For

Search for recent (2025-2026) regulatory guidance, speeches, and
consultation papers on AI/LLM risk in banking:

- Federal Reserve / OCC / FDIC guidance on AI model risk
- NIST AI 600-1 (GenAI Profile) adoption status
- EU AI Act implementation timeline for financial services
- Basel Committee (BCBS) AI/ML discussion papers
- Bank of England / PRA AI guidance
- MAS (Singapore) FEAT principles for AI
- Any regulatory enforcement actions related to AI in banking

**Key question:** Is there a regulatory requirement (existing or proposed)
that specifically asks banks to quantify LLM uncertainty or produce
machine-readable compliance artifacts?

### 4. The Gap Analysis — What Nobody Does

Based on your research in sections 1-3, answer:

1. **Is there ANY open-source library that combines LLM uncertainty
   quantification with NIST AI RMF report generation?**

2. **Is there ANY tool (open-source or commercial) that produces OSCAL
   Component Definitions from LLM calibration metrics?**

3. **Is there ANY tool that maps LLM calibration metrics to SR 11-7
   model validation requirements automatically?**

4. **Is there ANY tool that implements conformal prediction for LLMs
   AND produces regulatory compliance reports?**

5. **How do banks currently validate LLM outputs for model risk
   purposes?** (Manual? Internal tools? Vendor platforms?)

6. **What is the typical cost for a bank to build this capability
   internally?** (Team size, timeline, estimated cost)

7. **What salary range do "AI Model Risk" roles command at US banks?**
   (This is relevant for EB-2 NIW Prong 3 — demonstrating the
   petitioner's work addresses a well-compensated need)

### Output Format

Structure your answer as:

```
## 1. Job Market Analysis
[findings with specific postings]

## 2. Competitor Matrix
| Product | NIST RMF | OSCAL | Conformal | SR 11-7 | Multi-regime | Banking-specific | Open-source |
|---------|----------|-------|-----------|---------|--------------|------------------|-------------|
| ...     | ...      | ...   | ...       | ...     | ...          | ...              | ...         |

## 3. Regulatory Landscape
[findings with specific documents]

## 4. Gap Analysis
[answers to the 7 questions above]

## 5. Positioning Statement
[one paragraph: how should llm-uncertainty-banking position itself
given these findings?]
```

### Context (do NOT include in the research — this is background for you)

The library I'm positioning is called `llm-uncertainty-banking` (lub).
It is an open-source Python library (Apache 2.0) that:
- Implements 22 UQ estimators across 7 families
- Computes 16 calibration metrics (ECE, Brier, AUROC, PRR, etc.)
- Produces NIST AI RMF reports (HTML/MD)
- Produces OSCAL Component Definitions and Assessment Results
- Maps metrics to 6 regulatory frameworks (NIST, EU AI Act, BCBS, BCB, ISO 23894, ISO 42001)
- Includes OCC 2011-12 findings triage (FINDING/OBSERVATION/PASS)
- Works with HuggingFace, OpenAI, Anthropic, vLLM backends
- Has a governance layer (guard + policies + rails)
- Targets regulated banking specifically

I want to know: does anything else do this? If not, how big is the gap?
