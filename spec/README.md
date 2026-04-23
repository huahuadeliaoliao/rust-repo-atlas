# rust-repo-atlas Specs

This directory holds the v0 design specs for `rust-repo-atlas`.

Read in this order:

1. `runtime-state.md`
   Defines the runtime model, repo-local storage policy, minimal persistent state, and harness command surface.
2. `artifact-schema.md`
   Defines the atlas bundle layout, structured outputs, rendered reading surfaces, and evidence model.
3. `benchmark-protocol.md`
   Defines how to evaluate whether atlas artifacts measurably improve agent understanding of Rust repositories.
4. `authoring-checklist.md`
   Defines the writing-time acceptance criteria for the other spec files.

v0 decisions already fixed:

- `rust-repo-atlas` is a Rust-first repo world-model runtime, not a task runtime.
- Derived state and artifacts default to `<repo_root>/.rust-repo-atlas/`.
- Default refresh behavior is `manual refresh + automatic stale detection`.
- Default version policy is `latest`, and `latest` includes prereleases.
- `burn` and `codex` are the first two validation repositories.

