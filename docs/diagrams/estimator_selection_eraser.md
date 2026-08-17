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

// ─── Single pass (cheapest) ───
Single Pass [icon: zap, color: teal, label: "Single Forward Pass"] {
  token logprob [icon: hash, label: "token_logprob\nFastest baseline\nOverconfident on OOD"]
  token sar [icon: trending-up, label: "token_sar (SAR)\nSame cost as logprob\n49% lower ECE"]
  perplexity [icon: activity, label: "perplexity\nSequence-level\nSame ECE as logprob"]
}

Budget? > Single Pass: Minimal (1 pass)

// ─── Multi-sample ───
Multi Sample [icon: copy, color: purple, label: "Multiple Forward Passes"]

Budget? > Multi Sample: Can afford k=3-10 passes

Needs Coverage Guarantee? [shape: diamond, icon: shield, color: orange, label: "Need coverage guarantee?\n(SR 11-7 compliance)"]

Multi Sample > Needs Coverage Guarantee?

// ─── No guarantee needed ───
Diversity Methods [icon: shuffle, color: green, label: "Diversity-based"] {
  self consistency [icon: check-circle, label: "self_consistency (k=5)\nMajority vote\nBest cost/accuracy ratio"]
  semantic entropy [icon: wind, label: "semantic_entropy\nClusters by meaning\nBest on multi-hop QA"]
  eigenscore [icon: grid, label: "EigenScore\nNeeds embeddings\nGood on credit scoring"]
  p true [icon: rotate-cw, label: "p(True)\n2 passes only\nNearly as good as k=10"]
}

Needs Coverage Guarantee? > Diversity Methods: No, best-effort UQ is fine

// ─── Coverage guarantee needed ───
Conformal Methods [icon: maximize, color: red, label: "Conformal Prediction\nDistribution-free coverage"] {
  split conformal [icon: scissors, label: "split_conformal\nZero overhead\nNeeds calibration set"]
  adaptive conformal [icon: sliders, label: "adaptive_conformal\nHandles distribution shift\nOnline updates"]
  mondrian conformal [icon: square, label: "mondrian_conformal\nPer-group thresholds\nFair lending (ECOA)"]
  conformal sampling [icon: droplet, label: "conformal_sampling\nSet-valued predictions\nMultiple valid answers"]
  CCP [icon: crosshair, label: "CCP\nClaim-level conformal\nFact-checking"]
}

Needs Coverage Guarantee? > Conformal Methods: Yes, SR 11-7 requires it

// ─── Special cases ───
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
