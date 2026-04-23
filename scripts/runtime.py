#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from state import (
    ARTIFACT_SCHEMA_VERSION,
    TOOL_VERSION,
    atlas_root,
    bundles_root,
    empty_state,
    ensure_layout,
    load_state,
    now_iso,
    read_json,
    save_state,
    snapshots_root,
    stable_repo_id,
    write_json,
)


IGNORE_DIRS = {".git", ".rust-repo-atlas", "target", "node_modules", ".venv", "venv"}
FINGERPRINT_FILENAMES = {
    "Cargo.lock",
    "Cargo.toml",
    "README",
    "README.md",
    "rust-toolchain",
    "rust-toolchain.toml",
}
FINGERPRINT_SUFFIXES = {
    ".lock",
    ".markdown",
    ".md",
    ".rs",
    ".toml",
    ".yaml",
    ".yml",
}
NON_RUST_MARKERS = {
    "package.json": "javascript",
    "pnpm-workspace.yaml": "javascript",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "go.mod": "go",
}


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.rstrip("\n")


def _run_json(cmd: list[str], cwd: Path) -> dict[str, Any] | None:
    code, out = _run(cmd, cwd)
    if code != 0 or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _is_git_repo(repo_root: Path) -> bool:
    code, _ = _run(["git", "rev-parse", "--show-toplevel"], repo_root)
    return code == 0


def _git_toplevel(repo_root: Path) -> Path:
    code, out = _run(["git", "rev-parse", "--show-toplevel"], repo_root)
    if code != 0 or not out:
        raise RuntimeError("not a git repository")
    return Path(out).resolve()


def _iter_cargo_tomls(repo_root: Path) -> list[Path]:
    cargo_files: list[Path] = []
    for path in repo_root.rglob("Cargo.toml"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        cargo_files.append(path)
    return sorted(cargo_files)


def _has_workspace_manifest(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return "[workspace]" in text


def _common_ancestor(paths: list[Path]) -> Path:
    if not paths:
        raise ValueError("paths must not be empty")
    common = paths[0]
    for path in paths[1:]:
        while common != path and common not in path.parents:
            if common.parent == common:
                break
            common = common.parent
    return common


def _detect_workspace_root(repo_root: Path) -> tuple[Path, str]:
    cargo_files = _iter_cargo_tomls(repo_root)
    if not cargo_files:
        return repo_root, "mixed"

    workspace_candidates = [path.parent for path in cargo_files if _has_workspace_manifest(path)]
    if workspace_candidates:
        workspace_root = min(workspace_candidates, key=lambda p: len(p.parts))
        if workspace_root == repo_root:
            return workspace_root, "cargo-workspace"
        return workspace_root, "mixed"

    root_manifest = repo_root / "Cargo.toml"
    if root_manifest.exists():
        return repo_root, "single-crate"

    # Without an explicit workspace, pick a concrete Cargo package root for tooling.
    scores: dict[Path, int] = {}
    for cargo in cargo_files:
        parent = cargo.parent
        scores[parent] = scores.get(parent, 0) + 1
    best = max(scores, key=lambda p: (scores[p], -len(p.parts)))
    if best == repo_root:
        return best, "single-crate"
    return best, "mixed"


def _detect_rust_focus_root(repo_root: Path, workspace_root: Path) -> Path:
    cargo_files = _iter_cargo_tomls(repo_root)
    if not cargo_files:
        return workspace_root
    common = _common_ancestor([path.parent for path in cargo_files])
    if common != repo_root and not (common / "Cargo.toml").exists():
        return common
    return workspace_root


def _candidate_score(
    path: Path,
    repo_root: Path,
    cargo_files: list[Path],
    workspace_root: Path,
    rust_focus_root: Path,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if path == rust_focus_root:
        score += 100.0
        reasons.append("selected Rust focus root")
    if path == workspace_root:
        score += 60.0
        reasons.append("selected workspace root")
    manifest = path / "Cargo.toml"
    if manifest.exists():
        score += 20.0
        reasons.append("has Cargo.toml")
        if _has_workspace_manifest(manifest):
            score += 60.0
            reasons.append("declares [workspace]")
    owned = [cargo for cargo in cargo_files if cargo == manifest or path in cargo.parents]
    if owned:
        score += min(len(owned) * 4.0, 40.0)
        reasons.append(f"contains {len(owned)} Cargo manifests")
    if path == repo_root:
        score += 5.0
        reasons.append("repository root")
    distance = len(path.relative_to(repo_root).parts) if path != repo_root else 0
    score -= distance * 0.5
    return score, reasons


def _rust_focus_candidates(repo_root: Path, workspace_root: Path, rust_focus_root: Path) -> list[dict[str, Any]]:
    cargo_files = _iter_cargo_tomls(repo_root)
    candidates: set[Path] = {repo_root, workspace_root, rust_focus_root}
    if cargo_files:
        candidates.add(_common_ancestor([path.parent for path in cargo_files]))
        for cargo in cargo_files:
            candidates.add(cargo.parent)
            parent = cargo.parent.parent
            try:
                parent.relative_to(repo_root)
            except ValueError:
                continue
            candidates.add(parent)
    ranked: list[dict[str, Any]] = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            rel = "." if path == repo_root else str(path.relative_to(repo_root))
        except ValueError:
            rel = str(path)
        score, reasons = _candidate_score(path, repo_root, cargo_files, workspace_root, rust_focus_root)
        ranked.append(
            {
                "path": str(path.resolve()),
                "relative_path": rel,
                "score": round(score, 3),
                "reasons": reasons,
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["relative_path"]))
    return ranked[:8]


def _detect_language_context(repo_root: Path) -> list[str]:
    found: list[str] = []
    for marker, language in NON_RUST_MARKERS.items():
        if (repo_root / marker).exists() and language not in found:
            found.append(language)
    return found


def _release_channel_from_tag(tag: str) -> str:
    tag_lower = tag.lower()
    if not tag:
        return "unknown"
    if any(marker in tag_lower for marker in ["alpha", "beta", "rc", "pre"]):
        return "prerelease"
    return "stable"


def _is_fingerprint_relevant(rel_path: str) -> bool:
    path = Path(rel_path)
    if any(part in IGNORE_DIRS for part in path.parts):
        return False
    if path.name in FINGERPRINT_FILENAMES:
        return True
    return path.suffix in FINGERPRINT_SUFFIXES


def _git_status_path(status_line: str) -> str:
    if len(status_line) > 2 and status_line[2] == " ":
        raw = status_line[3:]
    elif len(status_line) > 1 and status_line[1] == " ":
        raw = status_line[2:]
    else:
        raw = status_line[3:] if len(status_line) > 3 else ""
    if " -> " in raw:
        raw = raw.split(" -> ", 1)[1]
    return raw.strip().strip('"')


def _git_worktree_fingerprint(repo_root: Path, status_output: str) -> tuple[str, list[str]]:
    hasher = hashlib.sha256()
    scope: list[str] = []
    for line in sorted(item for item in status_output.splitlines() if item.strip()):
        rel = _git_status_path(line)
        if not rel or not _is_fingerprint_relevant(rel):
            continue
        scope.append(rel)
        hasher.update(line.encode("utf-8"))
        path = repo_root / rel
        if path.exists() and path.is_file():
            hasher.update(path.read_bytes())
        else:
            hasher.update(b"<missing>")
    if not scope:
        return "", []
    return hasher.hexdigest(), scope


def _git_snapshot(repo_root: Path, version_policy: str) -> dict[str, Any]:
    commit = _run(["git", "rev-parse", "HEAD"], repo_root)[1]
    tag = _run(["git", "describe", "--tags", "--exact-match"], repo_root)[1]
    branch = _run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], repo_root)[1]
    dirty_cmd = [
        "git",
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude).rust-repo-atlas",
        ":(exclude).rust-repo-atlas/**",
    ]
    dirty_status = _run(dirty_cmd, repo_root)[1]
    dirty = bool(dirty_status)
    content_fingerprint, fingerprint_scope = _git_worktree_fingerprint(repo_root, dirty_status) if dirty else ("", [])
    resolved_ref = "tag" if tag else ("branch" if branch else "detached")
    identity = f"git:{commit}:{'dirty' if dirty else 'clean'}"
    return {
        "identity": identity,
        "resolved_ref": resolved_ref,
        "commit": commit,
        "tag": tag,
        "dirty": dirty,
        "fingerprint": "",
        "content_fingerprint": content_fingerprint,
        "fingerprint_scope": fingerprint_scope,
        "release_channel": _release_channel_from_tag(tag),
        "version_policy": version_policy,
        "observed_at": now_iso(),
    }


def _filesystem_fingerprint(repo_root: Path) -> str:
    hasher = hashlib.sha256()
    relevant = [path for path in repo_root.rglob("*") if path.is_file()]
    filtered = [
        path
        for path in relevant
        if _is_fingerprint_relevant(str(path.relative_to(repo_root)))
        and not any(part in IGNORE_DIRS for part in path.parts)
    ]
    for path in sorted(filtered):
        rel = str(path.relative_to(repo_root))
        hasher.update(rel.encode("utf-8"))
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _filesystem_snapshot(repo_root: Path, version_policy: str) -> dict[str, Any]:
    fingerprint = _filesystem_fingerprint(repo_root)
    identity = f"fs:{fingerprint}"
    return {
        "identity": identity,
        "resolved_ref": "none",
        "commit": "",
        "tag": "",
        "dirty": False,
        "fingerprint": fingerprint,
        "content_fingerprint": fingerprint,
        "fingerprint_scope": ["tracked filesystem files"],
        "release_channel": "none",
        "version_policy": version_policy,
        "observed_at": now_iso(),
    }


def _bundle_exists(bundle_path: str, manifest_path: str) -> bool:
    if not bundle_path or not manifest_path:
        return False
    return Path(bundle_path).exists() and Path(manifest_path).exists()


def _freshness(snapshot: dict[str, Any], state: dict[str, Any]) -> tuple[str, list[str], str]:
    current_snapshot_id = state["artifacts"].get("current_snapshot_id", "")
    bundle_path = state["artifacts"].get("current_bundle_path", "")
    manifest_path = state["artifacts"].get("current_manifest_path", "")
    if not current_snapshot_id:
        return "unknown", ["bundle_missing"], snapshot["identity"]
    if not _bundle_exists(bundle_path, manifest_path):
        return "stale", ["bundle_missing"], snapshot["identity"]
    version_reasons: list[str] = []
    artifacts = state.get("artifacts", {})
    if artifacts.get("tool_version") != TOOL_VERSION:
        version_reasons.append("tool_version_changed")
    if artifacts.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        version_reasons.append("artifact_schema_changed")
    if version_reasons:
        return "stale", version_reasons, snapshot["identity"]
    if current_snapshot_id != snapshot["identity"]:
        reasons: list[str] = []
        previous_snapshot = state.get("snapshot", {})
        if previous_snapshot.get("commit") != snapshot.get("commit"):
            reasons.append("head_changed")
        if bool(previous_snapshot.get("dirty")) != bool(snapshot.get("dirty")):
            reasons.append("dirty_changed")
        if not reasons:
            reasons.append("snapshot_changed")
        return "stale", reasons, snapshot["identity"]
    previous_snapshot = state.get("snapshot", {})
    if previous_snapshot.get("content_fingerprint", "") != snapshot.get("content_fingerprint", ""):
        return "stale", ["content_fingerprint_changed"], snapshot["identity"]
    return "fresh", [], snapshot["identity"]


