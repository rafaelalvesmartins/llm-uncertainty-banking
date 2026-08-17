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
