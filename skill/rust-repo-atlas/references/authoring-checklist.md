# Spec Authoring Checklist

This checklist defines the minimum writing-time acceptance criteria for the v0 spec set.

## Global Checklist

Every spec file must include:

- a short `Purpose` section
- a short `Design Principles` section
- an explicit boundary or `Non-Goals` section
- at least one concrete JSON example
- at least one table
- at least one structure block, directory tree, or protocol block
- at least one example tied to `burn` or `codex`
- at least one short `Open Questions` section

Every spec file must avoid:

- hand-wavy prose without concrete fields or rules
- implementation promises that the v0 design has not yet fixed
- mixing normative requirements with optional examples
- hidden assumptions about global storage under `~/.codex`

Cross-file consistency checks:

- `repo_root`, `atlas_root`, `snapshot_id`, `freshness`, `bundle`, `playbook`, `evidence`, `version_policy`, and `release_channel` mean the same thing everywhere
- `latest` includes prereleases everywhere
- repo-local storage is the default everywhere
- `fresh`, `stale`, and `unknown` are defined consistently everywhere

## `runtime-state.md` Checklist

Must contain sections for:

- `Purpose`
- `Design Principles`
- `Runtime Scope`
- `Storage Model`
- `Directory Layout`
- `State Model`
- `State Schema`
- `Field Reference`
- `Snapshot Identity Rules`
- `Freshness Semantics`
- `Refresh Semantics`
- `Command Surface`
- `Error and Recovery Model`
- `Non-Goals`
- `Open Questions`

Must include:

- one full `state.json` example
- one repo-local directory tree
- one Git snapshot example
- one non-Git snapshot example
- one freshness example

Must define field tables for:

- `runtime`
- `binding`
- `snapshot`
- `freshness`
- `artifacts`
- `policy`
- `agent_hints`

Every field table should include:

- `Field`
- `Required`
- `Type`
- `Meaning`
- `Example`
- `Why Needed`

## `artifact-schema.md` Checklist

Must contain sections for:

- `Purpose`
- `Design Principles`
- `Bundle Placement`
- `Bundle Layout`
- `Artifact Taxonomy`
- `Agent Consumption Order`
- `Common Metadata Header`
- schema sections for each primary JSON artifact
- `Rendered Views`
- `Coverage Levels`
- `Shareability and Portability`
- `Validation Rules`
- `Open Questions`

Must include:

- one bundle directory tree
- one common JSON header example
- one claim example
- one flow example
- one playbook example
- one evidence example
- one diagnostics example

Must define field tables for:

- common metadata
- `repo-profile.json`
- `global-model.json`
- `flows.json`
- `playbooks.json`
- `evidence.json`
- `diagnostics.json`

Every field table should include:

- `Field`
- `Required`
- `Type`
- `Description`
- `Example`
- `Consumer`

## `benchmark-protocol.md` Checklist

Must contain sections for:

- `Purpose`
- `Evaluation Philosophy`
- `Repositories Under Test`
- `Snapshot Discipline`
- `Benchmark Conditions`
- `Task Taxonomy`
- `Task Format`
- `Gold Annotation Guidelines`
- `Metrics`
- `Scoring`
- `Run Protocol`
- `Artifact-Aware Tasks`
- `Success Criteria`
- `Threats to Validity`
- `Versioning`
- `Open Questions`

Must include:

- one task JSON example
- one rubric example
- one condition matrix or equivalent table
- one run protocol block
- at least one task example grounded in `burn`
- at least one task example grounded in `codex`

Must define tables for:

- repo archetypes
- benchmark conditions
- task taxonomy
- metrics

Recommended scoring columns:

- `Metric`
- `Definition`
- `Why It Matters`
- `How Measured`

## Final Acceptance Gate

Before calling the spec set complete:

- all four files exist under `spec/`
- each file has at least one valid JSON block
- the repo-local storage policy is stated explicitly in both runtime and artifact specs
- prerelease handling is stated explicitly in runtime and benchmark specs
- `burn` and `codex` both appear somewhere in the spec set
- no spec relies on `~/.codex` for repo-derived artifacts

