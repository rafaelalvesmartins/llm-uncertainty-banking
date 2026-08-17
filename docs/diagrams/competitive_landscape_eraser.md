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
