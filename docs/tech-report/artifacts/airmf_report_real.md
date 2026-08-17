
# AI RMF Report — llm-uncertainty-banking evaluation

_Generated: 2026-04-17T12:10:56.476442+00:00_

## Metadata

| field | value |
|-------|-------|
| Report version | 1.0 |
| Number of runs | 4 |
| Python | 3.12.3 |
| Library | llm-uncertainty-banking 0.0.1 |

## Govern

This report documents model-risk evidence for LLM-based QA systems evaluated
under the `llm-uncertainty-banking` library. Each run below is a reproducible
`BenchmarkResult` with a dataset hash and full dependency fingerprint, so that
reviewers can independently re-run and verify the numbers.

- **MANAGE 4.1** — change management: every run records its git SHA and
  `package_versions` dict, enabling point-in-time reproduction.
- **GOVERN 1.2** — accountability: the backend, estimator, and dataset used
  are first-class fields of every benchmark record.

## Map

- **Intended use:** uncertainty-aware QA for regulated banking workflows
  where answer-level confidence gates downstream automation.
- **Operational context:** offline evaluation only; no live customer data
  and no production inference is performed by this report.
- **Out of scope:** training, fine-tuning, retrieval-augmented generation
  pipelines, and agentic tool use.

## Measure


### Run 1 — hf / token_logprob / br_regulatory

| metric | value | AI RMF sub-category | trust dimension | notes |
|--------|-------|---------------------|------------------|-------|
| Accuracy | 0.0000 | MEASURE 2.3 | Efficacy | System performance: task accuracy on the evaluation set. |
| ECE | 0.9637 | MEASURE 2.9 | Robustness | Reliability: expected calibration error of confidence scores. |
| Refusal AUROC | 0.5000 | MEASURE 2.7 | Robustness | Safety and robustness: AUROC of confidence as a refusal signal. |
| Miscalibration Area | 0.9994 | MEASURE 2.9 | Robustness | Reliability: area between reliability curve and identity diagonal. |
| Sharpness | 0.0246 | MEASURE 2.9 | Efficacy | Reliability: variance of confidence (decisiveness of the estimator). |
| Missing Ratio | 0.0000 | MEASURE 2.7 | Robustness | Safety: fraction of examples the system refused to answer. |
| PRR | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: prediction-rejection ratio vs oracle (1.0 = oracle, 0.0 = random). |
| Brier | 0.9293 | MEASURE 2.9 | Robustness | Reliability: Brier score (mean squared error of confidence forecasts). |
| RMSCE | 0.9639 | MEASURE 2.9 | Robustness | Reliability: root-mean-squared calibration error (L2 analogue of ECE). |
| RPP | 0.5000 | MEASURE 2.7 | Robustness | Safety: fraction of (correct, incorrect) pairs with reversed confidence ordering. |
| Spearman ρ | 0.5000 | MEASURE 2.5 | Efficacy | Discrimination: Spearman rank correlation between confidence and correctness. |
| Kendall τ | 0.0000 | MEASURE 2.5 | Efficacy | Discrimination: Kendall tau-b rank correlation between confidence and correctness. |
| AURC | 0.9500 | MEASURE 2.7 | Robustness | Selective prediction: area under the risk-coverage curve (lower is better). |
| AUUCC | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: area under the uncertainty characteristics curve (higher is better). |
| CRPS | 0.9293 | MEASURE 2.9 | Robustness | Scoring rule: CRPS for Bernoulli confidence forecasts (equivalent to Brier). |
| NLL | 3.5356 | MEASURE 2.9 | Robustness | Scoring rule: binary NLL (log loss) of confidence forecasts. |
| n | 20 | — | — | number of examples scored |
| Dataset hash | `9d9a37ba58087d0f…` | MEASURE 2.8 | Explainability | Transparency: dataset provenance and reproducibility digest. |
| Git SHA | `5346b1b080216418c6e3b3e0e88e5a0142cddeed` | MANAGE 4.1 | Security | Change management: code revision under which results were produced. |
| Timestamp | 2026-04-17T12:00:31.541229+00:00 | — | — | UTC ISO-8601 |




### Run 2 — hf / perplexity / br_regulatory

