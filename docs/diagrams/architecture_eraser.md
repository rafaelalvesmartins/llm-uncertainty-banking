// LLM Uncertainty Banking Architecture (post-ADR-002, 2026-04-25)
// Paste into eraser.io → New Diagram → Code
// Ruflo is the recommended primary orchestration layer; LUB provides
// calibrated workers that satisfy OrchestratorAgentProtocol.

direction down

// ─── User Entry Points ───
User [icon: user]

CLI [icon: terminal] {
  lub answer [icon: message-circle, label: "lub answer"]
  lub run-swarm [icon: cpu, label: "lub run-swarm"]
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

// ─── Orchestration core (ADR-002) ───
Ruflo Swarm [icon: zap, label: "RUFLO SWARM (npm claude-flow, MIT)"] {
  topology [icon: shuffle, label: "mesh / hierarchical / star"]
  router [icon: git-merge]
  ui [icon: monitor, label: "localhost:3000"]
}

Orchestrator Bridge [icon: link, label: "OrchestratorAgentProtocol"]
Ruflo Swarm --> Orchestrator Bridge: registers calibrated workers
Orchestrator Bridge --> CLI: lub run-swarm --ruflo-handshake
Orchestrator Bridge --> Python API: build_orchestrated_pack()

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
