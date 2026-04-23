# Benchmark Protocol Spec

## Purpose

This benchmark measures whether `rust-repo-atlas` helps agents understand Rust repositories more quickly, more correctly, and more completely than a no-atlas baseline.

It does not treat end-to-end code editing success as the first metric. The primary goal is to measure understanding uplift.

## Evaluation Philosophy

- Measure workflow delta, not just raw model capability.
- Keep repository snapshots fixed.
- Compare `with atlas` and `without atlas` under matched time, token, and tool budgets.
- Reward correctness, evidence faithfulness, completeness, and calibration.
- Treat stale-atlas handling as a first-class evaluation target.

## Non-Goals

This benchmark does not try to:

- replace broader software engineering agent evaluations such as end-to-end bug fixing
- prove that atlas removes the need to read source code
- optimize for one exact answer wording
- rank foundation models in the abstract
- evaluate non-Rust understanding quality as a primary target

## Repositories Under Test

| Repo | Archetype | Why It Matters |
| --- | --- | --- |
| `burn` | Rust-centric framework workspace | Stresses traits, generics, decorators, facade crates, and cross-crate architecture |
| `codex` | Mixed-language product repo with Rust focus subtree | Stresses Rust focus root discovery, mixed-language boundaries, and large workspace navigation |

Initial snapshots:

- `burn`: `v0.20.1` or latest according to configured policy
- `codex`: latest including prerelease, for example `rust-v0.122.0-alpha.9`

## Snapshot Discipline

Each benchmark task binds:

- an exact repo snapshot
- an atlas condition
- a fixed agent configuration

Required snapshot metadata:

- exact commit
- resolved ref or tag
- release channel
- dirty status
- version policy used to choose it

## Benchmark Conditions

| Condition | Description | Why It Matters |
| --- | --- | --- |
| `baseline` | No atlas present in repo root | Measures raw understanding |
| `fresh-atlas` | Repo-local atlas matches current snapshot | Measures best-case atlas value |
| `stale-atlas` | Repo-local atlas exists but is stale | Measures drift handling and calibration |
| `partial-atlas` | Only lightweight atlas outputs exist | Measures whether partial artifacts still help |

Condition setup should be done by manipulating `<repo_root>/.rust-repo-atlas/`.

## Task Taxonomy

| Level | Name | Goal |
| --- | --- | --- |
| `L1` | Orientation | Build the right global picture quickly |
| `L2` | Localization | Find the right crate, file, symbol, or entrypoint |
| `L3` | Relation Tracing | Explain important relationships and paths |
| `L4` | Change Planning | Plan where and how to modify the repo safely |
| `L5` | Refresh Discipline | Decide whether atlas reuse or refresh is appropriate |

## Task Format

Task example:

```json
{
  "task_id": "burn.trace.backend.decorator-path.001",
  "repo_name": "burn",
  "repo_snapshot": "v0.20.1",
  "condition": "fresh-atlas",
  "prompt": "Explain how backend composition works in burn and identify the main crates involved.",
  "must_include": ["burn-backend", "burn-autodiff", "burn-fusion"],
  "must_not_claim": ["single monolithic crate"],
  "gold_locations": [
    "crates/burn-backend/src/backend/base.rs#Backend",
    "crates/burn-autodiff/src/backend.rs#Autodiff"
  ],
  "gold_relations": [
    {"lhs": "Autodiff", "relation": "decorates", "rhs": "Backend"},
    {"lhs": "Fusion", "relation": "decorates", "rhs": "Backend"}
  ]
}
```

Codex example:

```json
{
  "task_id": "codex.localize.rust-focus-root.001",
  "repo_name": "codex",
  "repo_snapshot": "rust-v0.122.0-alpha.9",
  "condition": "fresh-atlas",
  "prompt": "Identify the main Rust workspace inside codex and explain why an agent should treat it as the Rust focus root.",
  "must_include": ["codex-rs", "mixed-language repository", "workspace root"],
  "must_not_claim": ["the repository root itself is the only Rust workspace"],
  "gold_locations": [
    "codex-rs/Cargo.toml",
    "codex-rs/cli/Cargo.toml"
  ],
  "gold_relations": [
    {"lhs": "codex-rs", "relation": "contains", "rhs": "primary Rust workspace"},
    {"lhs": "repo root", "relation": "contains", "rhs": "mixed-language context"}
  ]
}
```

## Gold Annotation Guidelines

Gold data should be written by humans with direct repo evidence and should distinguish:

- mandatory concepts
- optional but good details
- forbidden hallucinations
- precise file or symbol anchors
- expected relation types

Gold annotations should prefer stable conceptual truths over brittle wording.

## Metrics

| Metric | Definition | Why It Matters | How Measured |
| --- | --- | --- | --- |
| `correctness` | Core answer truth | Measures actual understanding | rubric or automatic checks |
| `evidence_faithfulness` | Claims supported by evidence | Prevents plausible hallucinations | evidence review |
| `completeness` | Important aspects covered | Avoids partial understanding | rubric |
| `calibration` | Uncertainty handled honestly | Important for stale/partial atlas use | rubric |
| `localization_accuracy` | Correct anchor paths or symbols found | Key practical skill | exact or fuzzy match |
| `relation_accuracy` | Correct relations identified | Tests architecture understanding | graph-style comparison |
| `exploration_efficiency` | Cost of arriving at answer | Measures workflow value | time/tokens/file reads/tools |
| `refresh_discipline` | Good reuse vs refresh decisions | Tests runtime use, not only content | condition-aware grading |

## Scoring

Recommended scoring split:

- automatic:
  - localization accuracy
  - required/forbidden mentions
  - some relation matches
- semi-automatic:
  - evidence faithfulness
  - refresh discipline
- rubric-based:
  - correctness
  - completeness
  - calibration

Rubric example:

```json
{
  "correctness": 4,
  "evidence_faithfulness": 4,
  "completeness": 3,
  "calibration": 2
}
```

## Run Protocol

```text
prepare snapshot
-> install benchmark condition
-> run agent under fixed budget
-> collect answer, evidence, and trace stats
-> score automatically where possible
-> apply human rubric where needed
```

Required run outputs:

- final answer
- cited evidence if present
- tool usage summary
- file access summary
- token/time budget summary
- refresh decision if atlas was present

## Artifact-Aware Tasks

These tasks exist specifically because atlas is repo-local:

- discover whether `.rust-repo-atlas/` exists
- determine whether the current atlas is `fresh`, `stale`, or `partial`
- decide whether refresh is needed for the asked task
- reuse a fresh atlas without unnecessary work
- refuse over-trusting a stale or partial atlas

## Success Criteria

Minimum v0 success standard:

- `fresh-atlas` beats `baseline` on `L1-L4` correctness
- `fresh-atlas` improves localization efficiency
- `evidence_faithfulness` does not regress
- `stale-atlas` does not cause major calibration collapse
- `partial-atlas` shows some improvement over baseline without misleading the agent

## Threats to Validity

- Overfitting to `burn` and `codex`
- Gold labels that leak expected wording instead of expected understanding
- Tasks that reward atlas-specific phrasing instead of real comprehension
- Budget mismatches between conditions
- Evaluators conflating verbosity with correctness

## Versioning

The benchmark itself must be versioned across:

- task set version
- gold set version
- repository snapshot
- atlas schema version
- scoring rubric version

## Open Questions

- When to add a third repository archetype.
- Whether v1 should include end-to-end modification tasks after understanding metrics stabilize.
- Whether stale-atlas conditions should later include intentionally misleading artifacts.
