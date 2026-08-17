# Context Autopilot

`lub.challenge.context_autopilot` is the **runtime arm** of Continuous
Effective Challenge (CEC). Where CEC calibrates an LLM run *after* it
finishes, Context Autopilot watches the **input context window** while
the conversation is still alive. It observes token usage, scores
ejection candidates with a calibrated rule (not FIFO, not LRU), and
flags later turns that re-reference content the autopilot already
ejected.

> Spec: `planning/25_Context_Autopilot_Spec_2026-04-25.md`.
> Petition tie-in: extends the existing CEC fourth claim
> ("calibrated continuous monitoring") from output-only to input+output.

## The four functions

1. **`ContextMonitor.observe(...)`** — passive token counter. Writes
   one row per turn into `context_window_observations`. No prompt is
   intercepted, mutated, or cached.
2. **`score_for_ejection(...)`** — returns an `EjectionScore` whose
   three terms (`alpha * (1 - similarity)`, `beta * age`,
   `-gamma * historical_usefulness`) are each persisted so audit
   reviewers can see *why* a turn was ejected.
3. **`detect_recall_risk(...)`** — when a *later* turn looks
   k-NN-similar to something previously ejected, the autopilot writes
   a `context_recall_flags` row. **It does not silently re-fetch the
   ejected turn** — re-injection is a human/operator decision (see
   §6 of the spec).
4. **MCP surface** — two read-only tools,
   `lub.challenge.context_autopilot.observe` and
   `lub.challenge.context_autopilot.simulate_ejection`. The simulate
   path is the input-side analog of `lub.challenge.replay`.

## Worked example: a 50-turn regulatory review

```python
from lub.challenge.context_autopilot import (
    ContextMonitor, Turn, eject_top_k, detect_recall_risk,
    EjectionLogEntry,
)
from lub.evidence import EvidenceStore
from lub.ledger import Ledger

led = Ledger("review.db")
mon = ContextMonitor(ledger=led)
store = EvidenceStore()

session_id = "ofac-2026-04-25"
model_max = 32_000
turns: list[Turn] = []

# 50-turn regulator review against a 32k context model.
for turn_id, prompt in enumerate(read_review_corpus()):
    input_tokens = approximate_tokens(prompt)
    mon.observe(session_id, turn_id, input_tokens, model_max)
    turns.append(
        Turn(turn_id=turn_id, text=prompt, age_in_turns=turn_id)
    )

    # When headroom drops below 15%, score and eject.
    used = sum(t.input_tokens for t in observations(led, session_id))
    if 1 - used / model_max < 0.15:
        ejected = eject_top_k(
            turns,
            current_query=prompt,
            evidence_store=store,
            ledger=led,
            k=3,
            threshold=0.4,
            session_id=session_id,
        )
        for e in ejected:
            print(f"ejected turn {e.turn_id} score={e.score.score:.3f}")
        # Drop the ejected turns from the live window.
        ejected_ids = {e.turn_id for e in ejected}
        turns = [t for t in turns if t.turn_id not in ejected_ids]

# Later in the session: a follow-up question that re-references KYC
# rules the autopilot ejected at turn 18.
log = [
    EjectionLogEntry(
        eject_id=row.id,
        session_id=session_id,
        ejected_turn_id=row.ejected_turn_id,
        text=...,  # caller-supplied; ledger does not store full prompt.
    )
    for row in fetch_ejections(led, session_id)
]
flag = detect_recall_risk(
    "could you re-check the KYC retail-onboarding line items?",
    log,
    store,
    ledger=led,
    similarity_threshold=0.3,
)
if flag is not None:
    notify_operator(flag)  # human decides whether to re-inject.
```

After the run, `lub.challenge.context_autopilot.observe` returns a
`ContextWindowReport` summarising peak usage, minimum headroom, and
final cumulative tokens. `simulate_ejection` answers the
counterfactual: *"what would have been ejected at threshold 0.30?"*.

Hard constraints: zero new required dependencies (`tiktoken` stays
optional via `lub.wrappers`); ejection is always logged before it
happens; recall flags are never auto-resolved.
