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
