# Getting Started

## Install

Not yet published to PyPI — install from source using
[uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/rafaelmartinsalves/llm-uncertainty-banking
cd llm-uncertainty-banking
uv venv
uv pip install -e ".[dev]"
```

Once released, the published package (future command):

```bash
pip install llm-uncertainty-banking
# with optional SDK backends
pip install "llm-uncertainty-banking[openai,anthropic]"
```

> **Heads-up on install size.** Today `torch` + `transformers` install as core
> dependencies (~2 GB), even though the offline path (`backend="dummy"`) and the
> numpy-based calibration core need neither. Moving the HuggingFace stack behind
> a `[hf]` extra so the air-gapped core is small is queued (planning/36 P38).

## Your first call

The `DummyBackend` makes no network calls and returns deterministic
output, so the snippet below runs anywhere — no GPUs, no API keys.

```python
from lub.pipeline import UncertaintyPipeline

pipe = UncertaintyPipeline.from_pretrained(
    model="dummy-model",
    backend="dummy",
    estimator="self_consistency",
    n_samples=8,
    temperature=0.7,
)

result = pipe.answer("What is the Basel III minimum CET1 ratio?")
print("answer    :", result.answer)
print("confidence:", round(result.confidence, 3))
print("refuse?   :", result.should_refuse)
print("raw       :", result.raw_scores)
```

## Your first benchmark

```python
from lub.benchmarks import BenchmarkRunner, BrazilianRegulatoryDataset

dataset = BrazilianRegulatoryDataset()
runner = BenchmarkRunner(pipeline=pipe, dataset=dataset)
result = runner.run(limit=20, seed=0)
print(result.accuracy, result.ece, result.refusal_auroc)
```

## CLI tour

```bash
lub version
lub answer --model dummy-model --backend dummy \
    --estimator self_consistency "What is the CET1 minimum?"
lub benchmark --model dummy-model --backend dummy \
    --estimator token_logprob --dataset br_regulatory \
    --limit 20 --out results.json
lub report --input results.json --format html --out report.html
```

`--quiet` and `--verbose` flags adjust log verbosity. Exit codes are
`0` on success, `1` on user error, `2` on internal error.

## Handling errors

`lub` ships a small custom exception hierarchy under `lub.exceptions`,
all rooted at `LubError`, so integrations can catch domain errors
without resorting to bare `Exception`:

```python
from lub import (
    UncertaintyPipeline,
    LubError, BackendError, CapabilityError, EstimatorError,
)

pipe = UncertaintyPipeline.from_pretrained(
    model="dummy-model",
    backend="anthropic",          # GENERATE only — no logprobs
    estimator="conformal",        # requires LOGPROBS
)
try:
    result = pipe.answer("What is the CET1 minimum?")
except CapabilityError as exc:
    # Estimator requires a backend capability that this backend
    # does not expose. Detected at construction / first call,
    # before any network round-trip is wasted.
    print(f"unsupported combo: {exc.message}")
    print(f"audit context    : {exc.context}")
except BackendError as exc:
    # Network / rate-limit / malformed-response from the LLM provider.
    # CapabilityError is a subclass of BackendError, so the order of
    # except clauses matters — put the more specific one first.
    print(f"backend failed: {exc.message}")
except LubError as exc:
    # Catch-all for anything else lub can raise (estimator, calibration,
    # benchmark, orchestration, confidence-parse). Useful at the top of
    # an integration loop so unexpected lub errors are isolated from
    # bugs in your own code.
    print(f"lub error: {exc!r}")
```

Every `LubError` carries an optional `context` dict that the
structured logger and the OSCAL audit trail can serialize, so a model
risk reviewer can reconstruct exactly what failed even if the
traceback is later stripped.

For the full hierarchy and when to use which subclass, see the
`lub.exceptions` module.
