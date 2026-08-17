# Brazilian Regulatory QA Dataset

A small hand-crafted question-answer set used as an in-library regression
benchmark for regulated-domain LLM evaluation. Scope is intentionally narrow:
20 factual questions over two topic areas.

## Topics

- **Basel III** — minimum capital ratios, leverage ratio, LCR, NSFR,
  standardized and IRB credit risk approaches, the 2017 operational risk
  standardized approach, and the G-SIB higher loss absorbency surcharge.
- **BCB Resolution 4.658 (April 2018)** — the Central Bank of Brazil's
  cybersecurity policy regulation for financial institutions, including
  governance, incident response, and cloud-services notification.

## Provenance

Every example in `br_regulatory.jsonl` is drawn from **publicly available
sources only**:

- Bank for International Settlements — `https://www.bis.org/` (Basel
  framework documents, including d424, d295, d445, and bcbs238).
- Banco Central do Brasil — `https://www.bcb.gov.br/` (Resolution 4.658
  normative page).

Each line includes a `source_url` field pointing to the public document
the fact was taken from.

## What this dataset is NOT

- **Not proprietary.** No content from any specific financial institution,
  internal policy, client data, or non-public regulatory communication is
  included.
- **Not a substitute for legal or compliance advice.** Answers are
  simplified factual snippets for benchmarking LLM calibration and should
  not be relied on for regulatory decisions.
- **Not a complete regulatory test set.** 20 questions is sufficient to
  surface gross miscalibration and regression, not to certify a model.

## Schema

Each line of `br_regulatory.jsonl` is a JSON object with fields:

| field         | type   | description                                    |
|---------------|--------|------------------------------------------------|
| `id`          | string | unique identifier, e.g. `brreg-001`            |
| `question`    | string | English-language factual question              |
| `gold_answer` | string | short factual answer                           |
| `source_url`  | string | public URL where the fact can be verified      |
| `topic`       | string | coarse-grained topic label                     |

## License

This dataset file is released under the same Apache 2.0 license as the
rest of `llm-uncertainty-banking`. The underlying facts are in the public
domain; the question phrasings are the author's own.
