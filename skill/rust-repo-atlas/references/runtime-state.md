# Runtime State Spec

## Purpose

`rust-repo-atlas` is a repo world-model runtime for Rust-first repositories. It binds to a specific repository root, resolves a snapshot identity, tracks whether atlas artifacts are fresh enough to reuse, and points agents toward the right atlas bundle.

It is not a task runtime, a background watcher, or a generic code index. Its persistent state should stay small, explicit, and local to the repository being analyzed.

## Design Principles

- Repo-local first: derived state and artifacts live under `<repo_root>/.rust-repo-atlas/`.
- Manual refresh by default: the runtime detects likely drift automatically but leaves expensive refresh decisions to the agent.
- Minimal persistent state: only store what is required to bind the repo, identify the snapshot, judge freshness, and locate the current bundle.
- Rust-first, mixed-language tolerant: Rust is the primary analysis target, but the runtime must tolerate repos where Rust is only one major subsystem.
- Evidence before narrative: state tracks facts and bundle locations, not long-form summaries.

## Runtime Scope

### In scope

- Bind a repo root and resolve the Rust focus root.
- Detect whether the source is a Git repository or a plain filesystem tree.
- Resolve a snapshot identity.
- Track freshness and stale reasons.
- Record which atlas bundle is current.
- Expose a small harness command surface for `bind`, `inspect`, `refresh`, `drift`, `explain`, and `close`.

### Out of scope

- Storing long natural-language summaries in runtime state.
- Acting as a general repository memory store for unrelated tasks.
- Performing continuous background indexing by default.
- Keeping full analyzer raw outputs in the state file.
- Replacing the atlas bundle with ad hoc summaries.

## Storage Model

### Default location

All repo-derived state and artifacts default to:

```text
<repo_root>/.rust-repo-atlas/
```

This is preferred over `~/.codex/` because atlas artifacts are properties of the repository snapshot, not user-private preferences. Repo-local placement makes them easier to inspect, ignore, share selectively, version against commits, and use in benchmark fixtures.

### Global-only resources

Only skill-global resources belong outside the repo, such as:

- the skill code itself
- reusable templates
- bundled references
- helper scripts that are not tied to one repository snapshot

## Directory Layout

```text
<repo_root>/.rust-repo-atlas/
  state.json
  snapshots/
    <snapshot_id>/
      manifest.json
  bundles/
    <snapshot_id>/
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
      rendered/
  cache/
  eval/
```

Notes:

- `state.json` is the live runtime pointer, not the full atlas.
- `snapshots/<snapshot_id>/manifest.json` records one refresh run.
- `bundles/<snapshot_id>/` contains agent-facing atlas outputs.
- `cache/` is for disposable helper data.
- `eval/` is for benchmark runs and should not affect normal runtime semantics.

## State Model

The runtime state has seven top-level objects:

- `runtime`: runtime metadata and high-level status
- `binding`: repo binding facts
- `snapshot`: resolved snapshot identity
- `freshness`: freshness status and stale reasons
- `artifacts`: pointers to the current atlas bundle
- `policy`: refresh and version resolution policy
- `agent_hints`: short recommendations for what the agent should do next

## State Schema

```json
{
  "runtime": {
    "schema_version": 1,
    "tool_version": "0.x",
    "repo_id": "stable-id",
    "status": "ready",
    "created_at": "2026-04-22T13:00:00Z",
    "updated_at": "2026-04-22T13:05:00Z",
    "atlas_root": "/abs/repo/.rust-repo-atlas",
    "last_error": ""
  },
  "binding": {
    "repo_root": "/abs/repo",
    "source_kind": "git",
    "rust_focus_root": "/abs/repo/codex-rs",
    "workspace_root": "/abs/repo/codex-rs",
    "workspace_kind": "mixed",
    "language_focus": ["rust"],
    "language_context": ["typescript", "python"],
    "rust_focus_candidates": [
      {"path": "/abs/repo/codex-rs", "relative_path": "codex-rs", "score": 120.0, "reasons": ["selected Rust focus root"]}
    ]
  },
  "snapshot": {
    "identity": "d65ed92a5e440972626965d0af9a6345179783bc",
    "resolved_ref": "tag",
    "commit": "d65ed92a5e440972626965d0af9a6345179783bc",
    "tag": "rust-v0.121.0",
    "dirty": false,
    "fingerprint": "",
    "content_fingerprint": "",
    "fingerprint_scope": [],
    "release_channel": "stable",
    "version_policy": "latest",
    "observed_at": "2026-04-22T13:05:00Z"
  },
  "freshness": {
    "status": "fresh",
    "reasons": [],
    "last_checked_at": "2026-04-22T13:05:00Z",
    "checked_against": "git:d65ed92a5e440972626965d0af9a6345179783bc:clean"
  },
  "artifacts": {
    "current_snapshot_id": "git:d65ed92a5e440972626965d0af9a6345179783bc:clean",
    "current_manifest_path": "/abs/repo/.rust-repo-atlas/snapshots/git:d65ed92.../manifest.json",
    "current_bundle_path": "/abs/repo/.rust-repo-atlas/bundles/git:d65ed92.../",
    "generated_at": "2026-04-22T13:04:30Z",
    "coverage_level": "core",
    "tool_version": "0.x",
    "artifact_schema_version": 1
  },
  "policy": {
    "storage_mode": "repo-local",
    "refresh_mode": "manual",
    "stale_check_mode": "cheap",
    "analysis_profile": "default",
    "allow_prerelease": true
  },
  "agent_hints": {
    "recommended_action": "reuse",
    "recommended_actions": [
      {"action": "reuse_for_orientation", "confidence": "high", "why": "Current bundle matches the current snapshot."}
    ],
    "why": "Current bundle matches the current clean snapshot."
  }
}
```

