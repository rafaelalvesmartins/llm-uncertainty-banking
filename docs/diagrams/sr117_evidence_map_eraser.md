// SR 11-7 Evidence Map — One Benchmark Run
// NOTE: values below are an ILLUSTRATIVE EXAMPLE of the metric->pillar->triage
// structure, NOT the live measured run. Measured values: console /compliance/sr-11-7.
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