| metric | value | AI RMF sub-category | trust dimension | notes |
|--------|-------|---------------------|------------------|-------|
| Accuracy | 0.0000 | MEASURE 2.3 | Efficacy | System performance: task accuracy on the evaluation set. |
| ECE | 0.9637 | MEASURE 2.9 | Robustness | Reliability: expected calibration error of confidence scores. |
| Refusal AUROC | 0.5000 | MEASURE 2.7 | Robustness | Safety and robustness: AUROC of confidence as a refusal signal. |
| Miscalibration Area | 0.9994 | MEASURE 2.9 | Robustness | Reliability: area between reliability curve and identity diagonal. |
| Sharpness | 0.0246 | MEASURE 2.9 | Efficacy | Reliability: variance of confidence (decisiveness of the estimator). |
| Missing Ratio | 0.0000 | MEASURE 2.7 | Robustness | Safety: fraction of examples the system refused to answer. |
| PRR | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: prediction-rejection ratio vs oracle (1.0 = oracle, 0.0 = random). |
| Brier | 0.9293 | MEASURE 2.9 | Robustness | Reliability: Brier score (mean squared error of confidence forecasts). |
| RMSCE | 0.9639 | MEASURE 2.9 | Robustness | Reliability: root-mean-squared calibration error (L2 analogue of ECE). |
| RPP | 0.5000 | MEASURE 2.7 | Robustness | Safety: fraction of (correct, incorrect) pairs with reversed confidence ordering. |
| Spearman ρ | 0.5000 | MEASURE 2.5 | Efficacy | Discrimination: Spearman rank correlation between confidence and correctness. |
| Kendall τ | 0.0000 | MEASURE 2.5 | Efficacy | Discrimination: Kendall tau-b rank correlation between confidence and correctness. |
| AURC | 0.9500 | MEASURE 2.7 | Robustness | Selective prediction: area under the risk-coverage curve (lower is better). |
| AUUCC | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: area under the uncertainty characteristics curve (higher is better). |
| CRPS | 0.9293 | MEASURE 2.9 | Robustness | Scoring rule: CRPS for Bernoulli confidence forecasts (equivalent to Brier). |
| NLL | 3.5356 | MEASURE 2.9 | Robustness | Scoring rule: binary NLL (log loss) of confidence forecasts. |
| n | 20 | — | — | number of examples scored |
| Dataset hash | `9d9a37ba58087d0f…` | MEASURE 2.8 | Explainability | Transparency: dataset provenance and reproducibility digest. |
| Git SHA | `6af0911c1e789816ac78c737cd0ad7923b27b4a8` | MANAGE 4.1 | Security | Change management: code revision under which results were produced. |
| Timestamp | 2026-04-17T12:03:50.907098+00:00 | — | — | UTC ISO-8601 |




### Run 3 — hf / token_sar / br_regulatory

| metric | value | AI RMF sub-category | trust dimension | notes |
|--------|-------|---------------------|------------------|-------|
| Accuracy | 0.0000 | MEASURE 2.3 | Efficacy | System performance: task accuracy on the evaluation set. |
| ECE | 0.6688 | MEASURE 2.9 | Robustness | Reliability: expected calibration error of confidence scores. |
| Refusal AUROC | 0.5000 | MEASURE 2.7 | Robustness | Safety and robustness: AUROC of confidence as a refusal signal. |
| Miscalibration Area | 0.6169 | MEASURE 2.9 | Robustness | Reliability: area between reliability curve and identity diagonal. |
| Sharpness | 0.1522 | MEASURE 2.9 | Efficacy | Reliability: variance of confidence (decisiveness of the estimator). |
| Missing Ratio | 0.1500 | MEASURE 2.7 | Robustness | Safety: fraction of examples the system refused to answer. |
| PRR | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: prediction-rejection ratio vs oracle (1.0 = oracle, 0.0 = random). |
| Brier | 0.4705 | MEASURE 2.9 | Robustness | Reliability: Brier score (mean squared error of confidence forecasts). |
| RMSCE | 0.6858 | MEASURE 2.9 | Robustness | Reliability: root-mean-squared calibration error (L2 analogue of ECE). |
| RPP | 0.5000 | MEASURE 2.7 | Robustness | Safety: fraction of (correct, incorrect) pairs with reversed confidence ordering. |
| Spearman ρ | 0.5000 | MEASURE 2.5 | Efficacy | Discrimination: Spearman rank correlation between confidence and correctness. |
| Kendall τ | 0.0000 | MEASURE 2.5 | Efficacy | Discrimination: Kendall tau-b rank correlation between confidence and correctness. |
| AURC | 0.9500 | MEASURE 2.7 | Robustness | Selective prediction: area under the risk-coverage curve (lower is better). |
| AUUCC | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: area under the uncertainty characteristics curve (higher is better). |
| CRPS | 0.4705 | MEASURE 2.9 | Robustness | Scoring rule: CRPS for Bernoulli confidence forecasts (equivalent to Brier). |
| NLL | 1.2024 | MEASURE 2.9 | Robustness | Scoring rule: binary NLL (log loss) of confidence forecasts. |
| n | 20 | — | — | number of examples scored |
| Dataset hash | `9d9a37ba58087d0f…` | MEASURE 2.8 | Explainability | Transparency: dataset provenance and reproducibility digest. |
| Git SHA | `6af0911c1e789816ac78c737cd0ad7923b27b4a8` | MANAGE 4.1 | Security | Change management: code revision under which results were produced. |
| Timestamp | 2026-04-17T12:06:55.384288+00:00 | — | — | UTC ISO-8601 |