## Field Reference

### `runtime`

| Field | Required | Type | Meaning | Example | Why Needed |
| --- | --- | --- | --- | --- | --- |
| `schema_version` | yes | integer | State schema version | `1` | Enables migration and validation |
| `tool_version` | yes | string | Atlas runtime version | `0.x` | Ties state to generator behavior |
| `repo_id` | yes | string | Stable repo-local identifier | `stable-id` | Lets tools refer to the bound repo consistently |
| `status` | yes | enum | Runtime status | `ready` | Gives a compact lifecycle state |
| `created_at` | yes | ISO-8601 string | First bind time | `...` | Provenance |
| `updated_at` | yes | ISO-8601 string | Last state change | `...` | Drift and debugging |
| `atlas_root` | yes | absolute path | Repo-local atlas root | `/abs/repo/.rust-repo-atlas` | Defines storage location |
| `last_error` | no | string | Most recent short error | `cargo metadata failed` | Fast recovery hint |

### `binding`

| Field | Required | Type | Meaning | Example | Why Needed |
| --- | --- | --- | --- | --- | --- |
| `repo_root` | yes | absolute path | Bound repository root | `/abs/repo` | Primary target |
| `source_kind` | yes | enum | Snapshot source mode | `git` | Changes identity rules |
| `rust_focus_root` | yes | absolute path | Rust-heavy subtree | `/abs/repo/codex-rs` | Helps mixed-language repos |
| `workspace_root` | yes | absolute path | Cargo workspace root | `/abs/repo/codex-rs` | Tool entrypoint |
| `workspace_kind` | yes | enum | Structural shape | `mixed` | Affects heuristics |
| `language_focus` | yes | string array | Main analysis languages | `["rust"]` | Explicit scope |
| `language_context` | no | string array | Secondary languages | `["typescript"]` | Peripheral context |
| `rust_focus_candidates` | no | object array | Ranked possible Rust focus roots with scores and reasons | `[...]` | Lets agents override defaults when task context warrants it |

### `snapshot`

| Field | Required | Type | Meaning | Example | Why Needed |
| --- | --- | --- | --- | --- | --- |
| `identity` | yes | string | Canonical snapshot identity | commit or fingerprint | Stable comparison key |
| `resolved_ref` | yes | enum | Ref interpretation | `tag` | Explains how snapshot was resolved |
| `commit` | conditional | string | Git commit | `d65ed9...` | Git snapshot traceability |
| `tag` | no | string | Tag if present | `rust-v0.121.0` | Release context |
| `dirty` | yes | boolean | Dirty worktree flag | `false` | Freshness semantics |
| `fingerprint` | conditional | string | Filesystem identity | hash | Non-Git support |
| `content_fingerprint` | no | string | Dirty-worktree or filesystem content hash over atlas-relevant files | hash | Detects semantic drift within the same dirty commit |
| `fingerprint_scope` | no | string array | Files considered by the content fingerprint | `["README.md"]` | Makes freshness scope auditable |
| `release_channel` | yes | enum | `stable`, `prerelease`, `unknown`, or `none` | `stable` | Important for version policy |
| `version_policy` | yes | enum | Resolution policy | `latest` | Makes policy explicit |
| `observed_at` | yes | ISO-8601 string | When snapshot was read | `...` | Provenance |

### `freshness`

| Field | Required | Type | Meaning | Example | Why Needed |
| --- | --- | --- | --- | --- | --- |
| `status` | yes | enum | `fresh`, `stale`, or `unknown` | `fresh` | Reuse decision |
| `reasons` | yes | string array | Stale reasons | `["head_changed"]` | Explains mismatch |
| `last_checked_at` | yes | ISO-8601 string | Last freshness check | `...` | Provenance |
| `checked_against` | yes | string | Snapshot id used for the check | `git:...` | Cross-check anchor |

### `artifacts`

