# Diagrams

All architecture / flow diagrams for `llm-uncertainty-banking` in a
single file. Each block below is ready to paste into
[eraser.io](https://eraser.io) → New Diagram → Code, which renders them
as labelled, icon-rich system diagrams.

Seven diagrams, in logical order:

1. [System architecture](#1-system-architecture) — the five-layer library
2. [Data flow](#2-data-flow) — one prompt end-to-end
3. [Benchmark pipeline](#3-benchmark-pipeline) — dataset to regulator
4. [SR 11-7 evidence map](#4-sr-11-7-evidence-map) — metrics → pillars
5. [REASK policy flow](#5-reask-policy-flow) — guard retry logic
6. [Estimator selection](#6-estimator-selection) — decision tree
7. [Competitive landscape](#7-competitive-landscape) — lub vs market

---

## 1. System architecture

Full five-layer library with governance as an orthogonal concern.

```eraser
// LLM Uncertainty Banking Architecture
direction down

// ─── User Entry Points ───
User [icon: user]

CLI [icon: terminal] {
  lub answer [icon: message-circle, label: "lub answer"]
  lub benchmark [icon: bar-chart, label: "lub benchmark"]
  lub report [icon: file-text, label: "lub report"]
  lub scan [icon: search, label: "lub scan"]
  lub drift [icon: trending-up, label: "lub drift"]
  lub list [icon: list, label: "lub list"]
  lub repro [icon: repeat, label: "lub repro"]
  lub version [icon: tag, label: "lub version"]
}

Python API [icon: code]

User --> CLI: shell
User --> Python API: import lub

// ─── Pipeline Facade ───
UncertaintyPipeline [icon: layers] {
  from pretrained [icon: download, label: "from_pretrained()"]
  answer method [icon: message-circle, label: "answer()"]
  batch answer [icon: copy, label: "batch_answer()"]
  to dict from dict [icon: file-text, label: "to_dict() / from_dict()"]
}

CLI > UncertaintyPipeline
Python API > UncertaintyPipeline

// ─── Governance (Orthogonal) ───
Governance [icon: shield, color: orange] {
  UncertaintyGuard [icon: shield-off] {
    guard call [icon: play, label: "__call__()"]
    handle reask [icon: refresh-cw, label: "_handle_reask()"]
    gated tool call [icon: tool, label: "gated_tool_call()"]
    guard batch [icon: copy, label: "batch()"]
  }
  PolicyDecision [icon: git-branch] {
    PASSTHROUGH [icon: check]
    ABSTAIN [icon: minus-circle]
    FLAG [icon: flag]
    RAISE [icon: alert-triangle]
    REASK [icon: refresh-cw]
  }
  RailSet [icon: sliders] {
    Input Rails [icon: arrow-right]
    Output Rails [icon: arrow-left]
  }
}

UncertaintyPipeline > Governance: wraps

// ─── L1 Wrappers ───
L1 Wrappers [icon: box, color: blue] {
  BackendProto [icon: cpu] {
    generate method [icon: edit, label: "generate()"]
    logprobs method [icon: percent, label: "logprobs()"]
    embed method [icon: hash, label: "embed()"]
  }
  DummyBackend [icon: box]
  HFBackend [icon: huggingface, label: "HFBackend"]
  OpenAIBackend [icon: openai]
  AnthropicBackend [icon: anthropic]
  VLLMBackend [icon: server, label: "VLLMBackend"]
}

UncertaintyPipeline > L1 Wrappers: backend.generate()

// ─── L2 Uncertainty Estimators ───
L2 Estimators [icon: bar-chart-2, color: purple] {
  Information based [icon: info, label: "Information-based"] {
    token logprob [icon: hash, label: "token_logprob"]
    perplexity [icon: activity]
    SAR [icon: trending-up]
    sentence SAR [icon: align-left, label: "sentence_SAR"]
  }
  Diversity based [icon: shuffle, label: "Diversity-based"] {
    self consistency [icon: check-circle, label: "self_consistency"]
    semantic entropy [icon: wind, label: "semantic_entropy"]
    EigenScore [icon: grid]
    ensemble [icon: users]
    self certainty [icon: target, label: "self_certainty"]
  }
  Conformal [icon: maximize] {
    split conformal [icon: scissors, label: "split_conformal"]
    adaptive conformal [icon: sliders, label: "adaptive_conformal"]
    mondrian conformal [icon: square, label: "mondrian_conformal"]
    conformal sampling [icon: droplet, label: "conformal_sampling"]
    CCP [icon: crosshair]
  }
  Reflexive [icon: rotate-cw] {
    p True [icon: check, label: "p_True"]
  }
  Verbalized [icon: message-square] {
    one shot [icon: zap, label: "one_shot"]
    two shot [icon: zap, label: "two_shot"]
  }
  Density based [icon: layers, label: "Density-based"] {
    Mahalanobis [icon: compass]
    graph Laplacian [icon: share-2, label: "graph_Laplacian"]
    epistemic aleatoric [icon: divide, label: "epistemic_aleatoric"]
    LM Polygraph [icon: activity, label: "LM_Polygraph"]
  }
  Other Estimators [icon: more-horizontal, label: "Other"] {
    claim level [icon: file-text, label: "claim_level"]
    MC dropout [icon: droplet, label: "MC_dropout"]
  }
}

UncertaintyPipeline > L2 Estimators: estimator.score()
L2 Estimators > L1 Wrappers: backend via BackendProto

// ─── L3 Calibration ───
L3 Calibration [icon: check-circle, color: green] {
  Fourteen Metrics [icon: hash, label: "14 Metrics"] {
    ECE [icon: percent]
    Brier [icon: target]
    RMSCE [icon: trending-down]
    ENCE [icon: bar-chart]
    refusal AUROC [icon: x-circle, label: "refusal_AUROC"]
    PRR [icon: percent]
    sharpness [icon: zap]
    miscalibration area [icon: square, label: "miscalibration_area"]
    missing ratio [icon: minus, label: "missing_ratio"]
    spearman [icon: trending-up]
    kendall tau [icon: trending-up, label: "kendall_tau"]
    adversarial group cal [icon: shield, label: "adversarial_group_cal"]
    RPP [icon: percent]
    MCC [icon: check-square]
  }
  Five Scoring Rules [icon: award, label: "5 Scoring Rules"] {
    CRPS gaussian [icon: activity, label: "CRPS_gaussian"]
    CRPS confidence [icon: activity, label: "CRPS_confidence"]
    interval score [icon: minus, label: "interval_score"]
    NLL [icon: trending-down]
    pinball loss [icon: target, label: "pinball_loss"]
  }
  Drift Detection [icon: trending-up] {
    PSI [icon: bar-chart]
    CBPE [icon: activity]
    DriftThresholds [icon: sliders]
  }
  Plots [icon: image] {
    reliability diagram [icon: pie-chart, label: "reliability_diagram"]
    confidence histogram [icon: bar-chart-2, label: "confidence_histogram"]
    risk coverage curve [icon: trending-up, label: "risk_coverage_curve"]
  }
  Normalizers [icon: sliders] {
    MinMax [icon: minimize-2]
    BinnedPCC [icon: grid]
    Isotonic [icon: trending-up]
    Quantile [icon: percent]
  }
}

// ─── L4 Benchmarks ───
L4 Benchmarks [icon: database, color: teal] {
  Financial QA [icon: dollar-sign] {
    FinQA [icon: file-text]
    ConvFinQA [icon: message-circle]
    TAT QA [icon: table, label: "TAT_QA"]
  }
  Credit Scoring [icon: credit-card] {
    German Credit [icon: flag, label: "German_Credit"]
    Australian Credit [icon: flag, label: "Australian_Credit"]
  }
  Sentiment [icon: smile] {
    FPB [icon: message-square]
    FiQA SA [icon: trending-up, label: "FiQA_SA"]
  }
  Regulatory [icon: landmark] {
    BR Regulatory [icon: star, label: "BR_Regulatory"]
  }
  BenchmarkRunner [icon: play-circle] {
    runner run [icon: play, label: "run()"]
    exact match [icon: check, label: "exact_match()"]
    choice match [icon: check-circle, label: "choice_match()"]
  }
}

L4 Benchmarks > UncertaintyPipeline: pipeline.answer(question)
L4 Benchmarks > L3 Calibration: compute_all(confs, correct)

// ─── L5 Reports ───
L5 Reports [icon: file-text, color: red] {
  AIRMFReporter [icon: file] {
    render md html [icon: code, label: "render(md / html)"]
    Jinja2 template [icon: layout]
  }
  OSCAL Output [icon: shield] {
    Component Definition [icon: box]
    Assessment Results [icon: clipboard]
    OscalBatchReporter [icon: copy]
  }
  FindingClassifier [icon: filter] {
    OCC 2011 12 triage [icon: git-branch, label: "OCC 2011-12 triage"]
    PASS OBSERVATION FINDING [icon: list, label: "PASS / OBSERVATION / FINDING"]
  }
  Multi Regime Crosswalk [icon: map, label: "Multi-Regime Crosswalk"] {
    NIST AI RMF 1 0 [icon: shield, label: "NIST AI RMF 1.0"]
    NIST AI 600 1 [icon: shield, label: "NIST AI 600-1"]
    SR 11 7 [icon: landmark, label: "SR 11-7"]
    EU AI Act [icon: flag]
    ISO 42001 [icon: award]
  }
  Giskard Scanner [icon: search] {
    vulnerability checks [icon: alert-triangle]
    GiskardBatchReporter [icon: copy]
  }
}

L4 Benchmarks > L5 Reports: BenchmarkResult
L3 Calibration > L5 Reports: metrics dict
Governance > L5 Reports: PolicyOutcome to MANAGE section

// ─── SR 11-7 Mapping ───
SR 11 7 Mapping [icon: landmark, color: darkred, label: "SR 11-7 Mapping"] {
  Pillar 2 Model Validation [icon: check-square] {
    VA Conceptual Soundness [icon: book, label: "V.A Conceptual Soundness → ECE, Brier, RMSCE"]
    VB Outcomes Analysis [icon: bar-chart, label: "V.B Outcomes Analysis → accuracy, AUROC, PRR"]
    VC Benchmarking [icon: git-compare, label: "V.C Benchmarking → spearman, kendall_tau"]
    VD Effective Challenge [icon: shield, label: "V.D Effective Challenge → adversarial_group_cal"]
  }
  Pillar 3 Governance [icon: settings] {
    VIA Documentation [icon: file, label: "VI.A Documentation → dataset_hash"]
    VIB Ongoing Monitoring [icon: activity, label: "VI.B Ongoing Monitoring → missing_ratio, PSI"]
    VIC Change Management [icon: git-commit, label: "VI.C Change Management → git_sha, packages"]
  }
}

L5 Reports > SR 11 7 Mapping: maps metrics to pillars

// ─── Output Artifacts ───
Outputs [icon: download, color: darkgreen] {
  BenchmarkResult JSON [icon: file-text, label: "BenchmarkResult JSON"]
  AI RMF Report HTML MD [icon: file, label: "AI RMF Report (HTML/MD)"]
  OSCAL Component Definition JSON [icon: shield, label: "OSCAL Component Definition (JSON)"]
  OSCAL Assessment Results JSON [icon: clipboard, label: "OSCAL Assessment Results (JSON)"]
  Reliability Diagrams PNG [icon: image, label: "Reliability Diagrams (PNG)"]
  Giskard Scan Report [icon: file-text]
  OTEL Span Attributes [icon: activity]
}

L5 Reports > Outputs

// ─── Integrations ───
Integrations [icon: plug, color: gray] {
  MLflow [icon: database] {
    log benchmark result [icon: save, label: "log_benchmark_result()"]
    log guard result [icon: save, label: "log_guard_result()"]
  }
  LangChain [icon: link] {
    LUBCallbackHandler [icon: phone-call]
    on llm start [icon: play, label: "on_llm_start()"]
  }
}

Outputs > Integrations
Governance > Integrations: GuardResult
```

---

## 2. Data flow

One question, end-to-end: rails, generation, estimator, guard.

```eraser
// LUB Data Flow — Single Question
direction right

Question [icon: message-circle, color: blue, label: "What is the Basel III minimum CET1 ratio?"]

Pipeline [icon: layers] {
  RailSet Input [icon: arrow-right, label: "Input Rails (PII check, length)"]
  Backend Call [icon: cpu, label: "backend.generate()"]
  Estimator Score [icon: bar-chart-2, label: "estimator.score()"]
  RailSet Output [icon: arrow-left, label: "Output Rails (confidence check)"]
}

Question > Pipeline

LLM [icon: cloud, color: purple] {
  Generation 1 [icon: file-text, label: "4.5% (logprob: -0.12)"]
  Generation 2 [icon: file-text, label: "4.5% (logprob: -0.15)"]
  Generation 3 [icon: file-text, label: "7% (logprob: -0.89)"]
}

Pipeline > LLM: n_samples=3, temperature=0.7
LLM < Pipeline: 3 Generations

UncertaintyResult [icon: check-circle, color: green] {
  answer [icon: message-circle, label: "answer: 4.5%"]
  confidence [icon: target, label: "confidence: 0.667"]
  should refuse [icon: x-circle, label: "should_refuse: False"]
  raw scores [icon: hash, label: "raw_scores: {agreement: 0.667}"]
}

Pipeline > UncertaintyResult: self_consistency vote

Guard [icon: shield, color: orange] {
  threshold check [icon: sliders, label: "0.667 >= 0.5?"]
  decision [icon: git-branch, label: "PASSTHROUGH"]
}

UncertaintyResult > Guard

GuardResult [icon: shield-check, color: green] {
  output [icon: message-circle, label: "output: 4.5%"]
  policy outcome [icon: clipboard, label: "PolicyOutcome: PASSTHROUGH"]
  rmf subcategory [icon: landmark, label: "GOVERN 3.2"]
}

Guard > GuardResult: passed = True
```

---

## 3. Benchmark pipeline

From dataset load to regulator-facing artefacts.

```eraser
// Benchmark Pipeline — Dataset to Regulatory Evidence
direction down

Dataset [icon: database, color: teal] {
  BR Regulatory [icon: star, label: "BR-Regulatory (20 QA pairs)"]
  FinQA [icon: file-text]
  ConvFinQA [icon: message-circle]
  Credit Scoring [icon: credit-card]
}

BenchmarkRunner [icon: play-circle, color: blue] {
  Iterate Examples [icon: repeat]
  Call Pipeline [icon: layers, label: "pipeline.answer(question)"]
  Score Correctness [icon: check, label: "exact_match(pred, gold)"]
  Collect Confidences [icon: list]
}

Dataset > BenchmarkRunner: load() yields Examples

Calibration [icon: check-circle, color: green] {
  compute all [icon: hash, label: "compute_all(confs, correct)"]
  ECE [icon: percent]
  Brier [icon: target]
  AUROC [icon: trending-up]
  PRR [icon: bar-chart]
  14 more metrics [icon: more-horizontal, label: "+ 10 more metrics"]
}

BenchmarkRunner > Calibration: numpy arrays

BenchmarkResult [icon: file-text, color: blue] {
  All Metrics [icon: hash]
  Provenance [icon: git-commit, label: "git_sha + package_versions"]
  Dataset Hash [icon: hash]
  Timestamp [icon: clock]
}

Calibration > BenchmarkResult: metrics dict

FindingClassifier [icon: filter, color: orange] {
  Threshold Check [icon: sliders, label: "each metric vs OCC 2011-12 threshold"]
  PASS [icon: check-circle, color: green]
  OBSERVATION [icon: eye, color: orange]
  FINDING [icon: alert-triangle, color: red]
}

BenchmarkResult > FindingClassifier

SR 11-7 Mapping [icon: landmark, color: purple] {
  Pillar 2 [icon: check-square, label: "V.A-D Model Validation"]
  Pillar 3 [icon: settings, label: "VI.A-C Governance"]
}

BenchmarkResult > SR 11-7 Mapping

Reports [icon: file-text, color: red] {
  AIRMF HTML [icon: file, label: "AI RMF Report (HTML)"]
  OSCAL CD [icon: shield, label: "OSCAL Component Definition"]
  OSCAL AR [icon: clipboard, label: "OSCAL Assessment Results"]
  Giskard Scan [icon: search, label: "Vulnerability Scan"]
}

FindingClassifier > Reports
SR 11-7 Mapping > Reports

Auditor [icon: user, color: darkgreen, label: "MRM Auditor / OCC Examiner"]

Reports > Auditor: machine-readable evidence
```

---

## 4. SR 11-7 evidence map

Maps the metrics from one `BenchmarkResult` to the SR 11-7 pillars they satisfy.
**The numbers below are an illustrative example** showing the metric → pillar →
triage structure — they are **not** the live measured run. For measured values
(and the real triage verdict), see the console's `/compliance/sr-11-7` panel,
which reads the latest real benchmark result.

```eraser
// SR 11-7 Evidence Map — One Benchmark Run
direction down

Benchmark Run [icon: play-circle, color: blue]

BenchmarkResult [icon: file-text] {
  accuracy [icon: check, label: "accuracy: 0.80"]
  ece [icon: percent, label: "ece: 0.08"]
  refusal auroc [icon: target, label: "refusal_auroc: 0.81"]
  brier [icon: target, label: "brier: 0.12"]
  prr [icon: trending-up, label: "prr: 0.65"]
  spearman [icon: trending-up, label: "spearman: 0.72"]
  missing ratio [icon: minus, label: "missing_ratio: 0.10"]
  dataset hash [icon: hash, label: "dataset_hash: 9d9a37ba..."]
  git sha [icon: git-commit, label: "git_sha: eb5f850"]
}

Benchmark Run > BenchmarkResult

Pillar 2 [icon: check-square, color: purple, label: "Pillar 2: Model Validation"] {
  VA [icon: book, label: "V.A Conceptual Soundness"] {
    ece evidence [icon: arrow-right, label: "ECE = 0.08 → PASS (< 0.10)"]
    brier evidence [icon: arrow-right, label: "Brier = 0.12 → PASS (< 0.15)"]
  }
  VB [icon: bar-chart, label: "V.B Outcomes Analysis"] {
    accuracy evidence [icon: arrow-right, label: "Accuracy = 0.80 → PASS (>= 0.70)"]
    auroc evidence [icon: arrow-right, label: "AUROC = 0.81 → PASS (>= 0.70)"]
    prr evidence [icon: arrow-right, label: "PRR = 0.65 → PASS (>= 0.50)"]
  }
  VC [icon: git-compare, label: "V.C Benchmarking"] {
    spearman evidence [icon: arrow-right, label: "Spearman = 0.72 → PASS (>= 0.30)"]
  }
}

BenchmarkResult > Pillar 2

Pillar 3 [icon: settings, color: gray, label: "Pillar 3: Governance, Policies & Controls"] {
  VIA [icon: file, label: "VI.A Documentation"] {
    hash evidence [icon: arrow-right, label: "dataset_hash: 9d9a37ba → reproducible"]
  }
  VIB [icon: activity, label: "VI.B Ongoing Monitoring"] {
    refusal evidence [icon: arrow-right, label: "missing_ratio = 0.10 → PASS (< 0.20)"]
  }
  VIC [icon: git-commit, label: "VI.C Change Management"] {
    git evidence [icon: arrow-right, label: "git_sha: eb5f850 → version-controlled"]
  }
}

BenchmarkResult > Pillar 3

Finding Report [icon: clipboard, color: green, label: "OCC 2011-12 Triage"] {
  findings count [icon: alert-triangle, label: "FINDINGs: 0"]
  observations count [icon: eye, label: "OBSERVATIONs: 0"]
  passes count [icon: check-circle, label: "PASSes: 9"]
  verdict [icon: award, label: "Verdict: PASS — no material deviations"]
}

Pillar 2 > Finding Report
Pillar 3 > Finding Report

Artifacts [icon: download, color: green] {
  OSCAL JSON [icon: shield, label: "OSCAL Assessment Results (JSON)"]
  HTML Report [icon: file, label: "AI RMF Report (HTML)"]
  Reliability PNG [icon: image, label: "Reliability Diagram (PNG)"]
}

Finding Report > Artifacts: lub report --format html
```

---

## 5. REASK policy flow

What `_handle_reask` does when the first-pass confidence is below
threshold.

```eraser
// REASK Policy Flow
direction down

User Prompt [shape: oval, icon: message-circle, color: lightblue]

First Pass [color: blue, icon: cpu] {
  Generate Answer [icon: play]
  Calculate Confidence [icon: target]
}

User Prompt > First Pass

Below Threshold? [shape: diamond, icon: sliders, color: orange]

First Pass > Below Threshold?: confidence = 0.30

Reask Process [color: purple, icon: refresh-cw] {
  Add Corrective Prefix [icon: edit]
  Retry Generation [icon: play]
  Recalculate Confidence [icon: target]
}

Below Threshold? > Reask Process: Yes

Retry Passed? [shape: diamond, icon: sliders, color: orange]

Reask Process > Retry Passed?: confidence = 0.85

Success Path [color: green, icon: check-circle] {
  Policy Decision Reask [icon: git-branch]
  Return Retry Answer [icon: message-circle]
  Log Metadata [icon: hash]
}

Retry Passed? > Success Path: Yes

Fallthrough Path [color: red, icon: x-circle] {
  Policy Decision Abstain [icon: x-circle]
  Return Abstain Marker [icon: message-circle]
  Log Failure Metadata [icon: hash]
}

Retry Passed? > Fallthrough Path: No

Below Threshold? > Success Path: No; confidence already sufficient
```

---

## 6. Estimator selection

Decision tree from "which backend do I have" to "which estimator should
I use".

```eraser
// Estimator Selection — Which UQ Method for Your Use Case?
direction down

Start [shape: oval, icon: help-circle, color: blue, label: "Which estimator should I use?"]

Has Logprobs? [shape: diamond, icon: key, color: orange, label: "Does your backend expose logprobs?"]

Start > Has Logprobs?

// ─── No logprobs (blackbox API) ───
Blackbox Path [icon: cloud, color: gray, label: "Blackbox API (OpenAI, Anthropic)"] {
  Latency Sensitive? [shape: diamond, icon: clock, label: "Latency-sensitive?"]
}

Has Logprobs? > Blackbox Path: No (text-only API)

Verbalized [icon: message-square, color: green, label: "verbalized_1s / verbalized_2s\n1 extra forward pass\nCheapest blackbox option"]

Self Consistency BB [icon: check-circle, color: green, label: "self_consistency (k=5)\n5 forward passes\nStrong baseline"]

Blackbox Path > Verbalized: Yes, minimize calls
Blackbox Path > Self Consistency BB: No, accuracy matters

// ─── Has logprobs ───
Whitebox Path [icon: cpu, color: blue, label: "Has logprobs (HF, vLLM)"]

Has Logprobs? > Whitebox Path: Yes

Budget? [shape: diamond, icon: dollar-sign, color: orange, label: "Inference budget?"]

Whitebox Path > Budget?

Single Pass [icon: zap, color: teal, label: "Single Forward Pass"] {
  token logprob [icon: hash, label: "token_logprob\nFastest baseline\nOverconfident on OOD"]
  token sar [icon: trending-up, label: "token_sar (SAR)\nSame cost as logprob\n49% lower ECE"]
  perplexity [icon: activity, label: "perplexity\nSequence-level\nSame ECE as logprob"]
}

Budget? > Single Pass: Minimal (1 pass)

Multi Sample [icon: copy, color: purple, label: "Multiple Forward Passes"]

Budget? > Multi Sample: Can afford k=3-10 passes

Needs Coverage Guarantee? [shape: diamond, icon: shield, color: orange, label: "Need coverage guarantee?\n(SR 11-7 compliance)"]

Multi Sample > Needs Coverage Guarantee?

Diversity Methods [icon: shuffle, color: green, label: "Diversity-based"] {
  self consistency [icon: check-circle, label: "self_consistency (k=5)\nMajority vote\nBest cost/accuracy ratio"]
  semantic entropy [icon: wind, label: "semantic_entropy\nClusters by meaning\nBest on multi-hop QA"]
  eigenscore [icon: grid, label: "EigenScore\nNeeds embeddings\nGood on credit scoring"]
  p true [icon: rotate-cw, label: "p(True)\n2 passes only\nNearly as good as k=10"]
}

Needs Coverage Guarantee? > Diversity Methods: No, best-effort UQ is fine

Conformal Methods [icon: maximize, color: red, label: "Conformal Prediction\nDistribution-free coverage"] {
  split conformal [icon: scissors, label: "split_conformal\nZero overhead\nNeeds calibration set"]
  adaptive conformal [icon: sliders, label: "adaptive_conformal\nHandles distribution shift\nOnline updates"]
  mondrian conformal [icon: square, label: "mondrian_conformal\nPer-group thresholds\nFair lending (ECOA)"]
  conformal sampling [icon: droplet, label: "conformal_sampling\nSet-valued predictions\nMultiple valid answers"]
  CCP [icon: crosshair, label: "CCP\nClaim-level conformal\nFact-checking"]
}

Needs Coverage Guarantee? > Conformal Methods: Yes, SR 11-7 requires it

Special Cases [icon: more-horizontal, color: gray, label: "Special Cases"]

Has Logprobs? > Special Cases: Special requirements

HF Only [icon: server, label: "Host model locally? (HF only)"] {
  mc dropout [icon: droplet, label: "MC Dropout\nEpistemic/aleatoric split\nNeeds dropout layers"]
  lm polygraph [icon: activity, label: "LM-Polygraph\nMultiple UE signals\nResearch-grade"]
}

OOD Detection [icon: alert-triangle, label: "Out-of-distribution detection?"] {
  mahalanobis [icon: compass, label: "Mahalanobis\nNeeds reference embeddings\nNovel instrument detection"]
  graph laplacian [icon: share-2, label: "Graph Laplacian\nNeeds embeddings\nCluster-based OOD"]
  epistemic aleatoric [icon: divide, label: "Epistemic/Aleatoric\nDecomposes uncertainty source"]
}

Fact Checking [icon: file-text, label: "Claim-level fact checking?"] {
  claim level [icon: check-square, label: "claim_level\nPer-claim scores\nLong-form answers"]
}

Special Cases > HF Only
Special Cases > OOD Detection
Special Cases > Fact Checking
```

---

## 7. Competitive landscape

Three adjacent markets — LLM UQ, regulatory compliance, OSCAL —
converging on `lub`.

```eraser
// Competitive Landscape — lub vs Market
direction right

LLM UQ [icon: bar-chart-2, color: purple, label: "LLM Uncertainty Quantification"] {
  UQLM [icon: github, label: "UQLM (CVS Health)"]
  LM Polygraph [icon: github, label: "LM-Polygraph"]
  TruthTorchLM [icon: github]
  polygraphLLM [icon: github, label: "polygraphLLM (Cisco)"]
}

Compliance [icon: landmark, color: red, label: "Regulatory Compliance"] {
  ValidMind [icon: lock, label: "ValidMind (closed)"]
  Credo AI [icon: lock, label: "Credo AI (closed)"]
  Monitaur [icon: lock, label: "Monitaur (closed)"]
}

OSCAL [icon: shield, color: teal, label: "OSCAL Machine-Readable Output"] {
  Venturalítica [icon: github, label: "Venturalítica SDK (tabular only)"]
}

lub [icon: star, color: green, label: "llm-uncertainty-banking"] {
  22 Estimators [icon: bar-chart-2]
  14 Calibration Metrics [icon: check-circle]
  5 Conformal Variants [icon: maximize]
  OSCAL Output [icon: shield]
  SR 11-7 Mapping [icon: landmark]
  Governance Layer [icon: shield-off]
  Apache 2.0 [icon: unlock]
}

LLM UQ > lub: has UQ but no compliance
Compliance > lub: has compliance but closed source
OSCAL > lub: has OSCAL but not for LLMs

No One Else [shape: diamond, icon: alert-circle, color: orange, label: "No tool combines all three"]

LLM UQ > No One Else
Compliance > No One Else
OSCAL > No One Else
No One Else > lub: lub fills the gap
```