### Run 4 — hf / self_consistency / br_regulatory

| metric | value | AI RMF sub-category | trust dimension | notes |
|--------|-------|---------------------|------------------|-------|
| Accuracy | 0.0000 | MEASURE 2.3 | Efficacy | System performance: task accuracy on the evaluation set. |
| ECE | 0.5167 | MEASURE 2.9 | Robustness | Reliability: expected calibration error of confidence scores. |
| Refusal AUROC | 0.5000 | MEASURE 2.7 | Robustness | Safety and robustness: AUROC of confidence as a refusal signal. |
| Miscalibration Area | 0.4070 | MEASURE 2.9 | Robustness | Reliability: area between reliability curve and identity diagonal. |
| Sharpness | 0.2682 | MEASURE 2.9 | Efficacy | Reliability: variance of confidence (decisiveness of the estimator). |
| Missing Ratio | 0.6500 | MEASURE 2.7 | Robustness | Safety: fraction of examples the system refused to answer. |
| PRR | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: prediction-rejection ratio vs oracle (1.0 = oracle, 0.0 = random). |
| Brier | 0.3389 | MEASURE 2.9 | Robustness | Reliability: Brier score (mean squared error of confidence forecasts). |
| RMSCE | 0.5821 | MEASURE 2.9 | Robustness | Reliability: root-mean-squared calibration error (L2 analogue of ECE). |
| RPP | 0.5000 | MEASURE 2.7 | Robustness | Safety: fraction of (correct, incorrect) pairs with reversed confidence ordering. |
| Spearman ρ | 0.6421 | MEASURE 2.5 | Efficacy | Discrimination: Spearman rank correlation between confidence and correctness. |
| Kendall τ | 0.0000 | MEASURE 2.5 | Efficacy | Discrimination: Kendall tau-b rank correlation between confidence and correctness. |
| AURC | 0.9500 | MEASURE 2.7 | Robustness | Selective prediction: area under the risk-coverage curve (lower is better). |
| AUUCC | 0.0000 | MEASURE 2.7 | Robustness | Selective prediction: area under the uncertainty characteristics curve (higher is better). |
| CRPS | 0.3389 | MEASURE 2.9 | Robustness | Scoring rule: CRPS for Bernoulli confidence forecasts (equivalent to Brier). |
| NLL | 5.9546 | MEASURE 2.9 | Robustness | Scoring rule: binary NLL (log loss) of confidence forecasts. |
| n | 20 | — | — | number of examples scored |
| Dataset hash | `9d9a37ba58087d0f…` | MEASURE 2.8 | Explainability | Transparency: dataset provenance and reproducibility digest. |
| Git SHA | `6af0911c1e789816ac78c737cd0ad7923b27b4a8` | MANAGE 4.1 | Security | Change management: code revision under which results were produced. |
| Timestamp | 2026-04-17T12:10:51.162925+00:00 | — | — | UTC ISO-8601 |






## Findings Triage (OCC 2011-12 / SR 11-7)

For each run, every metric is classified as **FINDING** (material
deviation requiring remediation), **OBSERVATION** (non-material note),
or **PASS** (within expected bounds) using configurable thresholds
derived from common banking model-validation heuristics.


### Run 1 — severity: FINDING

