# Benchmark configs

Committable TOML files that pin every argument of `lub benchmark` into one
versioned artifact. Each file here is a complete description of a
reproducible benchmark run — check one in, cite it in a paper, and anyone
can re-run the same experiment with `lub benchmark --config configs/eval/<file>.toml`.

TOML was chosen over YAML because it is stdlib in Python 3.11+ (`tomllib`)
so LUB does not take on a new dependency.

## Supported keys

| Key | Type | Meaning | Default |
|---|---|---|---|
| `model` | str | Backend-specific model id | required |
| `backend` | str | `hf` \| `openai` \| `anthropic` \| `vllm` \| `dummy` | required |
| `estimator` | str | key from `lub.pipeline._ESTIMATORS` | required |
| `dataset` | str | `finqa` \| `convfinqa` \| `tatqa` \| `br_regulatory` | required |
| `limit` | int | max examples to score (null = all) | null |
| `seed` | int | RNG seed for runner | 0 |
| `out` | str | path to write result JSON | `"benchmarks/results"` |

CLI flags override TOML values; TOML sets the defaults.

## Naming convention

`<backend>_<model>_<estimator>_<dataset>.toml`, for example:
- `dummy_dummy-0_token_logprob_br_regulatory.toml`
- `hf_Qwen-2.5-7B_semantic_entropy_finqa.toml`
- `anthropic_claude-sonnet-4-6_verbalized_1s_convfinqa.toml`

Keep a config in git for every release-tagged benchmark result JSON in
`benchmarks/results/`.
