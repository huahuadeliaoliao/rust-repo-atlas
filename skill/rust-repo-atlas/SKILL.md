---
name: rust-repo-atlas
description: Use when an agent needs to understand a large Rust repository or Rust-heavy mixed-language repository, maintain a repo-local atlas under .rust-repo-atlas, decide whether artifacts are fresh enough to reuse, and follow a Rust-first reading workflow grounded in structured evidence and task playbooks.
---

# Rust Repo Atlas

`rust-repo-atlas` is a Rust-first repo world-model skill backed by a repo-local harness runtime.

Use it when the user needs:

- fast and accurate orientation inside a Rust repository
- architecture and subsystem explanations grounded in code evidence
- help deciding where to read next for a Rust task
- a reusable repo-local atlas that can be refreshed later
- support for mixed-language repositories where Rust is the main analysis target

Do not use it as a substitute for source reading on risky changes. Atlas should narrow and structure the reading path, not eliminate direct verification.

## Harness posture

Treat this skill as a soft harness: it provides repo facts, freshness state,
confidence signals, evidence profiles, and optional playbooks. It should not
replace the agent's task-specific exploration strategy.

Prefer using atlas outputs as:

- a first-pass context sampler for large Rust repositories
- a freshness and drift instrument
- a map of likely subsystems, candidate roots, and evidence-backed claims
- a prompt to verify source when a claim only has manifest, doc, or heuristic support

Avoid treating atlas outputs as:

- an authoritative call graph
- the only valid read order
- a substitute for source verification before implementation changes
- a mandatory refresh policy when the task context says otherwise

## Default workflow

1. Check whether `<repo_root>/.rust-repo-atlas/state.json` exists.
2. If missing, bind the repository with the harness.
3. Inspect freshness before trusting existing artifacts.
4. Reuse a fresh atlas by reading:
   `overview.md` -> `repo-profile.json` -> `global-model.json`
5. For narrow questions, continue into:
   `flows.json` -> `playbooks.json` -> `evidence.json`
6. If the atlas is stale or missing and the task depends on current code structure, refresh it.
7. For ambiguous or high-risk changes, confirm important claims directly in source even if the atlas is fresh.

## Runtime commands

Use the controller:

```bash
python3 scripts/controller.py bind --repo-root /abs/repo
python3 scripts/controller.py inspect --repo-root /abs/repo
python3 scripts/controller.py refresh --repo-root /abs/repo
python3 scripts/controller.py drift --repo-root /abs/repo
python3 scripts/controller.py explain --repo-root /abs/repo
python3 scripts/controller.py validate --repo-root /abs/repo
python3 scripts/controller.py close --repo-root /abs/repo
```

## What the runtime stores

The harness stores repo-derived state locally under:

```text
<repo_root>/.rust-repo-atlas/
```

This includes:

- `state.json`
- `snapshots/<snapshot_id>/manifest.json`
- `bundles/<snapshot_id>/...`

## Reuse rules

- `fresh`: reuse by default
- `stale`: inspect drift, then decide whether to refresh
- `unknown`: refresh if the task is sensitive to current repo structure
- `partial`: good for orientation, not enough for deep relation claims

When `explain` returns multiple `recommended_actions`, read them as decision
inputs rather than commands. Stronger models should freely choose a different
path when task context or direct source evidence warrants it.

## References

Read these when needed:

- `references/runtime-state.md`
- `references/artifact-schema.md`
- `references/benchmark-protocol.md`
- `references/authoring-checklist.md`
