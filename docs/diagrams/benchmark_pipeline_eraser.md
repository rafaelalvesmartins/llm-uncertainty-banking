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