def _artifact_header(repo_root: Path, snapshot_id: str) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "repo_root": str(repo_root.resolve()),
        "snapshot_id": snapshot_id,
        "generated_at": now_iso(),
        "generator": {
            "name": "rust-repo-atlas",
            "version": TOOL_VERSION,
        },
    }


def _coverage_metadata(coverage_level: str) -> dict[str, Any]:
    if coverage_level == "profile":
        return {
            "level": "profile",
            "confidence": "orientation-only",
            "complete_for": ["orientation", "workspace-localization", "basic crate dependency graph"],
            "not_complete_for": ["symbol-level relation tracing", "implementation planning"],
            "missing_capabilities": ["symbol_relation_evidence", "api_surface"],
        }
    if coverage_level == "deep":
        return {
            "level": "deep",
            "confidence": "core-plus",
            "complete_for": [
                "orientation",
                "workspace-localization",
                "subsystem navigation",
                "crate-level impact analysis",
                "change-planning context",
            ],
            "not_complete_for": ["unverified symbol-level implementation changes"],
            "missing_capabilities": ["api-level analyzers"],
        }
    return {
        "level": "core",
        "confidence": "navigation",
        "complete_for": [
            "orientation",
            "workspace-localization",
            "subsystem navigation",
            "crate-level impact analysis",
            "change-planning context",
        ],
        "not_complete_for": ["unverified symbol-level implementation changes"],
        "missing_capabilities": ["full call graph", "api-level analyzers", "symbol-level relation extraction"],
    }


def _agent_hints(freshness_status: str, reasons: list[str], coverage_level: str = "profile") -> dict[str, Any]:
    if freshness_status == "fresh":
        actions = [
            {
                "action": "reuse_for_orientation",
                "confidence": "high",
                "why": "Current bundle matches the current snapshot.",
            },
            {
                "action": "verify_source_for_symbol_relations",
                "confidence": "medium",
                "why": "Atlas claims are navigation context; source remains authoritative for implementation-risk decisions.",
            },
        ]
        if coverage_level == "profile":
            actions.append(
                {
                    "action": "refresh_for_deeper_relation_context",
                    "confidence": "low",
                    "why": "Profile coverage is designed for orientation and workspace localization.",
                }
            )
        return {
            "recommended_action": "reuse",
            "recommended_actions": actions,
            "why": "Current bundle matches the current snapshot.",
        }
    if freshness_status == "stale":
        return {
            "recommended_action": "inspect_drift",
            "recommended_actions": [
                {
                    "action": "reuse_only_as_background",
                    "confidence": "medium",
                    "why": f"Atlas is stale: {', '.join(reasons) if reasons else 'snapshot mismatch'}.",
                },
                {
                    "action": "refresh_before_relying_on_claims",
                    "confidence": "high",
                    "why": "A stale bundle may no longer match source facts.",
                },
            ],
            "why": "Current bundle does not fully match the current snapshot.",
        }
    return {
        "recommended_action": "bind",
        "recommended_actions": [
            {
                "action": "refresh_to_create_atlas",
                "confidence": "high",
                "why": "No reusable atlas bundle is available.",
            }
        ],
        "why": "No atlas bundle exists yet.",
    }


