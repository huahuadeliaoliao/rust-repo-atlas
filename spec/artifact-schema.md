# Artifact Schema Spec

## Purpose

An atlas bundle is the agent-facing world model for one repository snapshot. It converts Rust-native evidence into a short reading surface and a structured fact surface. The structured surface is the source of truth; rendered Markdown exists to make that truth easier to consume quickly.

## Design Principles

- JSON is the source of truth.
- Markdown is the reading surface.
- Every architectural claim must be evidence-backed.
- Evidence should expose type and strength so agents can decide how much to trust it.
- Artifacts should support both fast orientation and deep follow-up.
- Bundles are repo-local and snapshot-specific by default.

## Non-Goals

The artifact bundle is not intended to:

- preserve raw analyzer outputs without reduction
- become a second copy of the repository source tree
- replace targeted source reading for risky or ambiguous changes
- act as a generic cross-repo memory store
- store user-private task history unrelated to the repository snapshot

## Bundle Placement

Default bundle root:

```text
<repo_root>/.rust-repo-atlas/bundles/<snapshot_id>/
```

Bundles are repo-local because they are properties of one repo snapshot, not global user state.

## Bundle Layout

```text
bundles/<snapshot_id>/
  overview.md
  repo-profile.json
  global-model.json
  flows.json
  playbooks.json
  evidence.json
  diagnostics.json
  rendered/
    global-model.md
    playbooks/
      orientation.md
      localization.md
      relation-tracing.md
      change-planning.md
```

## Artifact Taxonomy

- `overview.md`
  The shortest reusable repo summary. Agents should read this first.
- `repo-profile.json`
  Snapshot-level facts: workspace, Rust focus root, major entrypoints, build/test surface, and language mix.
- `global-model.json`
  High-level concepts, subsystems, boundaries, invariants, and architecture claims.
- `flows.json`
  Execution, dependency, data, and control flows that matter for understanding and change planning.
- `playbooks.json`
  Task-oriented navigation plans for agents.
- `evidence.json`
  Claim-to-evidence index grounded in concrete files, symbols, or queries.
- `diagnostics.json`
  Coverage, low-confidence zones, tool failures, and portability notes.

## Agent Consumption Order

Recommended read order:

1. `overview.md`
2. `repo-profile.json`
3. `global-model.json`
4. `flows.json` and `playbooks.json` for task-specific deepening
5. `evidence.json` to validate important claims

Agents should not start from `evidence.json` unless the task is already narrow and symbol-specific.

## Common Metadata Header

Every JSON artifact must include a small shared header:

```json
{
  "schema_version": 1,
  "repo_root": "/abs/repo",
  "snapshot_id": "git:75b7881397df1f21e5c2bf51cd3aa6b9ae2bb6a4:clean",
  "generated_at": "2026-04-22T13:04:30Z",
  "generator": {
    "name": "rust-repo-atlas",
    "version": "0.x"
  }
}
```

| Field | Required | Type | Description | Example | Consumer |
| --- | --- | --- | --- | --- | --- |
| `schema_version` | yes | integer | Artifact schema version | `1` | harness, validator |
| `repo_root` | yes | absolute path | Repo root for this bundle | `/abs/repo` | agent, harness |
| `snapshot_id` | yes | string | Snapshot represented by this artifact | `git:...` | agent, evaluator |
| `generated_at` | yes | ISO-8601 string | Generation time | `...` | agent, harness |
| `generator` | yes | object | Generator metadata | `{...}` | harness, evaluator |

## Schema: `repo-profile.json`

Purpose:

- describe the shape of the repo before any deeper architecture claims
- expose the Rust focus root for mixed-language repositories

Core fields:

| Field | Required | Type | Description | Example | Consumer |
| --- | --- | --- | --- | --- | --- |
| `repo_name` | yes | string | Human-readable repo name | `burn` | agent |
| `repo_archetype` | yes | enum | High-level repo shape | `framework-workspace` | agent, evaluator |
| `atlas_root` | yes | absolute path | Repo-local atlas root | `/abs/repo/.rust-repo-atlas` | agent |
| `storage_mode` | yes | enum | Storage placement | `repo-local` | harness |
| `source_kind` | yes | enum | Git vs filesystem | `git` | harness |
| `workspace_root` | yes | absolute path | Cargo workspace root | `/abs/repo` | agent |
| `rust_focus_root` | yes | absolute path | Primary Rust subtree | `/abs/repo/codex-rs` | agent |
| `rust_focus_root_reason` | yes | string | Why that subtree was chosen | `largest Rust workspace root` | agent |
| `workspace_kind` | yes | enum | Structural classification | `mixed` | harness, agent |
| `crates` | yes | array | Major crate descriptors | `[...]` | agent |
| `entrypoints` | yes | array | Main Rust entrypoints | `[...]` | agent |
| `build_surface` | no | array | Important build commands or roots | `[...]` | agent |
| `test_surface` | no | array | Important test commands or roots | `[...]` | agent |
| `language_mix` | yes | array | Language distribution summary | `[...]` | agent |

## Schema: `global-model.json`

Purpose:

- capture the stable abstractions and subsystem boundaries of the repository
- avoid turning raw directory structure into a fake conceptual model

Core objects:

- `concepts`
- `subsystems`
- `boundaries`
- `invariants`
- `claims`

Claim example:

```json
{
  "id": "claim.burn.decorator-model",
  "kind": "architecture",
  "text": "Burn organizes backend capabilities through backend-generic abstractions plus decorators.",
  "confidence": "high",
  "scope": "repo",
  "evidence_ids": ["ev-burn-backend", "ev-burn-readme"],
  "evidence_profile": {
    "evidence_types": ["doc", "manifest"],
    "weakest_strength": "medium",
    "support_count": 2,
    "missing_evidence_ids": [],
    "agent_note": "Use as navigation context; verify source before relying on this as a symbol-level relation."
  }
}
```

Fields:

| Field | Required | Type | Description | Example | Consumer |
| --- | --- | --- | --- | --- | --- |
| `concepts` | yes | array | Key repository concepts | `[...]` | agent |
| `subsystems` | yes | array | Major subsystems and roles | `[...]` | agent |
| `boundaries` | yes | array | Important subsystem boundaries | `[...]` | agent |
| `invariants` | no | array | Stable rules the repo relies on | `[...]` | agent |
| `claims` | yes | array | Evidence-backed architecture claims | `[...]` | agent, evaluator |

## Schema: `flows.json`

Purpose:

- represent the relationships agents most often need when tracing behavior or planning changes

Allowed flow kinds:

- `execution`
- `dependency`
- `data`
- `control`

Flow example:

```json
{
  "id": "flow.burn.training-path",
  "kind": "execution",
  "title": "guide training path",
  "nodes": [
    {"id": "n1", "label": "examples/guide/src/bin/train.rs", "kind": "entrypoint", "evidence_ids": ["ev1"]},
    {"id": "n2", "label": "burn-train learner", "kind": "subsystem", "evidence_ids": ["ev2"]}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "relation": "constructs"}
  ]
}
```

Fields:

| Field | Required | Type | Description | Example | Consumer |
| --- | --- | --- | --- | --- | --- |
| `flows` | yes | array | Flow collection | `[...]` | agent |
| `id` | yes | string | Flow identifier | `flow...` | harness |
| `kind` | yes | enum | Flow type | `execution` | agent |
| `title` | yes | string | Human-readable label | `guide training path` | agent |
| `nodes` | yes | array | Nodes in the flow | `[...]` | agent |
| `edges` | yes | array | Directed relations | `[...]` | agent |

## Schema: `playbooks.json`

Purpose:

- tell agents how to read the repo for recurring task types

Task types:

- `orientation`
- `localization`
- `relation-tracing`
- `change-planning`
- `impact-analysis`

Playbook example:

```json
{
  "id": "playbook.modify-backend-trait",
  "task_type": "change-planning",
  "when_to_use": "Need to change a trait implemented across multiple crates.",
  "read_order": ["repo-profile", "global-model", "flows:backend", "evidence"],
  "queries": ["find trait definition", "find all impls", "find re-exports"],
  "pitfalls": ["feature-gated impls", "proc macros", "facade re-exports"]
}
```

Fields:

| Field | Required | Type | Description | Example | Consumer |
| --- | --- | --- | --- | --- | --- |
| `playbooks` | yes | array | Playbook collection | `[...]` | agent |
| `id` | yes | string | Playbook id | `playbook...` | harness |
| `task_type` | yes | enum | Task family | `change-planning` | agent |
| `when_to_use` | yes | string | Trigger description | `Need to change...` | agent |
| `read_order` | yes | array | Recommended read sequence | `[...]` | agent |
| `queries` | yes | array | Suggested queries or checks | `[...]` | agent |
| `pitfalls` | no | array | Common mistakes | `[...]` | agent |

