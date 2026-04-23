# Benchmarks

This folder contains the first runnable benchmark scaffold for `rust-repo-atlas`.

## What It Covers

- task fixtures grounded in `burn` and `codex`
- benchmark-condition preparation helpers
- lightweight automatic scoring for required mentions, forbidden claims, locations, relations, and refresh decisions

This is not yet a full agent runner. It is the harness layer that makes a later `with atlas` vs `without atlas` evaluation reproducible.

## Layout

```text
benchmarks/
  README.md
  answers/
    reference_atlas/
    reference_baseline/
  reports/
  tasks/
    burn/
    codex/
```

## Commands

List the task set:

```bash
python3 scripts/benchmark.py list-tasks
```

Prepare a repository for a benchmark condition:

```bash
python3 scripts/benchmark.py prepare-condition \
  --repo-root /abs/repo \
  --condition fresh-atlas
```

Score one answer file against one task:

```bash
python3 scripts/benchmark.py score-answer \
  --task benchmarks/tasks/burn/burn.trace.backend.decorator-path.001.json \
  --answer /abs/answer.json
```

Score a directory of answer JSON files:

```bash
python3 scripts/benchmark.py score-batch \
  --answers-dir /abs/answers
```

Score every answer set under `benchmarks/answers/` and generate a suite report:

```bash
python3 scripts/benchmark.py score-suite \
  --answers-root benchmarks/answers \
  --baseline-label reference_baseline \
  --out-json benchmarks/reports/reference_suite.json \
  --out-md benchmarks/reports/reference_suite.md
```

## Answer File Shape

The automatic scorer expects JSON like:

```json
{
  "task_id": "burn.trace.backend.decorator-path.001",
  "final_answer": "burn-backend defines the interface while autodiff and fusion decorate it.",
  "locations": [
    "crates/burn-backend/src/backend/base.rs#Backend",
    "crates/burn-autodiff/src/backend.rs#Autodiff"
  ],
  "relations": [
    {"lhs": "Autodiff", "relation": "decorates", "rhs": "Backend"}
  ],
  "refresh_decision": "reuse"
}
```

The repo now includes two curated answer sets:

- `reference_atlas`: strong reference answers written to match the atlas-backed understanding target
- `reference_baseline`: plausible but less complete answers that model pre-atlas orientation quality

These are reference fixtures for validating the scoring/reporting pipeline. They are not live model outputs.

Generated reports can be written to `benchmarks/reports/` so the repo carries both the scoring code and a reproducible first score sheet.

## Current Scope

- `fresh-atlas`, `stale-atlas`, `partial-atlas`, and `baseline` condition preparation
- automatic metrics only
- reference answer-set scoring and suite-level comparison reports
- no built-in model runner yet
- no human rubric capture yet