def _relpath(path: str | Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _cargo_metadata(workspace_root: Path) -> dict[str, Any] | None:
    return _run_json(["cargo", "metadata", "--format-version", "1", "--no-deps"], workspace_root)


def _package_kind(package: dict[str, Any]) -> str:
    target_kinds: set[str] = set()
    for target in package.get("targets", []):
        target_kinds.update(target.get("kind", []))
    if "bin" in target_kinds and "lib" in target_kinds:
        return "mixed"
    if "bin" in target_kinds:
        return "binary"
    if "lib" in target_kinds:
        return "library"
    if any(kind.endswith("test") or kind == "test" for kind in target_kinds):
        return "test-support"
    return "other"


def _major_crates(metadata: dict[str, Any], workspace_root: Path) -> list[dict[str, Any]]:
    packages = metadata.get("packages", [])
    members = set(metadata.get("workspace_members", []))
    crates: list[dict[str, Any]] = []
    for package in packages:
        if package.get("id") not in members:
            continue
        manifest_path = package.get("manifest_path", "")
        crates.append(
            {
                "name": package.get("name", ""),
                "version": package.get("version", ""),
                "kind": _package_kind(package),
                "manifest_path": manifest_path,
                "relative_manifest_path": _relpath(manifest_path, workspace_root),
                "target_count": len(package.get("targets", [])),
            }
        )
    crates.sort(key=lambda item: (item["relative_manifest_path"], item["name"]))
    return crates


def _entrypoints(metadata: dict[str, Any], workspace_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    members = set(metadata.get("workspace_members", []))
    for package in metadata.get("packages", []):
        if package.get("id") not in members:
            continue
        for target in package.get("targets", []):
            kinds = target.get("kind", [])
            if "bin" in kinds or "lib" in kinds:
                entries.append(
                    {
                        "package": package.get("name", ""),
                        "target_name": target.get("name", ""),
                        "kind": "bin" if "bin" in kinds else "lib",
                        "relative_src_path": _relpath(target.get("src_path", ""), workspace_root),
                    }
                )
    entries.sort(key=lambda item: (item["kind"], item["relative_src_path"]))
    return entries[:20]


def _workspace_package_lookup(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    members = set(metadata.get("workspace_members", []))
    return {
        package.get("name", ""): package
        for package in metadata.get("packages", [])
        if package.get("id") in members and package.get("name")
    }


def _subsystem_by_crate(subsystems: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for subsystem in subsystems:
        for crate_name in subsystem.get("crate_names", []):
            index.setdefault(crate_name, subsystem.get("name", ""))
    return index


def _direct_dependency_maps(edges: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    direct: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    for edge in edges:
        source = edge["from"]
        target = edge["to"]
        direct.setdefault(source, set()).add(target)
        reverse.setdefault(target, set()).add(source)
        direct.setdefault(target, set())
        reverse.setdefault(source, set())
    return (
        {name: sorted(values) for name, values in direct.items()},
        {name: sorted(values) for name, values in reverse.items()},
    )


def _transitive_closure(seed: str, graph: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    queue = list(graph.get(seed, []))
    while queue:
        item = queue.pop(0)
        if item in seen or item == seed:
            continue
        seen.add(item)
        queue.extend(graph.get(item, []))
    return sorted(seen)


def _build_crate_graph(
    *,
    metadata: dict[str, Any] | None,
    workspace_root: Path,
    crates: list[dict[str, Any]],
    subsystems: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    crate_names = {crate["name"] for crate in crates}
    crate_to_subsystem = _subsystem_by_crate(subsystems)
    nodes = [
        {
            "id": crate["name"],
            "name": crate["name"],
            "kind": crate["kind"],
            "relative_manifest_path": crate["relative_manifest_path"],
            "subsystem": crate_to_subsystem.get(crate["name"], ""),
        }
        for crate in crates
    ]
    edges: list[dict[str, Any]] = []
    if metadata is not None:
        package_by_name = _workspace_package_lookup(metadata)
        for package_name, package in package_by_name.items():
            for dep in package.get("dependencies", []):
                dep_name = dep.get("name", "")
                if dep_name not in crate_names:
                    continue
                dep_path = dep.get("path")
                if dep_path:
                    try:
                        Path(dep_path).resolve().relative_to(workspace_root.resolve())
                    except ValueError:
                        continue
                dep_kind = dep.get("kind") or "normal"
                edges.append(
                    {
                        "from": package_name,
                        "to": dep_name,
                        "kind": dep_kind,
                        "optional": bool(dep.get("optional", False)),
                        "target": dep.get("target") or "",
                        "features": sorted(dep.get("features", [])),
                        "reason": "workspace dependency",
                    }
                )
    edges.sort(key=lambda item: (item["from"], item["to"], item["kind"], item["target"]))
    direct_dependencies, reverse_dependencies = _direct_dependency_maps(edges)
    for crate_name in sorted(crate_names):
        direct_dependencies.setdefault(crate_name, [])
        reverse_dependencies.setdefault(crate_name, [])
    transitive_dependents = {
        crate_name: _transitive_closure(crate_name, reverse_dependencies)
        for crate_name in sorted(crate_names)
    }
    transitive_dependencies = {
        crate_name: _transitive_closure(crate_name, direct_dependencies)
        for crate_name in sorted(crate_names)
    }
    return {
        "coverage": coverage,
        "nodes": nodes,
        "edges": edges,
        "direct_dependencies": direct_dependencies,
        "reverse_dependencies": reverse_dependencies,
        "transitive_dependencies": transitive_dependencies,
        "transitive_dependents": transitive_dependents,
        "graph_notes": [
            "Edges come from Cargo workspace dependency metadata.",
            "Use reverse dependencies as candidate impact surfaces, not as a complete call graph.",
        ],
    }


def _pair_key(lhs: str, rhs: str) -> tuple[str, str]:
    return tuple(sorted((lhs, rhs)))


def _build_coupling_map(
    *,
    crate_graph: dict[str, Any],
    subsystems: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    crate_to_subsystem = _subsystem_by_crate(subsystems)
    pair_reasons: dict[tuple[str, str], list[str]] = {}
    pair_scores: dict[tuple[str, str], float] = {}
    for edge in crate_graph.get("edges", []):
        key = _pair_key(edge["from"], edge["to"])
        pair_scores[key] = pair_scores.get(key, 0.0) + (3.0 if edge["kind"] == "normal" else 2.0)
        pair_reasons.setdefault(key, []).append(f"{edge['from']} depends on {edge['to']} ({edge['kind']})")
    for subsystem in subsystems:
        members = [name for name in subsystem.get("crate_names", []) if name in crate_graph.get("direct_dependencies", {})]
        for index, lhs in enumerate(members):
            for rhs in members[index + 1 :]:
                key = _pair_key(lhs, rhs)
                pair_scores[key] = pair_scores.get(key, 0.0) + 1.0
                pair_reasons.setdefault(key, []).append(f"both are in subsystem {subsystem['name']}")
    strong_pairs = []
    for (lhs, rhs), score in sorted(pair_scores.items(), key=lambda item: (-item[1], item[0])):
        reasons = pair_reasons.get((lhs, rhs), [])
        strong_pairs.append(
            {
                "lhs": lhs,
                "rhs": rhs,
                "score": round(score, 3),
                "confidence": "high" if score >= 3.0 and any("depends on" in reason for reason in reasons) else "medium",
                "reasons": reasons[:6],
                "agent_note": "Candidate coupling edge; verify source and tests before implementation changes.",
            }
        )
    clusters = []
    direct_dependencies = crate_graph.get("direct_dependencies", {})
    for subsystem in subsystems:
        members = [name for name in subsystem.get("crate_names", []) if name in direct_dependencies]
        internal_edges = [
            edge
            for edge in crate_graph.get("edges", [])
            if edge["from"] in members and edge["to"] in members
        ]
        outgoing_edges = [
            edge
            for edge in crate_graph.get("edges", [])
            if edge["from"] in members and edge["to"] not in members
        ]
        incoming_edges = [
            edge
            for edge in crate_graph.get("edges", [])
            if edge["from"] not in members and edge["to"] in members
        ]
        if not members:
            continue
        clusters.append(
            {
                "id": f"cluster.{_safe_id(subsystem['name'])}",
                "name": subsystem["name"],
                "members": members,
                "confidence": "high" if internal_edges or len(members) == 1 else "medium",
                "coupling_reasons": [
                    "subsystem grouping",
                    *(
                        ["internal Cargo dependency edges"]
                        if internal_edges
                        else ["no internal Cargo dependency edge detected"]
                    ),
                ],
                "internal_edge_count": len(internal_edges),
                "incoming_edge_count": len(incoming_edges),
                "outgoing_edge_count": len(outgoing_edges),
                "incoming_crates": sorted({edge["from"] for edge in incoming_edges}),
                "outgoing_crates": sorted({edge["to"] for edge in outgoing_edges}),
                "agent_note": "Cluster is a navigation hint, not an ownership boundary.",
            }
        )
    return {
        "coverage": coverage,
        "clusters": clusters,
        "strong_pairs": strong_pairs[:80],
        "crate_to_subsystem": crate_to_subsystem,
        "map_notes": [
            "Coupling scores combine real Cargo dependency edges with soft subsystem grouping.",
            "Use this map to choose what to inspect next; source and tests remain authoritative.",
        ],
    }


def _crate_focus_path(crate_name: str, crate_index: dict[str, dict[str, Any]]) -> str:
    crate = crate_index.get(crate_name)
    if not crate:
        return ""
    return _crate_dir(crate)


def _build_impact_index(
    *,
    crate_graph: dict[str, Any],
    coupling_map: dict[str, Any],
    crates: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    crate_index = _crate_index(crates)
    reverse_dependencies = crate_graph.get("reverse_dependencies", {})
    transitive_dependents = crate_graph.get("transitive_dependents", {})
    direct_dependencies = crate_graph.get("direct_dependencies", {})
    strong_neighbors: dict[str, list[dict[str, Any]]] = {}
    for pair in coupling_map.get("strong_pairs", []):
        strong_neighbors.setdefault(pair["lhs"], []).append({"crate": pair["rhs"], "score": pair["score"], "reasons": pair["reasons"]})
        strong_neighbors.setdefault(pair["rhs"], []).append({"crate": pair["lhs"], "score": pair["score"], "reasons": pair["reasons"]})
    seeds = []
    for crate in crates:
        name = crate["name"]
        direct = reverse_dependencies.get(name, [])
        transitive = [item for item in transitive_dependents.get(name, []) if item not in direct]
        dependencies = direct_dependencies.get(name, [])
        neighbors = sorted(strong_neighbors.get(name, []), key=lambda item: (-item["score"], item["crate"]))[:8]
        verify_first = [
            path
            for path in [
                _crate_focus_path(name, crate_index),
                *[_crate_focus_path(item, crate_index) for item in direct[:6]],
            ]
            if path
        ]
        likely_affected = [
            {"target": item, "reason": "direct reverse dependency", "confidence": "high"}
            for item in direct
        ] + [
            {"target": item, "reason": "transitive reverse dependency", "confidence": "medium"}
            for item in transitive[:12]
        ]
        seeds.append(
            {
                "target": name,
                "change_types": ["public-api", "trait-or-type-contract", "feature-or-dependency-change"],
                "likely_affected": likely_affected,
                "direct_dependencies": dependencies,
                "coupled_neighbors": neighbors,
                "verify_first": verify_first,
                "impact_radius": {
                    "direct_reverse_dependencies": len(direct),
                    "transitive_reverse_dependencies": len(transitive),
                    "strong_coupling_neighbors": len(neighbors),
                },
                "agent_note": "Candidate impact surface derived from Cargo dependencies and coupling hints; verify source before editing.",
            }
        )
    seeds.sort(
        key=lambda item: (
            -item["impact_radius"]["direct_reverse_dependencies"],
            -item["impact_radius"]["transitive_reverse_dependencies"],
            item["target"],
        )
    )
    return {
        "coverage": coverage,
        "seeds": seeds,
        "index_notes": [
            "Likely affected crates are reverse dependencies, not guaranteed runtime callers.",
            "For API or trait changes, inspect direct reverse dependencies before transitive dependents.",
        ],
    }


def _infer_repo_archetype(repo_name: str, workspace_kind: str, language_context: list[str], crate_count: int) -> str:
    if repo_name == "burn":
        return "framework-workspace"
    if repo_name == "codex":
        return "mixed-product"
    if workspace_kind == "cargo-workspace" and crate_count > 10:
        return "large-rust-workspace"
    if workspace_kind == "single-crate":
        return "single-crate"
    if language_context:
        return "mixed-product"
    return "rust-workspace"


def _detect_repo_family(repo_name: str, crates: list[dict[str, Any]], binding: dict[str, Any]) -> dict[str, Any]:
    crate_names = {crate["name"] for crate in crates}
    burn_signals = sorted(crate_names & {"burn", "burn-backend", "burn-autodiff", "burn-fusion", "burn-train"})
    codex_signals = sorted(crate_names & {"codex-cli", "codex-core", "codex-exec", "codex-tui", "codex-protocol"})
    if repo_name == "burn" or {"burn-backend", "burn-autodiff"}.issubset(crate_names):
        confidence = "high" if len(burn_signals) >= 3 else "medium"
        signals = burn_signals + (["repo-name:burn"] if repo_name == "burn" else [])
        return {"name": "burn", "confidence": confidence, "matched_signals": signals}
    if repo_name == "codex" or {"codex-core", "codex-cli"}.issubset(crate_names):
        confidence = "high" if len(codex_signals) >= 3 else "medium"
        signals = codex_signals + (["repo-name:codex"] if repo_name == "codex" else [])
        if binding.get("repo_root") != binding.get("rust_focus_root"):
            signals.append("mixed-rust-focus-root")
        return {"name": "codex", "confidence": confidence, "matched_signals": signals}
    return {"name": "generic", "confidence": "low", "matched_signals": []}


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "item"


def _locator(relative_path: str, anchor: str = "") -> str:
    if not anchor:
        return relative_path
    return f"{relative_path}#{_safe_id(anchor)}"


def _read_text_if_exists(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _readme_summary(path: Path) -> str:
    text = _read_text_if_exists(path)
    if not text:
        return ""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith(("#", "<", "![", "[![", "|", "```", "---")):
            if lines:
                break
            continue
        if line.startswith(("- ", "* ")):
            if lines:
                break
            continue
        lines.append(line)
        if len(" ".join(lines)) >= 240:
            break
    return " ".join(lines)[:260].strip()


def _default_evidence_assessment(kind: str, source: str, path: Path) -> tuple[str, str]:
    if source == "doc":
        return "doc", "medium"
    if source == "cargo-metadata":
        return "manifest", "medium"
    if source == "manual" and path.name == "Cargo.toml":
        return "manifest", "high"
    if kind == "query":
        return "query", "high"
    return "heuristic", "low"


def _append_evidence(
    evidence_items: list[dict[str, Any]],
    seen_ids: set[str],
    *,
    evidence_id: str,
    kind: str,
    path: Path,
    snapshot_id: str,
    symbol: str = "",
    locator: str = "",
    source: str = "manual",
    evidence_type: str = "",
    strength: str = "",
) -> str:
    if not evidence_id:
        return ""
    if evidence_id in seen_ids:
        return evidence_id
    if kind == "file" and not path.exists():
        return ""
    inferred_type, inferred_strength = _default_evidence_assessment(kind, source, path)
    evidence_items.append(
        {
            "id": evidence_id,
            "kind": kind,
            "evidence_type": evidence_type or inferred_type,
            "strength": strength or inferred_strength,
            "path": str(path.resolve()),
            "symbol": symbol,
            "locator": locator,
            "source": source,
            "snapshot_id": snapshot_id,
        }
    )
    seen_ids.add(evidence_id)
    return evidence_id


def _add_doc_evidence(
    evidence_items: list[dict[str, Any]],
    seen_ids: set[str],
    *,
    repo_root: Path,
    path: Path,
    snapshot_id: str,
    evidence_id: str,
    anchor: str = "",
) -> str:
    relative_path = _relpath(path, repo_root)
    return _append_evidence(
        evidence_items,
        seen_ids,
        evidence_id=evidence_id,
        kind="file",
        path=path,
        snapshot_id=snapshot_id,
        locator=_locator(relative_path, anchor),
        source="doc",
        evidence_type="doc",
        strength="medium",
    )


def _add_crate_evidence(
    evidence_items: list[dict[str, Any]],
    seen_ids: set[str],
    *,
    repo_root: Path,
    workspace_root: Path,
    snapshot_id: str,
    crate: dict[str, Any],
) -> str:
    manifest_path = workspace_root / crate["relative_manifest_path"]
    return _append_evidence(
        evidence_items,
        seen_ids,
        evidence_id=f"ev.crate.{crate['name']}",
        kind="file",
        path=manifest_path,
        snapshot_id=snapshot_id,
        symbol=crate["name"],
        locator=_relpath(manifest_path, repo_root),
        source="cargo-metadata",
        evidence_type="manifest",
        strength="medium",
    )


def _claim_evidence_profile(claim: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    strengths = {"high": 3, "medium": 2, "low": 1}
    ids = [item for item in claim.get("evidence_ids", []) if item]
    evidence = [evidence_by_id[item] for item in ids if item in evidence_by_id]
    types = sorted({item.get("evidence_type", "unknown") for item in evidence})
    strength_values = [item.get("strength", "low") for item in evidence]
    weakest = min(strength_values, key=lambda value: strengths.get(value, 0)) if strength_values else "none"
    profile = {
        "evidence_types": types,
        "weakest_strength": weakest,
        "support_count": len(evidence),
        "missing_evidence_ids": [item for item in ids if item not in evidence_by_id],
    }
    if claim.get("kind") in {"architecture", "boundary"} and not any(item in types for item in ("symbol", "relation")):
        profile["agent_note"] = "Use as navigation context; verify source before relying on this as a symbol-level relation."
    return profile


def _annotate_claim_support(claims: list[dict[str, Any]], evidence_items: list[dict[str, Any]]) -> None:
    evidence_by_id = {item["id"]: item for item in evidence_items if item.get("id")}
    for claim in claims:
        claim["evidence_profile"] = _claim_evidence_profile(claim, evidence_by_id)


def _crate_dir(crate: dict[str, Any]) -> str:
    return str(Path(crate["relative_manifest_path"]).parent)


def _crate_index(crates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {crate["name"]: crate for crate in crates}


def _make_subsystem(
    subsystem_id: str,
    name: str,
    summary: str,
    crate_names: list[str],
    crate_index: dict[str, dict[str, Any]],
    *,
    extra_paths: list[str] | None = None,
    root_scope: str = "workspace",
) -> dict[str, Any]:
    unique_crates: list[str] = []
    for crate_name in crate_names:
        if crate_name in crate_index and crate_name not in unique_crates:
            unique_crates.append(crate_name)
    focus_paths: list[str] = []
    for crate_name in unique_crates:
        rel_dir = _crate_dir(crate_index[crate_name])
        if rel_dir not in focus_paths:
            focus_paths.append(rel_dir)
    for path in extra_paths or []:
        if path not in focus_paths:
            focus_paths.append(path)
    return {
        "id": subsystem_id,
        "name": name,
        "crate_count": len(unique_crates),
        "crate_names": unique_crates,
        "representative_crates": unique_crates[:6],
        "focus_paths": focus_paths[:10],
        "summary": summary,
        "root_scope": root_scope,
    }


def _generic_subsystems(crates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    crate_index = _crate_index(crates)
    groups: dict[str, list[str]] = {}
    for crate in crates:
        rel = crate["relative_manifest_path"]
        parts = rel.split("/")
        bucket = parts[0] if len(parts) > 1 else crate["name"]
        groups.setdefault(bucket, []).append(crate["name"])
    subsystems = [
        _make_subsystem(
            f"subsystem.{_safe_id(bucket)}",
            bucket,
            f"Workspace members grouped under `{bucket}`.",
            crate_names,
            crate_index,
            extra_paths=[bucket],
        )
        for bucket, crate_names in groups.items()
    ]
    subsystems.sort(key=lambda item: (-item["crate_count"], item["name"]))
    return subsystems


def _burn_subsystems(crates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    crate_index = _crate_index(crates)
    examples = [crate["name"] for crate in crates if crate["relative_manifest_path"].startswith("examples/")]
    support = sorted(
        [
            crate["name"]
            for crate in crates
            if "test" in crate["name"] or crate["name"] in {"burn-tensor-testgen"}
        ]
    )
    assigned = set(examples + support + ["xtask"])
    core = [
        "burn",
        "burn-backend",
        "burn-core",
        "burn-tensor",
        "burn-nn",
        "burn-optim",
        "burn-derive",
        "burn-ir",
        "burn-std",
    ]
    decorators = ["burn-autodiff", "burn-fusion", "burn-cubecl-fusion", "burn-router", "burn-remote"]
    backend_impl = [
        "burn-candle",
        "burn-cpu",
        "burn-cubecl",
        "burn-cuda",
        "burn-flex",
        "burn-ndarray",
        "burn-rocm",
        "burn-tch",
        "burn-wgpu",
        "burn-collective",
        "burn-communication",
        "burn-dispatch",
    ]
    training = ["burn-train", "burn-dataset", "burn-store", "burn-vision", "burn-rl"]
    assigned.update(core + decorators + backend_impl + training)

    subsystems = [
        _make_subsystem(
            "subsystem.core-framework",
            "core-framework",
            "Facade, tensor, backend, and model-building crates that define Burn's Rust-first framework surface.",
            core,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.backend-decorators",
            "backend-decorators",
            "Decorator-style crates that add autodiff, fusion, routing, or remoting on top of concrete backends.",
            decorators,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.backend-implementations",
            "backend-implementations",
            "Concrete compute backends and dispatch layers for CPU, GPU, and external runtime integrations.",
            backend_impl,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.training-and-data",
            "training-and-data",
            "Training, datasets, persistence, and model-adjacent crates that support end-to-end ML workflows.",
            training,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.examples",
            "examples",
            "Executable examples used as end-to-end entrypoints and architecture anchors.",
            examples,
            crate_index,
            extra_paths=["examples"],
        ),
        _make_subsystem(
            "subsystem.test-support",
            "test-support",
            "Workspace crates focused on backend validation, no-std checks, and store-format compatibility tests.",
            support,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.tooling",
            "tooling",
            "Maintenance helpers and workspace automation.",
            ["xtask"],
            crate_index,
            extra_paths=["xtask"],
        ),
    ]
    leftovers = sorted(crate["name"] for crate in crates if crate["name"] not in assigned)
    if leftovers:
        subsystems.append(
            _make_subsystem(
                "subsystem.misc",
                "misc",
                "Workspace members that do not yet match a stronger Burn-specific bucket.",
                leftovers,
                crate_index,
            )
        )
    return [subsystem for subsystem in subsystems if subsystem["crate_count"] > 0]


def _codex_subsystems(crates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    crate_index = _crate_index(crates)
    entrypoints = ["codex-cli", "codex-tui", "codex-exec", "codex-core", "codex-config", "codex-state"]
    app_protocol = [
        "codex-app-server",
        "codex-app-server-client",
        "codex-app-server-protocol",
        "codex-app-server-test-client",
        "codex-protocol",
        "codex-api",
        "codex-client",
    ]
    mcp_integrations = [
        "codex-mcp",
        "codex-mcp-server",
        "codex-rmcp-client",
        "codex-connectors",
        "codex-backend-client",
        "codex-chatgpt",
        "codex-responses-api-proxy",
        "codex-realtime-webrtc",
    ]
    execution_sandbox = [
        "codex-shell-command",
        "codex-shell-escalation",
        "codex-sandboxing",
        "codex-exec-server",
        "codex-execpolicy",
        "codex-execpolicy-legacy",
        "codex-linux-sandbox",
        "codex-process-hardening",
        "codex-arg0",
        "codex-stdio-to-uds",
        "codex-terminal-detection",
        "codex-windows-sandbox",
    ]
    model_cloud = [
        "codex-model-provider",
        "codex-model-provider-info",
        "codex-models-manager",
        "codex-lmstudio",
        "codex-ollama",
        "codex-rollout",
        "codex-cloud-requirements",
        "codex-cloud-tasks",
        "codex-cloud-tasks-client",
        "codex-cloud-tasks-mock-client",
    ]
    config_skills = [
        "codex-skills",
        "codex-core-skills",
        "codex-core-plugins",
        "codex-plugin",
        "codex-instructions",
        "codex-hooks",
        "codex-install-context",
        "codex-collaboration-mode-templates",
        "codex-features",
        "codex-secrets",
        "codex-thread-store",
        "codex-login",
        "codex-feedback",
    ]
    utilities = sorted(
        [
            crate["name"]
            for crate in crates
            if crate["name"].startswith("codex-utils-")
            or crate["name"]
            in {
                "codex-analytics",
                "codex-apply-patch",
                "codex-file-search",
                "codex-git-utils",
                "codex-ansi-escape",
                "codex-async-utils",
                "codex-keyring-store",
                "codex-network-proxy",
                "codex-otel",
                "codex-response-debug-context",
                "codex-tools",
                "codex-code-mode",
                "codex-backend-openapi-models",
            }
        ]
    )
    experiments = [
        "codex-v8-poc",
        "codex-debug-client",
        "codex-test-binary-support",
        "app_test_support",
        "core_test_support",
        "mcp_test_support",
        "codex-experimental-api-macros",
    ]
    assigned = set(
        entrypoints + app_protocol + mcp_integrations + execution_sandbox + model_cloud + config_skills + utilities + experiments
    )
    subsystems = [
        _make_subsystem(
            "subsystem.packaging-and-sdks",
            "packaging-and-sdks",
            "Top-level non-Rust package manager and SDK surfaces that sit outside the main Rust workspace.",
            [],
            crate_index,
            extra_paths=["package.json", "pnpm-workspace.yaml", "codex-cli", "sdk"],
            root_scope="repo",
        ),
        _make_subsystem(
            "subsystem.entrypoints-and-core",
            "entrypoints-and-core",
            "Primary Rust entrypoints and the core business-logic layer.",
            entrypoints,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.app-and-protocol",
            "app-and-protocol",
            "Rich-client integration crates centered on app-server and shared protocol types.",
            app_protocol,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.mcp-and-integrations",
            "mcp-and-integrations",
            "MCP client/server and remote integration surfaces that connect Codex to external runtimes.",
            mcp_integrations,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.execution-and-sandbox",
            "execution-and-sandbox",
            "Command execution, sandbox policy, and platform-specific runtime hardening.",
            execution_sandbox,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.model-and-cloud",
            "model-and-cloud",
            "Model provider, rollout, and cloud-facing coordination crates.",
            model_cloud,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.config-and-skills",
            "config-and-skills",
            "Config, instructions, skills, plugins, and session-state surfaces that shape agent behavior.",
            config_skills,
            crate_index,
        ),
        _make_subsystem(
            "subsystem.utilities",
            "utilities",
            "Shared utilities, file search, telemetry, and support crates reused across the workspace.",
            utilities,
            crate_index,
            extra_paths=["utils"],
        ),
        _make_subsystem(
            "subsystem.tests-and-experiments",
            "tests-and-experiments",
            "Test-support, experimental, and debug crates that are important for contributor workflows but not core runtime dispatch.",
            experiments,
            crate_index,
        ),
    ]
    leftovers = sorted(crate["name"] for crate in crates if crate["name"] not in assigned)
    if leftovers:
        subsystems.append(
            _make_subsystem(
                "subsystem.misc",
                "misc",
                "Workspace members that do not yet match a stronger Codex-specific bucket.",
                leftovers,
                crate_index,
            )
        )
    return [subsystem for subsystem in subsystems if subsystem["crate_count"] > 0 or subsystem["focus_paths"]]


def _subsystems_for_repo(repo_family: str, crates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if repo_family == "burn":
        return _burn_subsystems(crates)
    if repo_family == "codex":
        return _codex_subsystems(crates)
    return _generic_subsystems(crates)


def _orientation_flow(
    *,
    binding: dict[str, Any],
    subsystems: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes = [
        {
            "id": "n_repo",
            "label": binding["repo_root"],
            "kind": "repo",
            "evidence_ids": [],
        }
    ]
    edges: list[dict[str, Any]] = []
    workspace_anchor = "n_repo"
    if binding["rust_focus_root"] != binding["repo_root"]:
        nodes.append(
            {
                "id": "n_rust_focus",
                "label": binding["rust_focus_root"],
                "kind": "rust-focus-root",
                "evidence_ids": ["ev.workspace-root"],
            }
        )
        edges.append({"from": "n_repo", "to": "n_rust_focus", "relation": "contains"})
        workspace_anchor = "n_rust_focus"
    elif binding["workspace_root"] == binding["repo_root"]:
        workspace_anchor = "n_repo"
    if binding["workspace_root"] not in {binding["repo_root"], binding["rust_focus_root"]}:
        nodes.append(
            {
                "id": "n_workspace",
                "label": binding["workspace_root"],
                "kind": "workspace-root",
                "evidence_ids": ["ev.workspace-root"],
            }
        )
        edges.append({"from": workspace_anchor, "to": "n_workspace", "relation": "contains"})
        workspace_anchor = "n_workspace"
    for subsystem in subsystems[:6]:
        node_id = f"n_{_safe_id(subsystem['name'])}"
        representative = subsystem.get("representative_crates", [])
        evidence_ids = [f"ev.crate.{representative[0]}"] if representative else []
        nodes.append(
            {
                "id": node_id,
                "label": subsystem["name"],
                "kind": "subsystem",
                "evidence_ids": evidence_ids,
            }
        )
        parent_id = "n_repo" if subsystem.get("root_scope") == "repo" else workspace_anchor
        edges.append({"from": parent_id, "to": node_id, "relation": "contains"})
    return {
        "id": "flow.repo-orientation",
        "kind": "dependency",
        "title": "repository orientation path",
        "nodes": nodes,
        "edges": edges,
    }


def _build_semantic_bundle(
    *,
    repo_name: str,
    repo_family_info: dict[str, Any],
    repo_root: Path,
    workspace_root: Path,
    binding: dict[str, Any],
    snapshot: dict[str, Any],
    crates: list[dict[str, Any]],
    coverage_level: str,
) -> dict[str, Any]:
    evidence_items: list[dict[str, Any]] = []
    seen_evidence_ids: set[str] = set()
    concepts = [
        {
            "id": "concept.rust-focus-root",
            "name": "Rust focus root",
            "summary": "The subtree where Rust-first analysis should begin.",
        },
        {
            "id": "concept.workspace-root",
            "name": "Workspace root",
            "summary": "The Cargo workspace root that anchors package-level analysis.",
        },
    ]
    boundaries: list[dict[str, Any]] = []
    if binding["rust_focus_root"] != binding["repo_root"]:
        boundaries.append(
            {
                "id": "boundary.rust-focus",
                "lhs": binding["repo_root"],
                "relation": "contains",
                "rhs": binding["rust_focus_root"],
            }
        )
    invariants = [
        {
            "id": "invariant.snapshot-version-policy",
            "text": f"Version policy is {snapshot['version_policy']} and release channel is {snapshot['release_channel']}.",
        }
    ]
    claims: list[dict[str, Any]] = []
    overview_points: list[str] = []
    low_confidence_areas: list[str] = []

    workspace_evidence_id = _append_evidence(
        evidence_items,
        seen_evidence_ids,
        evidence_id="ev.workspace-root",
        kind="file",
        path=workspace_root / "Cargo.toml",
        snapshot_id=snapshot["identity"],
        locator=_relpath(workspace_root / "Cargo.toml", repo_root),
        source="manual",
    )
    tag_evidence_id = workspace_evidence_id
    if snapshot.get("tag"):
        tag_evidence_id = _append_evidence(
            evidence_items,
            seen_evidence_ids,
            evidence_id="ev.snapshot-tag",
            kind="query",
            path=repo_root,
            snapshot_id=snapshot["identity"],
            symbol=snapshot["tag"],
            locator="git describe --tags --exact-match",
            source="manual",
        )

    repo_readme_id = _add_doc_evidence(
        evidence_items,
        seen_evidence_ids,
        repo_root=repo_root,
        path=repo_root / "README.md",
        snapshot_id=snapshot["identity"],
        evidence_id="ev.doc.repo-readme",
    )
    workspace_readme_id = ""
    if workspace_root != repo_root:
        workspace_readme_id = _add_doc_evidence(
            evidence_items,
            seen_evidence_ids,
            repo_root=repo_root,
            path=workspace_root / "README.md",
            snapshot_id=snapshot["identity"],
            evidence_id="ev.doc.workspace-readme",
        )

    claims.append(
        {
            "id": "claim.workspace.shape",
            "kind": "architecture",
            "text": f"{repo_name} exposes a Rust workspace rooted at {binding['workspace_root']} with {len(crates)} workspace packages.",
            "confidence": "high",
            "scope": "repo",
            "evidence_ids": [workspace_evidence_id],
        }
    )
    if binding["rust_focus_root"] != binding["repo_root"]:
        claims.append(
            {
                "id": "claim.rust-focus-root",
                "kind": "boundary",
                "text": f"The main Rust analysis surface is the subtree at {binding['rust_focus_root']}, not the repository root.",
                "confidence": "high",
                "scope": "repo",
                "evidence_ids": [workspace_evidence_id],
            }
        )
    if snapshot.get("tag"):
        claims.append(
            {
                "id": "claim.release-channel",
                "kind": "invariant",
                "text": f"The current snapshot is pinned to tag {snapshot['tag']} on the {snapshot['release_channel']} channel.",
                "confidence": "high",
                "scope": "repo",
                "evidence_ids": [tag_evidence_id],
            }
        )

    rich_semantics = coverage_level in {"core", "deep"}
    crate_evidence_limit = len(crates) if rich_semantics else min(len(crates), 16)
    for crate in crates[:crate_evidence_limit]:
        _add_crate_evidence(
            evidence_items,
            seen_evidence_ids,
            repo_root=repo_root,
            workspace_root=workspace_root,
            snapshot_id=snapshot["identity"],
            crate=crate,
        )

    repo_family = repo_family_info.get("name", "generic")
    crate_index = _crate_index(crates)
    subsystems = _subsystems_for_repo(repo_family, crates)
    if any(subsystem["name"] == "misc" for subsystem in subsystems):
        low_confidence_areas.append("Some workspace members still fall into a generic `misc` subsystem bucket.")

    if repo_family == "burn":
        if not repo_readme_id:
            low_confidence_areas.append("Burn root README is missing; architecture claims fall back to crate naming heuristics.")
        else:
            overview_points.append("Start with `README.md` backend and training sections before diving into crate manifests.")
        overview_points.extend(
            [
                "Treat `examples/*` as executable orientation anchors rather than incidental samples.",
                "Backend changes usually fan out across `burn-backend`, decorator crates, and concrete backend implementations.",
            ]
        )
        concepts.extend(
            [
                {
                    "id": "concept.backend-decorator",
                    "name": "Backend decorator",
                    "summary": "A wrapper layer such as autodiff, fusion, routing, or remoting that augments an underlying backend.",
                },
                {
                    "id": "concept.training-surface",
                    "name": "Training surface",
                    "summary": "The set of crates and examples that turn tensor primitives into trainable workflows.",
                },
            ]
        )
        boundaries.extend(
            [
                {
                    "id": "boundary.burn.examples-vs-crates",
                    "lhs": "examples/* workspace members",
                    "relation": "separate-from",
                    "rhs": "crates/* library surface",
                },
                {
                    "id": "boundary.burn.decorators-vs-backends",
                    "lhs": "backend decorators",
                    "relation": "wrap",
                    "rhs": "concrete backends",
                },
            ]
        )
        if rich_semantics and repo_readme_id:
            backend_doc_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=repo_root / "README.md",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.burn-readme-backend",
                anchor="Backend",
            )
            training_doc_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=repo_root / "README.md",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.burn-readme-training",
                anchor="Training & Inference",
            )
            claims.extend(
                [
                    {
                        "id": "claim.burn.repo-purpose",
                        "kind": "architecture",
                        "text": "Burn positions itself as both a tensor library and a deep learning framework.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [repo_readme_id],
                    },
                    {
                        "id": "claim.burn.decorator-model",
                        "kind": "architecture",
                        "text": "Burn organizes backend capabilities through backend-generic abstractions plus decorator-style wrappers such as autodiff and fusion.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [
                            backend_doc_id,
                            "ev.crate.burn-backend",
                            "ev.crate.burn-autodiff",
                            "ev.crate.burn-fusion",
                        ],
                    },
                    {
                        "id": "claim.burn.training-surface",
                        "kind": "architecture",
                        "text": "Training and inference are first-class surfaces anchored by dedicated training, dataset, optimizer, store, and example crates.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [
                            training_doc_id,
                            "ev.crate.burn-train",
                            "ev.crate.burn-dataset",
                            "ev.crate.burn-store",
                            "ev.crate.guide",
                        ],
                    },
                    {
                        "id": "claim.burn.examples-as-entrypoints",
                        "kind": "boundary",
                        "text": "Burn's examples are part of the workspace and should be treated as real entrypoints for orientation and flow tracing.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [workspace_evidence_id, "ev.crate.guide"],
                    },
                ]
            )

    elif repo_family == "codex":
        if not workspace_readme_id:
            low_confidence_areas.append("`codex-rs/README.md` is missing; Rust CLI claims fall back to workspace naming heuristics.")
        overview_points.extend(
            [
                "Read the top-level `README.md` for install surfaces, then `codex-rs/README.md` for actual Rust code organization.",
                "Keep the mixed-language boundary in mind: packaging and SDK work lives outside `codex-rs`, but Rust runtime logic starts inside it.",
                "CLI changes usually trace through `cli` or `exec` into `core`; rich-client work usually traces through `app-server` and `protocol`.",
            ]
        )
        concepts.extend(
            [
                {
                    "id": "concept.mixed-language-boundary",
                    "name": "Mixed-language boundary",
                    "summary": "The repo root contains packaging and SDK surfaces beside the Rust workspace, so `repo_root` and `rust_focus_root` differ meaningfully.",
                },
                {
                    "id": "concept.app-server",
                    "name": "App-server protocol surface",
                    "summary": "A JSON-RPC integration layer used by rich clients such as IDE extensions.",
                },
                {
                    "id": "concept.sandbox-policy",
                    "name": "Sandbox policy",
                    "summary": "A cross-platform execution policy surface implemented through core logic and OS-specific helper crates.",
                },
            ]
        )
        boundaries.extend(
            [
                {
                    "id": "boundary.codex.packaging-vs-workspace",
                    "lhs": "top-level packaging and SDK surfaces",
                    "relation": "sits-alongside",
                    "rhs": "codex-rs Rust workspace",
                },
                {
                    "id": "boundary.codex.protocol-layer",
                    "lhs": "app-server / external clients",
                    "relation": "communicates-via",
                    "rhs": "codex-protocol types",
                },
                {
                    "id": "boundary.codex.platform-sandbox",
                    "lhs": "sandbox policy layer",
                    "relation": "dispatches-to",
                    "rhs": "platform-specific sandbox helpers",
                },
            ]
        )
        if rich_semantics:
            package_json_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=repo_root / "package.json",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.codex-package-json",
            )
            pnpm_workspace_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=repo_root / "pnpm-workspace.yaml",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.codex-pnpm-workspace",
            )
            workspace_code_org_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=workspace_root / "README.md",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.codex-rs-code-organization",
                anchor="Code Organization",
            )
            core_readme_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=workspace_root / "core" / "README.md",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.codex-core-readme",
            )
            app_server_readme_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=workspace_root / "app-server" / "README.md",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.codex-app-server-readme",
            )
            protocol_readme_id = _add_doc_evidence(
                evidence_items,
                seen_evidence_ids,
                repo_root=repo_root,
                path=workspace_root / "protocol" / "README.md",
                snapshot_id=snapshot["identity"],
                evidence_id="ev.doc.codex-protocol-readme",
            )
            claims.extend(
                [
                    {
                        "id": "claim.codex.mixed-repo",
                        "kind": "boundary",
                        "text": "The top-level Codex repository is a mixed-language monorepo, so Rust-first analysis should start in `codex-rs` while keeping packaging and SDK surfaces in view.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [workspace_evidence_id, package_json_id, pnpm_workspace_id],
                    },
                    {
                        "id": "claim.codex.rust-cli",
                        "kind": "architecture",
                        "text": "The maintained Codex CLI implementation lives in the Rust workspace, while top-level install surfaces wrap that executable.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [repo_readme_id, workspace_readme_id],
                    },
                    {
                        "id": "claim.codex.core-architecture",
                        "kind": "architecture",
                        "text": "codex-core is the business-logic center, while `cli`, `tui`, and `exec` provide distinct user-facing and automation entry surfaces.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [
                            workspace_code_org_id,
                            core_readme_id,
                            "ev.crate.codex-core",
                            "ev.crate.codex-cli",
                            "ev.crate.codex-tui",
                            "ev.crate.codex-exec",
                        ],
                    },
                    {
                        "id": "claim.codex.app-server-surface",
                        "kind": "architecture",
                        "text": "app-server is the main rich-client integration surface and speaks shared types defined in codex-protocol.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [
                            app_server_readme_id,
                            protocol_readme_id,
                            "ev.crate.codex-app-server",
                            "ev.crate.codex-protocol",
                        ],
                    },
                    {
                        "id": "claim.codex.mcp-surface",
                        "kind": "architecture",
                        "text": "Codex acts as both an MCP client and an experimental MCP server inside the Rust workspace.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [workspace_readme_id, "ev.crate.codex-mcp", "ev.crate.codex-mcp-server"],
                    },
                    {
                        "id": "claim.codex.sandbox-surface",
                        "kind": "architecture",
                        "text": "Sandbox and command-execution behavior is split across core policy logic and OS-specific helper crates.",
                        "confidence": "high",
                        "scope": "repo",
                        "evidence_ids": [
                            core_readme_id,
                            "ev.crate.codex-sandboxing",
                            "ev.crate.codex-execpolicy",
                            "ev.crate.codex-linux-sandbox",
                            "ev.crate.codex-windows-sandbox",
                        ],
                    },
                ]
            )

    elif rich_semantics and repo_readme_id:
        summary = _readme_summary(repo_root / "README.md")
        if summary:
            claims.append(
                {
                    "id": "claim.repo.summary",
                    "kind": "architecture",
                    "text": summary,
                    "confidence": "medium",
                    "scope": "repo",
                    "evidence_ids": [repo_readme_id],
                }
            )
            overview_points.append("Start with the repo README summary, then use subsystem groups and evidence to narrow deeper source reading.")

    flows = [_orientation_flow(binding=binding, subsystems=subsystems)]

    if repo_family == "burn" and rich_semantics:
        flows.extend(
            [
                {
                    "id": "flow.burn.backend-stack",
                    "kind": "dependency",
                    "title": "backend abstraction and decorator path",
                    "nodes": [
                        {
                            "id": "n_burn_facade",
                            "label": "burn facade crate",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.burn"],
                        },
                        {
                            "id": "n_burn_backend",
                            "label": "burn-backend",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.burn-backend"],
                        },
                        {
                            "id": "n_burn_decorators",
                            "label": "decorator crates",
                            "kind": "subsystem",
                            "evidence_ids": ["ev.crate.burn-autodiff", "ev.crate.burn-fusion", "ev.crate.burn-router"],
                        },
                        {
                            "id": "n_burn_backends",
                            "label": "concrete backend crates",
                            "kind": "subsystem",
                            "evidence_ids": ["ev.crate.burn-wgpu", "ev.crate.burn-cuda", "ev.crate.burn-ndarray"],
                        },
                    ],
                    "edges": [
                        {"from": "n_burn_facade", "to": "n_burn_backend", "relation": "re-exports-from"},
                        {"from": "n_burn_backend", "to": "n_burn_decorators", "relation": "wrapped-by"},
                        {"from": "n_burn_decorators", "to": "n_burn_backends", "relation": "decorate"},
                    ],
                },
                {
                    "id": "flow.burn.training-path",
                    "kind": "execution",
                    "title": "example-to-training workflow path",
                    "nodes": [
                        {
                            "id": "n_burn_example_guide",
                            "label": "examples/guide",
                            "kind": "entrypoint",
                            "evidence_ids": ["ev.crate.guide"],
                        },
                        {
                            "id": "n_burn_train",
                            "label": "burn-train",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.burn-train"],
                        },
                        {
                            "id": "n_burn_nn",
                            "label": "burn-nn",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.burn-nn"],
                        },
                        {
                            "id": "n_burn_optim",
                            "label": "burn-optim",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.burn-optim"],
                        },
                        {
                            "id": "n_burn_dataset",
                            "label": "burn-dataset",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.burn-dataset"],
                        },
                        {
                            "id": "n_burn_store",
                            "label": "burn-store",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.burn-store"],
                        },
                    ],
                    "edges": [
                        {"from": "n_burn_example_guide", "to": "n_burn_train", "relation": "constructs"},
                        {"from": "n_burn_train", "to": "n_burn_nn", "relation": "trains"},
                        {"from": "n_burn_train", "to": "n_burn_optim", "relation": "steps-with"},
                        {"from": "n_burn_train", "to": "n_burn_dataset", "relation": "consumes"},
                        {"from": "n_burn_train", "to": "n_burn_store", "relation": "persists-to"},
                    ],
                },
            ]
        )

    if repo_family == "codex" and rich_semantics:
        flows.extend(
            [
                {
                    "id": "flow.codex.cli-stack",
                    "kind": "execution",
                    "title": "install surface to Rust CLI path",
                    "nodes": [
                        {
                            "id": "n_codex_install_surface",
                            "label": "top-level install/package surfaces",
                            "kind": "package-surface",
                            "evidence_ids": ["ev.doc.repo-readme", "ev.doc.codex-package-json", "ev.doc.codex-pnpm-workspace"],
                        },
                        {
                            "id": "n_codex_cli",
                            "label": "codex-rs/cli",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-cli"],
                        },
                        {
                            "id": "n_codex_tui",
                            "label": "codex-rs/tui",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-tui"],
                        },
                        {
                            "id": "n_codex_exec",
                            "label": "codex-rs/exec",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-exec"],
                        },
                        {
                            "id": "n_codex_core",
                            "label": "codex-core",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-core", "ev.doc.codex-core-readme"],
                        },
                    ],
                    "edges": [
                        {"from": "n_codex_install_surface", "to": "n_codex_cli", "relation": "routes-to"},
                        {"from": "n_codex_cli", "to": "n_codex_tui", "relation": "dispatches-to"},
                        {"from": "n_codex_cli", "to": "n_codex_exec", "relation": "dispatches-to"},
                        {"from": "n_codex_tui", "to": "n_codex_core", "relation": "drives"},
                        {"from": "n_codex_exec", "to": "n_codex_core", "relation": "drives"},
                    ],
                },
                {
                    "id": "flow.codex.app-server-stack",
                    "kind": "dependency",
                    "title": "rich-client app-server path",
                    "nodes": [
                        {
                            "id": "n_codex_client_surface",
                            "label": "IDE or rich client",
                            "kind": "external-surface",
                            "evidence_ids": ["ev.doc.codex-app-server-readme"],
                        },
                        {
                            "id": "n_codex_app_server",
                            "label": "codex app-server",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-app-server", "ev.doc.codex-app-server-readme"],
                        },
                        {
                            "id": "n_codex_protocol",
                            "label": "codex-protocol",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-protocol", "ev.doc.codex-protocol-readme"],
                        },
                        {
                            "id": "n_codex_core_integration",
                            "label": "codex-core",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-core"],
                        },
                        {
                            "id": "n_codex_mcp",
                            "label": "codex-mcp + codex-mcp-server",
                            "kind": "subsystem",
                            "evidence_ids": ["ev.crate.codex-mcp", "ev.crate.codex-mcp-server"],
                        },
                    ],
                    "edges": [
                        {"from": "n_codex_client_surface", "to": "n_codex_app_server", "relation": "connects-to"},
                        {"from": "n_codex_app_server", "to": "n_codex_protocol", "relation": "speaks"},
                        {"from": "n_codex_app_server", "to": "n_codex_core_integration", "relation": "invokes"},
                        {"from": "n_codex_core_integration", "to": "n_codex_mcp", "relation": "integrates-with"},
                    ],
                },
                {
                    "id": "flow.codex.sandbox-stack",
                    "kind": "control",
                    "title": "command execution and sandbox policy path",
                    "nodes": [
                        {
                            "id": "n_codex_command_entry",
                            "label": "cli / exec command surfaces",
                            "kind": "entrypoint",
                            "evidence_ids": ["ev.crate.codex-cli", "ev.crate.codex-exec"],
                        },
                        {
                            "id": "n_codex_core_policy",
                            "label": "codex-core",
                            "kind": "crate",
                            "evidence_ids": ["ev.crate.codex-core", "ev.doc.codex-core-readme"],
                        },
                        {
                            "id": "n_codex_sandbox_policy",
                            "label": "sandboxing / execpolicy",
                            "kind": "subsystem",
                            "evidence_ids": ["ev.crate.codex-sandboxing", "ev.crate.codex-execpolicy", "ev.crate.codex-shell-command"],
                        },
                        {
                            "id": "n_codex_linux_sandbox",
                            "label": "Linux sandbox helpers",
                            "kind": "platform-helper",
                            "evidence_ids": ["ev.crate.codex-linux-sandbox"],
                        },
                        {
                            "id": "n_codex_windows_sandbox",
                            "label": "Windows sandbox helpers",
                            "kind": "platform-helper",
                            "evidence_ids": ["ev.crate.codex-windows-sandbox"],
                        },
                    ],
                    "edges": [
                        {"from": "n_codex_command_entry", "to": "n_codex_core_policy", "relation": "requests"},
                        {"from": "n_codex_core_policy", "to": "n_codex_sandbox_policy", "relation": "delegates-policy-to"},
                        {"from": "n_codex_sandbox_policy", "to": "n_codex_linux_sandbox", "relation": "uses-on-linux"},
                        {"from": "n_codex_sandbox_policy", "to": "n_codex_windows_sandbox", "relation": "uses-on-windows"},
                    ],
                },
            ]
        )

    if coverage_level == "deep":
        low_confidence_areas.append("Deep coverage currently reuses core semantic enrichers and does not yet add API-level analyzers.")

    _annotate_claim_support(claims, evidence_items)

    return {
        "concepts": concepts,
        "subsystems": subsystems,
        "boundaries": boundaries,
        "invariants": invariants,
        "claims": claims,
        "flows": flows,
        "evidence": evidence_items,
        "overview_points": overview_points,
        "low_confidence_areas": low_confidence_areas,
        "doc_evidence_count": sum(1 for item in evidence_items if item.get("source") == "doc"),
        "crate_evidence_count": sum(1 for item in evidence_items if item.get("source") == "cargo-metadata"),
        "enricher": repo_family if rich_semantics and repo_family in {"burn", "codex"} else "generic",
        "repo_family": repo_family_info,
    }


def _playbooks_for_repo(repo_name: str, binding: dict[str, Any], coverage_level: str) -> list[dict[str, Any]]:
    base_playbooks = [
        {
            "id": "playbook.orientation",
            "task_type": "orientation",
            "when_to_use": "Need a fast, correct global picture of the repository.",
            "read_order": ["overview.md", "repo-profile.json", "global-model.json"],
            "queries": ["inspect workspace root", "count crates", "check release channel"],
            "pitfalls": ["assuming repo root equals workspace root", "ignoring mixed-language boundaries"],
        },
        {
            "id": "playbook.localization",
            "task_type": "localization",
            "when_to_use": "Need to find the right crate, manifest, or entrypoint before deeper reading.",
            "read_order": ["repo-profile.json", "crate-graph.json", "flows.json", "evidence.json"],
            "queries": ["locate workspace members", "find entrypoint targets", "inspect subsystem buckets"],
            "pitfalls": ["confusing facade crates with implementation crates", "treating examples as core entrypoints"],
        },
        {
            "id": "playbook.relation-tracing",
            "task_type": "relation-tracing",
            "when_to_use": "Need to understand the main architectural or dependency paths.",
            "read_order": ["global-model.json", "crate-graph.json", "coupling-map.json", "flows.json", "evidence.json"],
            "queries": ["trace workspace containment", "trace subsystem grouping", "verify claims against evidence"],
            "pitfalls": ["over-trusting shallow profile coverage", "skipping source verification for high-risk claims"],
        },
        {
            "id": "playbook.change-planning",
            "task_type": "change-planning",
            "when_to_use": "Need to plan a change after the initial atlas orientation.",
            "read_order": ["repo-profile.json", "crate-graph.json", "impact-index.json", "global-model.json", "flows.json", "evidence.json"],
            "queries": ["identify likely owning crates", "find relevant targets", "check whether refresh is still needed"],
            "pitfalls": ["assuming profile coverage is enough for implementation", "ignoring stale atlas indicators"],
        },
        {
            "id": "playbook.impact-analysis",
            "task_type": "impact-analysis",
            "when_to_use": "Need to estimate which subsystems or crates a change could affect.",
            "read_order": ["impact-index.json", "crate-graph.json", "coupling-map.json", "flows.json", "global-model.json", "evidence.json"],
            "queries": ["inspect reverse dependencies", "inspect strong coupling pairs", "follow subsystem and flow context"],
            "pitfalls": ["treating crate dependency edges as a full call graph", "failing to refresh after repo drift"],
        },
    ]
    if repo_name == "burn":
        base_playbooks[1]["queries"] = [
            "locate the crate family first",
            "check whether the task lives in core, decorators, backends, or examples",
            "verify the relevant example entrypoint if the task is workflow-oriented",
        ]
        base_playbooks[2]["queries"] = [
            "trace facade -> backend -> decorator -> implementation paths",
            "trace example -> burn-train -> dataset/optim/store paths",
            "verify architecture claims against README-backed evidence",
        ]
        base_playbooks[3]["pitfalls"] = [
            "missing generic backend fan-out",
            "changing an example without checking the corresponding library crates",
            "assuming a backend-specific change is isolated to one crate",
        ]
    if repo_name == "codex":
        base_playbooks[0]["pitfalls"] = [
            "assuming the repo root is the Rust workspace root",
            "ignoring non-Rust packaging and SDK surfaces",
            "starting in a leaf utility crate before locating the correct entry surface",
        ]
        base_playbooks[1]["queries"] = [
            "decide whether the task belongs to cli/tui/exec, app-server/protocol, or sandbox/model-provider surfaces",
            "confirm whether the change starts at repo root or inside codex-rs",
            "use subsystem buckets before diving into individual utility crates",
        ]
        base_playbooks[2]["queries"] = [
            "trace install surface -> cli -> core paths",
            "trace app-server -> protocol -> core paths",
            "trace command execution -> sandbox policy -> platform helper paths",
        ]
        base_playbooks[3]["pitfalls"] = [
            "editing a Rust entry surface without checking core and protocol implications",
            "ignoring cross-platform sandbox backends",
            "forgetting top-level packaging or SDK consumers for repo-root changes",
        ]
    if coverage_level == "profile":
        for playbook in base_playbooks:
            playbook["pitfalls"] = playbook.get("pitfalls", []) + ["profile coverage may omit richer repo-specific flows and evidence"]
    return base_playbooks


def _render_global_model_md(global_model: dict[str, Any]) -> str:
    lines = ["# Global Model", ""]
    if global_model.get("concepts"):
        lines.extend(["## Concepts", ""])
        for concept in global_model["concepts"]:
            lines.append(f"- `{concept['name']}`: {concept['summary']}")
        lines.append("")
    if global_model.get("subsystems"):
        lines.extend(["## Subsystems", ""])
        for subsystem in global_model["subsystems"]:
            summary = subsystem.get("summary", "")
            rep = ", ".join(subsystem.get("representative_crates", [])[:4])
            detail = f" Representative crates: `{rep}`." if rep else ""
            lines.append(f"- `{subsystem['name']}`: {summary}{detail}")
        lines.append("")
    if global_model.get("boundaries"):
        lines.extend(["## Boundaries", ""])
        for boundary in global_model["boundaries"]:
            lines.append(f"- `{boundary['lhs']}` {boundary['relation']} `{boundary['rhs']}`")
        lines.append("")
    if global_model.get("invariants"):
        lines.extend(["## Invariants", ""])
        for invariant in global_model["invariants"]:
            lines.append(f"- {invariant['text']}")
        lines.append("")
    if global_model.get("claims"):
        lines.extend(["## Claims", ""])
        for claim in global_model["claims"]:
            evidence = ", ".join(claim.get("evidence_ids", []))
            suffix = f" Evidence: `{evidence}`." if evidence else ""
            lines.append(f"- `{claim['id']}`: {claim['text']}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_playbook_md(playbook: dict[str, Any]) -> str:
    lines = [f"# {playbook['task_type'].replace('-', ' ').title()}", "", playbook["when_to_use"], ""]
    lines.extend(["## Read Order", ""])
    for index, item in enumerate(playbook.get("read_order", []), start=1):
        lines.append(f"{index}. `{item}`")
    lines.extend(["", "## Queries", ""])
    for query in playbook.get("queries", []):
        lines.append(f"- {query}")
    pitfalls = playbook.get("pitfalls", [])
    if pitfalls:
        lines.extend(["", "## Pitfalls", ""])
        for pitfall in pitfalls:
            lines.append(f"- {pitfall}")
    lines.append("")
    return "\n".join(lines)


def _validate_bundle(bundle_dir: Path) -> dict[str, Any]:
    required_files = [
        "overview.md",
        "repo-profile.json",
        "global-model.json",
        "flows.json",
        "playbooks.json",
        "evidence.json",
        "crate-graph.json",
        "coupling-map.json",
        "impact-index.json",
        "diagnostics.json",
    ]
    missing = [name for name in required_files if not (bundle_dir / name).exists()]
    parsed: dict[str, dict[str, Any]] = {}
    invalid_json: list[str] = []
    for name in required_files:
        if not name.endswith(".json"):
            continue
        path = bundle_dir / name
        if not path.exists():
            continue
        try:
            parsed[name] = read_json(path)
        except Exception:
            invalid_json.append(name)
    metadata_errors: list[str] = []
    expected_snapshot_ids = {doc.get("snapshot_id") for doc in parsed.values() if isinstance(doc, dict)}
    expected_schema_versions = {doc.get("schema_version") for doc in parsed.values() if isinstance(doc, dict)}
    if len(expected_snapshot_ids) > 1:
        metadata_errors.append("JSON artifacts disagree on snapshot_id.")
    if len(expected_schema_versions) > 1:
        metadata_errors.append("JSON artifacts disagree on schema_version.")
    evidence_ids = {
        item.get("id")
        for item in parsed.get("evidence.json", {}).get("evidence", [])
        if isinstance(item, dict) and item.get("id")
    }
    missing_refs: list[str] = []
    for claim in parsed.get("global-model.json", {}).get("claims", []):
        if not isinstance(claim, dict):
            continue
        for evidence_id in claim.get("evidence_ids", []):
            if evidence_id and evidence_id not in evidence_ids:
                missing_refs.append(f"claim {claim.get('id', '?')} -> {evidence_id}")
    for flow in parsed.get("flows.json", {}).get("flows", []):
        if not isinstance(flow, dict):
            continue
        for node in flow.get("nodes", []):
            if not isinstance(node, dict):
                continue
            for evidence_id in node.get("evidence_ids", []):
                if evidence_id and evidence_id not in evidence_ids:
                    missing_refs.append(f"flow {flow.get('id', '?')} node {node.get('id', '?')} -> {evidence_id}")
    if missing_refs:
        preview = "; ".join(missing_refs[:10])
        metadata_errors.append(f"Missing evidence references: {preview}")
    repo_profile = parsed.get("repo-profile.json", {})
    diagnostics = parsed.get("diagnostics.json", {})
    global_model = parsed.get("global-model.json", {})
    crate_graph = parsed.get("crate-graph.json", {})
    coupling_map = parsed.get("coupling-map.json", {})
    impact_index = parsed.get("impact-index.json", {})
    if repo_profile and diagnostics:
        stats = diagnostics.get("workspace_stats", {})
        if stats.get("crate_count") not in (None, len(repo_profile.get("crates", []))):
            metadata_errors.append("Diagnostics crate_count does not match repo-profile crates.")
        if stats.get("entrypoint_count") not in (None, len(repo_profile.get("entrypoints", []))):
            metadata_errors.append("Diagnostics entrypoint_count does not match repo-profile entrypoints.")
        if stats.get("subsystem_count") not in (None, len(global_model.get("subsystems", []))):
            metadata_errors.append("Diagnostics subsystem_count does not match global-model subsystems.")
        if crate_graph and stats.get("dependency_edge_count") not in (None, len(crate_graph.get("edges", []))):
            metadata_errors.append("Diagnostics dependency_edge_count does not match crate-graph edges.")
        if coupling_map and stats.get("coupling_cluster_count") not in (None, len(coupling_map.get("clusters", []))):
            metadata_errors.append("Diagnostics coupling_cluster_count does not match coupling-map clusters.")
        if impact_index and stats.get("impact_seed_count") not in (None, len(impact_index.get("seeds", []))):
            metadata_errors.append("Diagnostics impact_seed_count does not match impact-index seeds.")
    is_valid = not missing and not invalid_json and not metadata_errors
    return {
        "bundle_path": str(bundle_dir.resolve()),
        "missing_files": missing,
        "invalid_json_files": invalid_json,
        "metadata_errors": metadata_errors,
        "valid": is_valid,
    }


class AtlasRuntime:
    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root).expanduser().resolve()

    def _detect_binding(self) -> dict[str, Any]:
        source_kind = "git" if _is_git_repo(self.repo_root) else "filesystem"
        actual_root = _git_toplevel(self.repo_root) if source_kind == "git" else self.repo_root
        workspace_root, workspace_kind = _detect_workspace_root(actual_root)
        rust_focus_root = _detect_rust_focus_root(actual_root, workspace_root)
        language_context = _detect_language_context(actual_root)
        rust_focus_candidates = _rust_focus_candidates(actual_root, workspace_root, rust_focus_root)
        return {
            "repo_root": str(actual_root),
            "source_kind": source_kind,
            "rust_focus_root": str(rust_focus_root),
            "workspace_root": str(workspace_root),
            "workspace_kind": workspace_kind,
            "language_focus": ["rust"],
            "language_context": language_context,
            "rust_focus_candidates": rust_focus_candidates,
        }

    def _detect_snapshot(self, binding: dict[str, Any], version_policy: str) -> dict[str, Any]:
        root = Path(binding["repo_root"])
        if binding["source_kind"] == "git":
            return _git_snapshot(root, version_policy)
        return _filesystem_snapshot(root, version_policy)

    def bind(self, *, version_policy: str = "latest", allow_prerelease: bool = True) -> dict[str, Any]:
        binding = self._detect_binding()
        repo_root = Path(binding["repo_root"])
        ensure_layout(repo_root)
        state = load_state(repo_root)
        if not state.get("runtime"):
            state = empty_state(repo_root)
        snapshot = self._detect_snapshot(binding, version_policy)
        freshness_status, reasons, checked_against = _freshness(snapshot, state)
        state["runtime"]["repo_id"] = stable_repo_id(repo_root)
        state["runtime"]["tool_version"] = TOOL_VERSION
        state["runtime"]["artifact_schema_version"] = ARTIFACT_SCHEMA_VERSION
        state["runtime"]["status"] = "ready" if freshness_status == "fresh" else "bound"
        state["runtime"]["atlas_root"] = str(atlas_root(repo_root).resolve())
        state["runtime"]["last_error"] = ""
        state["binding"] = binding
        state["snapshot"] = snapshot
        state["freshness"] = {
            "status": freshness_status,
            "reasons": reasons,
            "last_checked_at": now_iso(),
            "checked_against": checked_against,
        }
        state["policy"]["storage_mode"] = "repo-local"
        state["policy"]["refresh_mode"] = "manual"
        state["policy"]["stale_check_mode"] = "cheap"
        state["policy"]["analysis_profile"] = "default"
        state["policy"]["allow_prerelease"] = bool(allow_prerelease)
        state["snapshot"]["version_policy"] = version_policy
        state["agent_hints"] = _agent_hints(
            freshness_status,
            reasons,
            state.get("artifacts", {}).get("coverage_level", "profile"),
        )
        save_state(repo_root, state)
        return state

    def inspect(self) -> dict[str, Any]:
        state = self.bind(
            version_policy=load_state(self.repo_root).get("snapshot", {}).get("version_policy", "latest"),
            allow_prerelease=load_state(self.repo_root).get("policy", {}).get("allow_prerelease", True),
        )
        return state

    def refresh(self, *, coverage_level: str = "profile") -> dict[str, Any]:
        state = self.bind(
            version_policy=load_state(self.repo_root).get("snapshot", {}).get("version_policy", "latest"),
            allow_prerelease=load_state(self.repo_root).get("policy", {}).get("allow_prerelease", True),
        )
        repo_root = Path(state["binding"]["repo_root"])
        snapshot_id = state["snapshot"]["identity"]
        snapshot_dir = snapshots_root(repo_root) / snapshot_id
        bundle_dir = bundles_root(repo_root) / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        (bundle_dir / "rendered" / "playbooks").mkdir(parents=True, exist_ok=True)

        header = _artifact_header(repo_root, snapshot_id)
        repo_name = repo_root.name
        metadata = _cargo_metadata(Path(state["binding"]["workspace_root"]))
        crates: list[dict[str, Any]] = []
        entrypoints: list[dict[str, Any]] = []
        metadata_failures: list[str] = []
        if metadata is not None:
            crates = _major_crates(metadata, Path(state["binding"]["workspace_root"]))
            entrypoints = _entrypoints(metadata, Path(state["binding"]["workspace_root"]))
        else:
            metadata_failures.append("cargo metadata failed or returned invalid JSON")
        repo_archetype = _infer_repo_archetype(
            repo_name,
            state["binding"]["workspace_kind"],
            state["binding"].get("language_context", []),
            len(crates),
        )
        repo_family_info = _detect_repo_family(repo_name, crates, state["binding"])
        coverage = _coverage_metadata(coverage_level)
        semantic = _build_semantic_bundle(
            repo_name=repo_name,
            repo_family_info=repo_family_info,
            repo_root=repo_root,
            workspace_root=Path(state["binding"]["workspace_root"]),
            binding=state["binding"],
            snapshot=state["snapshot"],
            crates=crates,
            coverage_level=coverage_level,
        )
        playbook_items = _playbooks_for_repo(repo_family_info["name"], state["binding"], coverage_level)
        subsystems = semantic["subsystems"]
        crate_graph_body = _build_crate_graph(
            metadata=metadata,
            workspace_root=Path(state["binding"]["workspace_root"]),
            crates=crates,
            subsystems=subsystems,
            coverage=coverage,
        )
        coupling_map_body = _build_coupling_map(
            crate_graph=crate_graph_body,
            subsystems=subsystems,
            coverage=coverage,
        )
        impact_index_body = _build_impact_index(
            crate_graph=crate_graph_body,
            coupling_map=coupling_map_body,
            crates=crates,
            coverage=coverage,
        )
        repo_profile = {
            **header,
            "repo_name": repo_name,
            "repo_archetype": repo_archetype,
            "repo_family": repo_family_info,
            "coverage": coverage,
            "atlas_root": str(atlas_root(repo_root).resolve()),
            "storage_mode": "repo-local",
            "source_kind": state["binding"]["source_kind"],
            "workspace_root": state["binding"]["workspace_root"],
            "rust_focus_root": state["binding"]["rust_focus_root"],
            "rust_focus_root_reason": "workspace root selected as Rust focus root",
            "workspace_kind": state["binding"]["workspace_kind"],
            "crates": crates,
            "entrypoints": entrypoints,
            "build_surface": ["cargo metadata --format-version 1 --no-deps"],
            "test_surface": ["cargo test --workspace"],
            "language_mix": ["rust"] + state["binding"].get("language_context", []),
            "rust_focus_candidates": state["binding"].get("rust_focus_candidates", []),
        }
        global_model = {
            **header,
            "coverage": coverage,
            "concepts": semantic["concepts"],
            "subsystems": subsystems,
            "boundaries": semantic["boundaries"],
            "invariants": semantic["invariants"],
            "claims": semantic["claims"],
        }
        flows = {
            **header,
            "coverage": coverage,
            "flows": semantic["flows"],
        }
        playbooks = {
            **header,
            "coverage": coverage,
            "playbooks": playbook_items,
        }
        evidence = {
            **header,
            "coverage": coverage,
            "evidence": semantic["evidence"],
        }
        crate_graph = {
            **header,
            **crate_graph_body,
        }
        coupling_map = {
            **header,
            **coupling_map_body,
        }
        impact_index = {
            **header,
            **impact_index_body,
        }
        diagnostics = {
            **header,
            "coverage_level": coverage_level,
            "coverage": coverage,
            "low_confidence_areas": (
                semantic["low_confidence_areas"]
                if crates
                else semantic["low_confidence_areas"] + ["Workspace/package extraction is incomplete."]
            ),
            "tool_failures": metadata_failures,
            "reuse_status": "safe",
            "portability": {
                "repo_local": True,
                "shareable_files": ["overview.md"],
                "nonportable_reasons": ["absolute paths in structured artifacts"],
            },
            "semantic_inputs": {
                "repo_specific_enricher": semantic["enricher"],
                "repo_family": semantic["repo_family"],
                "doc_evidence_count": semantic["doc_evidence_count"],
                "crate_evidence_count": semantic["crate_evidence_count"],
            },
            "workspace_stats": {
                "crate_count": len(crates),
                "entrypoint_count": len(entrypoints),
                "subsystem_count": len(subsystems),
                "dependency_edge_count": len(crate_graph_body.get("edges", [])),
                "coupling_cluster_count": len(coupling_map_body.get("clusters", [])),
                "impact_seed_count": len(impact_index_body.get("seeds", [])),
            },
        }
        manifest = {
            "schema_version": 1,
            "repo_root": str(repo_root.resolve()),
            "snapshot_id": snapshot_id,
            "generated_at": now_iso(),
            "generator": {
                "name": "rust-repo-atlas",
                "version": TOOL_VERSION,
            },
            "binding": state["binding"],
            "snapshot": state["snapshot"],
            "coverage_level": coverage_level,
            "coverage": coverage,
            "repo_family": repo_family_info,
            "outputs": {
                "bundle_dir": str(bundle_dir.resolve()),
                "files": [
                    "overview.md",
                    "repo-profile.json",
                    "global-model.json",
                    "flows.json",
                    "playbooks.json",
                    "evidence.json",
                    "crate-graph.json",
                    "coupling-map.json",
                    "impact-index.json",
                    "diagnostics.json",
                ],
            },
        }

        overview_lines = [
            f"# Atlas Overview: {repo_name}",
            "",
            f"- Snapshot: `{snapshot_id}`",
            f"- Release channel: `{state['snapshot']['release_channel']}`",
            f"- Source kind: `{state['binding']['source_kind']}`",
            f"- Workspace root: `{state['binding']['workspace_root']}`",
            f"- Rust focus root: `{state['binding']['rust_focus_root']}`",
            f"- Repo archetype: `{repo_archetype}`",
            f"- Repo family: `{repo_family_info['name']}` ({repo_family_info['confidence']})",
            f"- Workspace packages: `{len(crates)}`",
            f"- Coverage: `{coverage_level}`",
            f"- Coverage confidence: `{coverage['confidence']}`",
        ]
        if semantic["overview_points"]:
            overview_lines.extend(["", "## Orientation Cues", ""])
            overview_lines.extend([f"- {point}" for point in semantic["overview_points"]])
        overview_lines.extend(
            [
                "",
                (
                    "This profile-level bundle is optimized for quick structural orientation."
                    if coverage_level == "profile"
                    else "Use the structured JSON artifacts for evidence-backed claims, subsystem grouping, and change-planning follow-up."
                ),
            ]
        )

        write_json(snapshot_dir / "manifest.json", manifest)
        write_json(bundle_dir / "repo-profile.json", repo_profile)
        write_json(bundle_dir / "global-model.json", global_model)
        write_json(bundle_dir / "flows.json", flows)
        write_json(bundle_dir / "playbooks.json", playbooks)
        write_json(bundle_dir / "evidence.json", evidence)
        write_json(bundle_dir / "crate-graph.json", crate_graph)
        write_json(bundle_dir / "coupling-map.json", coupling_map)
        write_json(bundle_dir / "impact-index.json", impact_index)
        write_json(bundle_dir / "diagnostics.json", diagnostics)
        (bundle_dir / "overview.md").write_text("\n".join(overview_lines) + "\n", encoding="utf-8")
        (bundle_dir / "rendered" / "global-model.md").write_text(_render_global_model_md(global_model), encoding="utf-8")
        for playbook in playbook_items:
            filename = f"{_safe_id(playbook['task_type'])}.md"
            (bundle_dir / "rendered" / "playbooks" / filename).write_text(
                _render_playbook_md(playbook),
                encoding="utf-8",
            )

        validation = _validate_bundle(bundle_dir)

        state["runtime"]["status"] = "ready"
        state["runtime"]["last_error"] = ""
        state["artifacts"] = {
            "current_snapshot_id": snapshot_id,
            "current_manifest_path": str((snapshot_dir / "manifest.json").resolve()),
            "current_bundle_path": str(bundle_dir.resolve()),
            "generated_at": now_iso(),
            "coverage_level": coverage_level,
            "tool_version": TOOL_VERSION,
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        }
        state["freshness"] = {
            "status": "fresh",
            "reasons": [],
            "last_checked_at": now_iso(),
            "checked_against": snapshot_id,
        }
        state["agent_hints"] = _agent_hints("fresh", [], coverage_level)
        save_state(repo_root, state)
        return {
            "state": state,
            "manifest": manifest,
            "validation": validation,
        }

    def drift(self) -> dict[str, Any]:
        state = load_state(self.repo_root)
        if not state.get("binding", {}).get("repo_root"):
            state = self.bind()
        repo_root = Path(state["binding"]["repo_root"])
        current = self.bind(
            version_policy=state.get("snapshot", {}).get("version_policy", "latest"),
            allow_prerelease=state.get("policy", {}).get("allow_prerelease", True),
        )
        previous_snapshot_id = current.get("artifacts", {}).get("current_snapshot_id", "")
        current_snapshot_id = current.get("snapshot", {}).get("identity", "")
        return {
            "repo_root": str(repo_root),
            "current_snapshot_id": current_snapshot_id,
            "bundle_snapshot_id": previous_snapshot_id,
            "freshness": current.get("freshness", {}),
            "agent_hints": current.get("agent_hints", {}),
        }

    def explain(self) -> dict[str, Any]:
        state = self.inspect()
        bundle = state["artifacts"].get("current_bundle_path", "")
        freshness = state["freshness"]["status"]
        coverage_level = state.get("artifacts", {}).get("coverage_level", "profile")
        coverage = _coverage_metadata(coverage_level)
        message = "No atlas bundle exists yet."
        if bundle and freshness == "fresh":
            message = "Reuse the current bundle by reading overview.md first."
        elif bundle and freshness == "stale":
            message = "Inspect drift and decide whether the task requires a refresh."
        return {
            "repo_root": state["binding"]["repo_root"],
            "freshness": freshness,
            "freshness_reasons": state["freshness"].get("reasons", []),
            "bundle_path": bundle,
            "coverage": coverage,
            "recommended_action": state["agent_hints"]["recommended_action"],
            "recommended_actions": state["agent_hints"].get("recommended_actions", []),
            "safe_for": coverage.get("complete_for", []),
            "not_safe_for": coverage.get("not_complete_for", []),
            "rust_focus_candidates": state["binding"].get("rust_focus_candidates", []),
            "message": message,
        }

    def validate(self) -> dict[str, Any]:
        state = self.inspect()
        bundle = state["artifacts"].get("current_bundle_path", "")
        if not bundle:
            return {
                "valid": False,
                "bundle_path": "",
                "missing_files": ["bundle"],
                "invalid_json_files": [],
                "metadata_errors": ["No current bundle exists."],
            }
        return _validate_bundle(Path(bundle))

    def close(self) -> dict[str, Any]:
        state = load_state(self.repo_root)
        if not state.get("runtime"):
            state = empty_state(self.repo_root)
        state["runtime"]["status"] = "closed"
        state["agent_hints"] = {
            "recommended_action": "bind",
            "recommended_actions": [
                {
                    "action": "bind",
                    "confidence": "high",
                    "why": "Runtime was explicitly closed.",
                }
            ],
            "why": "Runtime was explicitly closed.",
        }
        save_state(self.repo_root, state)
        return state