| metric | value | severity | threshold band |
|--------|-------|----------|----------------|
| accuracy | 0.0000 | FINDING | obs=0.7, find=0.5 |
| aurc | 0.9500 | FINDING | obs=0.15, find=0.3 |
| auucc | 0.0000 | FINDING | obs=0.5, find=0.3 |
| brier | 0.9293 | FINDING | obs=0.15, find=0.25 |
| crps_from_confidence | 0.9293 | FINDING | obs=0.15, find=0.25 |
| ece | 0.9637 | FINDING | obs=0.05, find=0.1 |
| kendall_tau | 0.0000 | FINDING | obs=0.25, find=0.08 |
| miscalibration_area | 0.9994 | FINDING | obs=0.08, find=0.15 |
| missing_ratio | 0.0000 | PASS | obs=0.2, find=0.4 |
| negative_log_likelihood | 3.5356 | FINDING | obs=0.5, find=1.0 |
| prr | 0.0000 | FINDING | obs=0.5, find=0.2 |
| refusal_auroc | 0.5000 | FINDING | obs=0.7, find=0.55 |
| reversed_pairs_proportion | 0.5000 | FINDING | obs=0.3, find=0.45 |
| rmsce | 0.9639 | FINDING | obs=0.07, find=0.15 |
| sharpness | 0.0246 | OBSERVATION | obs=0.05, find=0.01 |
| spearman | 0.5000 | PASS | obs=0.3, find=0.1 |



### Run 2 — severity: FINDING

| metric | value | severity | threshold band |
|--------|-------|----------|----------------|
| accuracy | 0.0000 | FINDING | obs=0.7, find=0.5 |
| aurc | 0.9500 | FINDING | obs=0.15, find=0.3 |
| auucc | 0.0000 | FINDING | obs=0.5, find=0.3 |
| brier | 0.9293 | FINDING | obs=0.15, find=0.25 |
| crps_from_confidence | 0.9293 | FINDING | obs=0.15, find=0.25 |
| ece | 0.9637 | FINDING | obs=0.05, find=0.1 |
| kendall_tau | 0.0000 | FINDING | obs=0.25, find=0.08 |
| miscalibration_area | 0.9994 | FINDING | obs=0.08, find=0.15 |
| missing_ratio | 0.0000 | PASS | obs=0.2, find=0.4 |
| negative_log_likelihood | 3.5356 | FINDING | obs=0.5, find=1.0 |
| prr | 0.0000 | FINDING | obs=0.5, find=0.2 |
| refusal_auroc | 0.5000 | FINDING | obs=0.7, find=0.55 |
| reversed_pairs_proportion | 0.5000 | FINDING | obs=0.3, find=0.45 |
| rmsce | 0.9639 | FINDING | obs=0.07, find=0.15 |
| sharpness | 0.0246 | OBSERVATION | obs=0.05, find=0.01 |
| spearman | 0.5000 | PASS | obs=0.3, find=0.1 |



### Run 3 — severity: FINDING

| metric | value | severity | threshold band |
|--------|-------|----------|----------------|
| accuracy | 0.0000 | FINDING | obs=0.7, find=0.5 |
| aurc | 0.9500 | FINDING | obs=0.15, find=0.3 |
| auucc | 0.0000 | FINDING | obs=0.5, find=0.3 |
| brier | 0.4705 | FINDING | obs=0.15, find=0.25 |
| crps_from_confidence | 0.4705 | FINDING | obs=0.15, find=0.25 |
| ece | 0.6688 | FINDING | obs=0.05, find=0.1 |
| kendall_tau | 0.0000 | FINDING | obs=0.25, find=0.08 |
| miscalibration_area | 0.6169 | FINDING | obs=0.08, find=0.15 |
| missing_ratio | 0.1500 | PASS | obs=0.2, find=0.4 |
| negative_log_likelihood | 1.2024 | FINDING | obs=0.5, find=1.0 |
| prr | 0.0000 | FINDING | obs=0.5, find=0.2 |
| refusal_auroc | 0.5000 | FINDING | obs=0.7, find=0.55 |
| reversed_pairs_proportion | 0.5000 | FINDING | obs=0.3, find=0.45 |
| rmsce | 0.6858 | FINDING | obs=0.07, find=0.15 |
| sharpness | 0.1522 | PASS | obs=0.05, find=0.01 |
| spearman | 0.5000 | PASS | obs=0.3, find=0.1 |