| Field | Required | Type | Meaning | Example | Why Needed |
| --- | --- | --- | --- | --- | --- |
| `current_snapshot_id` | no | string | Snapshot currently represented by bundle | `git:...` | Main reuse pointer |
| `current_manifest_path` | no | absolute path | Current snapshot manifest | `/abs/repo/.../manifest.json` | Detailed provenance |
| `current_bundle_path` | no | absolute path | Current atlas bundle | `/abs/repo/.../bundles/...` | Entry point for reuse |
| `generated_at` | no | ISO-8601 string | When current bundle was built | `...` | Freshness context |
| `coverage_level` | no | enum | `profile`, `core`, or `deep` | `core` | Tells the agent how much to trust bundle breadth |
| `tool_version` | no | string | Runtime version that generated the current bundle | `0.x` | Marks bundles stale after generator changes |
| `artifact_schema_version` | no | integer | Artifact schema version that generated the current bundle | `1` | Marks bundles stale after schema changes |

### `policy`

| Field | Required | Type | Meaning | Example | Why Needed |
| --- | --- | --- | --- | --- | --- |
| `storage_mode` | yes | enum | Storage placement policy | `repo-local` | Encodes a top-level design rule |
| `refresh_mode` | yes | enum | Refresh strategy | `manual` | Preserves harness boundaries |
| `stale_check_mode` | yes | enum | Cheap vs deep drift detection | `cheap` | Cost control |
| `analysis_profile` | yes | enum | Default analysis depth | `default` | Controls refresh scope |
| `allow_prerelease` | yes | boolean | Whether `latest` includes prereleases | `true` | Matches version policy |

### `agent_hints`

| Field | Required | Type | Meaning | Example | Why Needed |
| --- | --- | --- | --- | --- | --- |
| `recommended_action` | no | enum | Runtime suggestion | `reuse` | Fast next step |
| `recommended_actions` | no | object array | Multiple non-binding action options with confidence and rationale | `[...]` | Keeps the runtime as a soft harness rather than a decision engine |
| `why` | no | string | One short explanation | `Current bundle matches...` | Human-readable rationale |

## Non-Goals for State

The following do not belong in `state.json`:

- Long architecture narratives
- Full crate or symbol graphs
- Raw tool stdout/stderr
- Benchmark results
- Conversation history
- Arbitrary task memory unrelated to the repository snapshot

## Snapshot Identity Rules

### Git repositories

The runtime should prefer a Git identity of the form:

```text
git:<commit>:clean
git:<commit>:dirty
```

If a tag is available it should be stored separately in `snapshot.tag`, not used as the sole identity.

### Non-Git repositories

The runtime should fall back to:

- a fingerprint over Rust manifests and selected Rust source paths
- an observation timestamp

Recommended identity form:

```text
fs:<fingerprint>
```

### Version policy

`version_policy = latest` includes prereleases when `allow_prerelease = true`.

Examples:

- `burn` may resolve to `v0.21.0-pre.3`
- `codex` may resolve to `rust-v0.122.0-alpha.9`

## Freshness Semantics

- `fresh`: current repo snapshot matches the current atlas bundle snapshot
- `stale`: a known mismatch exists
- `unknown`: the runtime cannot cheaply prove freshness or staleness

Suggested stale reasons:

- `head_changed`
- `dirty_changed`
- `workspace_manifest_changed`
- `fingerprint_changed`
- `tool_version_changed`
- `bundle_missing`
- `manifest_missing`

## Refresh Semantics

Default behavior:

- run a cheap stale check automatically
- do not rebuild the atlas automatically
- leave refresh decisions to the agent

Recommended agent actions:

- `fresh`: reuse bundle by default
- `stale`: inspect drift, then decide refresh
- `unknown`: decide based on task sensitivity and repo change surface

## Command Surface

Conceptual commands:

- `bind`
  Bind a repo and create initial state.
- `inspect`
  Show binding, snapshot, freshness, and bundle pointers.
- `refresh`
  Generate or rebuild atlas artifacts for the current snapshot.
- `drift`
  Compare current repo state with the atlas snapshot.
- `explain`
  Provide the shortest path to reuse the atlas safely.
- `close`
  Mark the runtime as intentionally closed.

These commands define semantics, not a final CLI.

## Error and Recovery Model

- Missing `state.json`: treat as unbound, not broken.
- Broken `state.json`: keep repo-local evidence, report error, and require repair.
- Missing bundle with valid state: mark `freshness = stale` with `bundle_missing`.
- Tool failure during refresh: keep prior bundle if valid; record a short `last_error`.
- Workspace root resolution failure: bind repo root anyway, mark `workspace_kind = mixed` or `unknown`, and reduce confidence.

## Open Questions

- Whether v0 should support more than one named analysis profile.
- Whether `cache/` needs stronger schema guarantees or can stay implementation-defined.
- Whether later versions should support multiple active bundles per repo beyond a single current pointer.