## Schema: `evidence.json`

Purpose:

- make every important claim auditable

Evidence example:

```json
{
  "id": "ev-burn-backend",
  "kind": "symbol",
  "evidence_type": "symbol",
  "strength": "high",
  "path": "/abs/repo/crates/burn-backend/src/backend/base.rs",
  "symbol": "Backend",
  "locator": "trait Backend",
  "source": "manual",
  "snapshot_id": "git:..."
}
```

Allowed sources:

- `cargo-metadata`
- `rust-analyzer`
- `cargo-modules`
- `cargo-expand`
- `rustdoc-json`
- `cargo-public-api`
- `manual`

Fields:

| Field | Required | Type | Description | Example | Consumer |
| --- | --- | --- | --- | --- | --- |
| `evidence` | yes | array | Evidence collection | `[...]` | agent, evaluator |
| `id` | yes | string | Evidence id | `ev...` | harness |
| `kind` | yes | enum | Evidence type | `symbol` | agent |
| `evidence_type` | no | enum | Support class: `manifest`, `doc`, `symbol`, `relation`, `query`, or `heuristic` | `manifest` | agent |
| `strength` | no | enum | Support strength: `high`, `medium`, or `low` | `medium` | agent |
| `path` | yes | absolute path | Evidence file path | `/abs/repo/...` | agent |
| `symbol` | no | string | Symbol name if relevant | `Backend` | agent |
| `locator` | no | string | Text locator | `trait Backend` | agent |
| `source` | yes | enum | Evidence origin | `rust-analyzer` | evaluator |
| `snapshot_id` | yes | string | Snapshot that produced the evidence | `git:...` | evaluator |

## Schema: `diagnostics.json`

Purpose:

- expose confidence, missing coverage, failures, and portability limitations

Diagnostics example:

```json
{
  "coverage_level": "core",
  "low_confidence_areas": ["macro-expanded API surface"],
  "tool_failures": [],
  "reuse_status": "safe",
  "portability": {
    "repo_local": true,
    "shareable_files": ["overview.md", "rendered/global-model.md"],
    "nonportable_reasons": ["absolute evidence paths"]
  }
}
```

Fields:

| Field | Required | Type | Description | Example | Consumer |
| --- | --- | --- | --- | --- | --- |
| `coverage_level` | yes | enum | `profile`, `core`, or `deep` | `core` | agent |
| `low_confidence_areas` | no | array | Weakly supported areas | `[...]` | agent |
| `tool_failures` | no | array | Tool failures during generation | `[...]` | harness |
| `reuse_status` | yes | enum | `safe`, `stale`, or `partial` | `safe` | agent |
| `portability` | yes | object | Shareability notes | `{...}` | agent, evaluator |

## Rendered Views

Rendered Markdown files exist for fast reading. They must follow two rules:

- they summarize and organize facts already present in JSON artifacts
- they do not introduce unsupported new claims

## Coverage Levels

| Level | Meaning | Minimum Outputs |
| --- | --- | --- |
| `profile` | Quick structural orientation | `overview.md`, `repo-profile.json`, basic `evidence.json` |
| `core` | Default full atlas | all primary artifacts |
| `deep` | Expanded evidence and analysis | all primary artifacts plus deeper flows, APIs, and diagnostics |

## Shareability and Portability

Repo-local storage is the default, but not every file is equally portable.

- Good sharing candidates:
  - `overview.md`
  - `rendered/global-model.md`
  - selected benchmark fixtures
- Weak portability:
  - `evidence.json` with absolute paths
  - diagnostics that mention local tool failures

The bundle must still remain valid when used only inside the original repo root.

## Validation Rules

Minimum validation checks:

- every JSON file has the common metadata header
- every claim references existing `evidence_ids`
- every flow node and edge refer to valid node ids
- every playbook task type is in the allowed set
- `diagnostics.coverage_level` matches runtime state coverage

## Open Questions

- Whether v0 should include a dedicated public API artifact when `rustdoc-json` or `cargo-public-api` is available.
- Whether future versions should support relative-path evidence as the default for better portability.
