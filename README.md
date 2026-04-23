# Rust Repo Atlas

Rust Repo Atlas is a Codex skill and repo-local harness for quickly orienting agents inside large Rust repositories and Rust-heavy mixed-language codebases.

It generates an evidence-backed atlas under each target repository:

```text
<repo>/.rust-repo-atlas/
  state.json
  snapshots/<snapshot_id>/manifest.json
  bundles/<snapshot_id>/
    overview.md
    repo-profile.json
    global-model.json
    flows.json
    playbooks.json
    evidence.json
    crate-graph.json
    coupling-map.json
    impact-index.json
    diagnostics.json
```

The goal is not to replace source reading. The goal is to make the first pass cheaper, safer, and easier to audit.

## Why

Strong coding agents work best when they can choose their own exploration strategy, but large Rust workspaces still benefit from a reliable first map. Rust Repo Atlas provides:

- Freshness and drift checks for repo-local atlas artifacts.
- Rust focus root detection for mixed-language repositories.
- Workspace, crate, entrypoint, subsystem, and flow summaries.
- A crate-level dependency and reverse-dependency graph from Cargo metadata.
- Coupling hints that combine real dependency edges with softer subsystem context.
- Impact seeds that show likely affected crates before a change.
- Evidence profiles that distinguish manifest, document, symbol, relation, query, and heuristic support.
- Optional playbooks for orientation, localization, relation tracing, change planning, and impact analysis.

It is designed as a soft harness: facts, confidence signals, and reading surfaces are exposed to the agent, while task-specific decisions stay with the agent.

## Quick Start

Bind a repository:

```bash
python3 scripts/controller.py bind --repo-root /path/to/repo
```

Generate an atlas:

```bash
python3 scripts/controller.py refresh --repo-root /path/to/repo --coverage-level core
```

Inspect reuse guidance:

```bash
python3 scripts/controller.py explain --repo-root /path/to/repo
```

Validate the current bundle:

```bash
python3 scripts/controller.py validate --repo-root /path/to/repo
```

## Coverage Levels

- `profile`: optimized for orientation and workspace localization.
- `core`: default navigation model with subsystems, flows, playbooks, and evidence.
- `deep`: currently core-plus diagnostics; reserved for future API and symbol-level analyzers.

Coverage metadata is emitted in the artifacts so agents can decide whether to reuse, refresh, or verify source directly.

## Impact Atlas Artifacts

Rust Repo Atlas now emits three crate-level impact surfaces:

- `crate-graph.json`: workspace crate nodes, Cargo dependency edges, reverse dependencies, and transitive dependency/dependent indexes.
- `coupling-map.json`: candidate clusters and strong crate pairs, with reasons such as direct dependency edges or shared subsystem grouping.
- `impact-index.json`: one seed per crate showing likely affected reverse dependencies, coupled neighbors, and first paths to verify.

These artifacts are intentionally conservative. They describe candidate impact surfaces for agent exploration; they are not a call graph and they do not replace source or test verification.

## Benchmark Scaffold

The repository includes a lightweight benchmark harness for measuring orientation and localization uplift:

```bash
python3 scripts/benchmark.py list-tasks
python3 scripts/benchmark.py score-suite \
  --answers-root benchmarks/answers \
  --baseline-label reference_baseline
```

The current reference suite covers `burn` and `codex` tasks and compares atlas-backed answers against baseline answers.

## Skill Packaging

Build a distributable skill package:

```bash
python3 scripts/build_skill_dist.py
```

Install it into a Codex skills directory:

```bash
python3 scripts/install_skill.py --upgrade
```

The built package lives under `skill/rust-repo-atlas/` and contains only the skill-facing runtime, metadata, and references.

## Development

Run the tests:

```bash
python3 -m unittest discover -s tests
```

Run syntax checks:

```bash
python3 -m py_compile scripts/*.py tests/*.py
```

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