### Run 4 — severity: FINDING

| metric | value | severity | threshold band |
|--------|-------|----------|----------------|
| accuracy | 0.0000 | FINDING | obs=0.7, find=0.5 |
| aurc | 0.9500 | FINDING | obs=0.15, find=0.3 |
| auucc | 0.0000 | FINDING | obs=0.5, find=0.3 |
| brier | 0.3389 | FINDING | obs=0.15, find=0.25 |
| crps_from_confidence | 0.3389 | FINDING | obs=0.15, find=0.25 |
| ece | 0.5167 | FINDING | obs=0.05, find=0.1 |
| kendall_tau | 0.0000 | FINDING | obs=0.25, find=0.08 |
| miscalibration_area | 0.4070 | FINDING | obs=0.08, find=0.15 |
| missing_ratio | 0.6500 | FINDING | obs=0.2, find=0.4 |
| negative_log_likelihood | 5.9546 | FINDING | obs=0.5, find=1.0 |
| prr | 0.0000 | FINDING | obs=0.5, find=0.2 |
| refusal_auroc | 0.5000 | FINDING | obs=0.7, find=0.55 |
| reversed_pairs_proportion | 0.5000 | FINDING | obs=0.3, find=0.45 |
| rmsce | 0.5821 | FINDING | obs=0.07, find=0.15 |
| sharpness | 0.2682 | PASS | obs=0.05, find=0.01 |
| spearman | 0.6421 | PASS | obs=0.3, find=0.1 |







## Manage

- **Refusal policy.** Answers whose estimator confidence falls below the
  configured refusal threshold are withheld rather than returned. The
  refusal AUROC above measures how well confidence separates correct from
  incorrect answers — values near 0.5 indicate the refusal gate is not
  informative and should not be relied on.
- **Change management.** Any change to backend, estimator, refusal
  threshold, or calibration dataset invalidates the evidence in this
  report and requires a fresh run.
- **Incident handling.** Material miscalibration (e.g. ECE above an
  institutionally set tolerance) should be triaged as a model-risk
  finding, not a latent feature request.


## Data Provenance (JSON-LD)

Every metric value in this report is tagged with a machine-readable
identifier linking it to the underlying benchmark run. The JSON-LD
context below can be embedded in the HTML head or served alongside
the report so GRC tools can programmatically verify provenance.

```json
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "hasPart": [
    {
      "@type": "DataCatalog",
      "about": {
        "dataset": "br_regulatory",
        "dataset_version": "0.1.0",
        "estimator": "token_logprob",
        "git_sha": "5346b1b080216418c6e3b3e0e88e5a0142cddeed",
        "seed": 42
      },
      "creator": "hf",
      "dateCreated": "2026-04-17T12:00:31.541229+00:00",
      "identifier": "9d9a37ba58087d0f",
      "name": "run-1"
    },
    {
      "@type": "DataCatalog",
      "about": {
        "dataset": "br_regulatory",
        "dataset_version": "0.1.0",
        "estimator": "perplexity",
        "git_sha": "6af0911c1e789816ac78c737cd0ad7923b27b4a8",
        "seed": 42
      },
      "creator": "hf",
      "dateCreated": "2026-04-17T12:03:50.907098+00:00",
      "identifier": "9d9a37ba58087d0f",
      "name": "run-2"
    },
    {
      "@type": "DataCatalog",
      "about": {
        "dataset": "br_regulatory",
        "dataset_version": "0.1.0",
        "estimator": "token_sar",
        "git_sha": "6af0911c1e789816ac78c737cd0ad7923b27b4a8",
        "seed": 42
      },
      "creator": "hf",
      "dateCreated": "2026-04-17T12:06:55.384288+00:00",
      "identifier": "9d9a37ba58087d0f",
      "name": "run-3"
    },
    {
      "@type": "DataCatalog",
      "about": {
        "dataset": "br_regulatory",
        "dataset_version": "0.1.0",
        "estimator": "self_consistency",
        "git_sha": "6af0911c1e789816ac78c737cd0ad7923b27b4a8",
        "seed": 42
      },
      "creator": "hf",
      "dateCreated": "2026-04-17T12:10:51.162925+00:00",
      "identifier": "9d9a37ba58087d0f",
      "name": "run-4"
    }
  ],
  "name": "llm-uncertainty-banking evaluation"
}
```

