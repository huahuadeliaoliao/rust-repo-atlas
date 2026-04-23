# Benchmark Suite Report

- Tasks dir: `/Users/florianliao/Documents/Playground/rust-repo-atlas/benchmarks/tasks`
- Answers root: `/Users/florianliao/Documents/Playground/rust-repo-atlas/benchmarks/answers`
- Sets scored: `2`
- Baseline label: `reference_baseline`

## Set Summary

| Label | Coverage | Avg Score | Avg Required | Avg Localization | Avg Relation | Avg Refresh |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `reference_atlas` | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| `reference_baseline` | 4 | 0.742 | 0.646 | 0.562 | 0.500 | 1.000 |

## Deltas Vs Baseline

| Candidate | Avg Delta | Improved | Regressed | Unchanged |
| --- | ---: | ---: | ---: | ---: |
| `reference_atlas` | 0.258 | 4 | 0 | 0 |

## Task Deltas: `reference_atlas` vs `reference_baseline`

| Task | Repo | Baseline | Candidate | Delta |
| --- | --- | ---: | ---: | ---: |
| `burn.plan.training-change-surface.001` | `burn` | 0.667 | 1.000 | 0.333 |
| `burn.trace.backend.decorator-path.001` | `burn` | 0.733 | 1.000 | 0.267 |
| `codex.localize.rust-focus-root.001` | `codex` | 0.733 | 1.000 | 0.267 |
| `codex.trace.cli-core-path.001` | `codex` | 0.833 | 1.000 | 0.167 |
