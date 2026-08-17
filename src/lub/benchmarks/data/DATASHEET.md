# Datasheet: BR-Regulatory QA Dataset

*Following the "Datasheets for Datasets" template (Gebru et al. 2021, CACM).*

---

## 1. Motivation

### Why was the dataset created?

The BR-Regulatory dataset was created to fill a specific gap in LLM evaluation:
no existing benchmark tests calibration and uncertainty quantification on
**financial regulatory text** in the intersection of international (Basel III)
and Brazilian (BCB) banking regulation. Existing financial QA benchmarks
(FinQA, ConvFinQA, TAT-QA) test numerical reasoning over financial reports
but not factual recall of regulatory rules that bank employees are expected
to know.

The dataset directly addresses a need identified in the EB-2 NIW petition
context: demonstrating that LLM uncertainty quantification matters for
regulated banking by testing on the actual type of questions a risk officer
would ask.

### Who created it?

**Rafael Martins Alves** (Banco de Brasilia / UNICAMP), as an original
contribution within the `llm-uncertainty-banking` framework. The dataset
was hand-crafted by the author based on his professional knowledge of
banking regulation, with every answer verified against publicly available
source documents.

### Who funded it?

No external funding. Created as part of the author's independent
open-source research.

---

## 2. Composition

### What does the dataset represent?

20 factual question-answer pairs about banking regulation, designed to test
whether an LLM can accurately recall specific regulatory facts and whether
its uncertainty estimator correctly identifies low-confidence answers.

### How many instances?

**20 examples** (QA pairs).

### What are the instances?

Each instance is a JSON object with:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (e.g., `brreg-001`) |
| `question` | string | English-language factual question about banking regulation |
| `gold_answer` | string | Short factual answer (typically a number, percentage, or term) |
| `source_url` | string | Public URL where the fact can be verified |
| `topic` | string | Coarse topic label (`basel3` or `bcb4658`) |

### What topics are covered?

**Topic 1: Basel III** (international framework, 14 questions)
- Minimum CET1, Tier 1, and total capital ratios
- Leverage ratio (3%)
- Liquidity Coverage Ratio (LCR) and Net Stable Funding Ratio (NSFR)
- Standardized and IRB credit risk approaches
- 2017 operational risk standardized approach
- G-SIB higher loss absorbency surcharge
- Countercyclical capital buffer

**Topic 2: BCB Resolution 4.658** (Brazilian cybersecurity regulation, 6 questions)
- Scope and applicability to financial institutions
- Cybersecurity governance requirements
- Incident response and notification timelines
- Cloud services notification obligations
- Data storage and processing requirements

### Why these topics?

- **Basel III** is the global banking capital framework. Every US, EU, and
  Brazilian bank must comply. Questions are phrased in English because Basel
  Committee documents are published in English.
- **BCB Resolution 4.658** is the Brazilian central bank's cybersecurity
  regulation. It tests the system on a less-common regulatory domain where
  LLMs are more likely to hallucinate, making it a calibration stress test.

### Is the data a sample?

No. The dataset is hand-crafted, not sampled from a larger collection.

### Are there recommended splits?

No. With 20 examples, the dataset is used as a single evaluation set.
For conformal prediction, a 50/50 calibration/test split is used.

### Does the dataset contain confidential information?

**No.** Every fact is sourced from publicly available documents on
`bis.org` and `bcb.gov.br`. No proprietary, internal, or non-public
information from any financial institution is included.

---

## 3. Collection Process

### How was the data collected?

The author manually:
1. Selected regulatory topics relevant to banking LLM deployments
2. Formulated factual questions that have unambiguous correct answers
3. Extracted gold answers from the source documents
4. Recorded the source URL for each fact
5. Verified each answer against the official document

### Who was involved in the collection?

**Rafael Martins Alves only.** No crowdsourcing, no annotation tools,
no inter-annotator agreement needed (factual questions with verifiable
answers).

### What was the time frame?

March-April 2026.

### Were any ethical review processes conducted?

Not applicable. The dataset contains only publicly available regulatory
facts, not personal data or human subjects.

---

## 4. Preprocessing / Cleaning

### Was any preprocessing applied?

Minimal:
- Questions normalized to English
- Answers shortened to the minimal factual snippet (e.g., "4.5%" rather
  than "The minimum CET1 ratio under Basel III is 4.5%")
- Source URLs verified to be accessible as of April 2026

### Is raw data available?

The JSONL file is the raw data. No intermediate processing steps exist.

---

## 5. Uses

### What tasks is the dataset intended for?

1. **Calibration benchmarking**: Testing whether LLM uncertainty estimators
   correctly identify low-confidence answers on regulatory questions
2. **Refusal detection**: Testing whether the system refuses to answer when
   it does not know the regulatory fact
3. **Cross-domain stress testing**: Using BCB questions as out-of-distribution
   probes for models trained primarily on English financial text

### What tasks should it NOT be used for?

- **Regulatory compliance decisions** -- 20 questions cannot certify a model
- **Training data** -- too small; would overfit immediately
- **Legal advice** -- answers are simplified factual snippets

### Who are the intended users?

- Model risk management (MRM) teams evaluating LLM deployments
- ML engineers benchmarking uncertainty estimators on financial text
- Researchers studying calibration in domain-specific contexts

---

## 6. Distribution

### How is the dataset distributed?

Packaged inside the `llm-uncertainty-banking` Python wheel under
`src/lub/benchmarks/data/br_regulatory.jsonl`.

### License?

Apache License 2.0 (same as the library). The underlying regulatory facts
are in the public domain; the question phrasings are the author's original
contribution.

### Are there any restrictions?

No restrictions on use, modification, or redistribution beyond the
Apache 2.0 license terms.

---

## 7. Maintenance

### Who maintains the dataset?

Rafael Martins Alves (author). Updates will be versioned alongside the
library releases.

### Will the dataset be updated?

Yes. Planned expansions:
- Additional Basel III questions (countercyclical buffers, FRTB)
- BCB Resolution 4.893 (AI-specific requirements)
- Portuguese-language variants of existing questions
- Questions on NIST AI RMF sub-categories (meta-regulatory)

### How can users contact the maintainer?

Via GitHub issues on the `llm-uncertainty-banking` repository.

---

## 8. Relevance to SR 11-7

This dataset provides evidence for **SR 11-7 Pillar 2 (Model Validation)**:

| SR 11-7 Section | How BR-Regulatory Contributes |
|-----------------|-------------------------------|
| V.A Outcomes Analysis | Accuracy on regulatory QA directly measures outcomes |
| V.B Conceptual Soundness | ECE/Brier on these questions tests calibration theory |
| V.C Benchmarking | Comparison across estimators on same regulatory domain |
| V.D Effective Challenge | BCB questions serve as out-of-distribution challenge |

The dataset is relevant to **US banks** because:
- Basel III is the same framework US banks follow (via Fed/OCC implementation)
- The evaluation methodology (calibration metrics + conformal prediction)
  transfers directly to any regulatory QA domain
- The BCB questions test cross-jurisdictional regulatory knowledge, which
  is relevant for multinational banks

---

## Citation

```bibtex
@misc{alves2026brregulatory,
  title={BR-Regulatory: A Hand-Crafted Regulatory QA Dataset for
         LLM Calibration Benchmarking in Banking},
  author={Alves, Rafael Martins},
  year={2026},
  note={Distributed as part of llm-uncertainty-banking (Apache 2.0)},
  url={https://github.com/rafaelmartinsalves/llm-uncertainty-banking}
}
```

---

*Datasheet version: 1.0*
*Date: 2026-04-18*
*Author: Rafael Martins Alves*
