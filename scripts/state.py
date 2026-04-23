#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOOL_VERSION = "0.1.0"
STATE_SCHEMA_VERSION = 1
ARTIFACT_SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def clean_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean_string(item) for item in value if clean_string(item)]


def stable_repo_id(repo_root: Path) -> str:
    return hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:16]


def atlas_root(repo_root: Path) -> Path:
    return repo_root / ".rust-repo-atlas"


def state_path(repo_root: Path) -> Path:
    return atlas_root(repo_root) / "state.json"


def snapshots_root(repo_root: Path) -> Path:
    return atlas_root(repo_root) / "snapshots"


def bundles_root(repo_root: Path) -> Path:
    return atlas_root(repo_root) / "bundles"


def cache_root(repo_root: Path) -> Path:
    return atlas_root(repo_root) / "cache"


def eval_root(repo_root: Path) -> Path:
    return atlas_root(repo_root) / "eval"


def ensure_layout(repo_root: Path) -> None:
    root = atlas_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    snapshots_root(repo_root).mkdir(parents=True, exist_ok=True)
    bundles_root(repo_root).mkdir(parents=True, exist_ok=True)
    cache_root(repo_root).mkdir(parents=True, exist_ok=True)
    eval_root(repo_root).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def empty_state(repo_root: Path) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "runtime": {
            "schema_version": STATE_SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "repo_id": stable_repo_id(repo_root),
            "status": "bound",
            "created_at": timestamp,
            "updated_at": timestamp,
            "atlas_root": str(atlas_root(repo_root).resolve()),
            "last_error": "",
        },
        "binding": {
            "repo_root": str(repo_root.resolve()),
            "source_kind": "filesystem",
            "rust_focus_root": str(repo_root.resolve()),
            "workspace_root": str(repo_root.resolve()),
            "workspace_kind": "mixed",
            "language_focus": ["rust"],
            "language_context": [],
            "rust_focus_candidates": [],
        },
        "snapshot": {
            "identity": "",
            "resolved_ref": "none",
            "commit": "",
            "tag": "",
            "dirty": False,
            "fingerprint": "",
            "content_fingerprint": "",
            "fingerprint_scope": [],
            "release_channel": "unknown",
            "version_policy": "latest",
            "observed_at": timestamp,
        },
        "freshness": {
            "status": "unknown",
            "reasons": ["bundle_missing"],
            "last_checked_at": timestamp,
            "checked_against": "",
        },
        "artifacts": {
            "current_snapshot_id": "",
            "current_manifest_path": "",
            "current_bundle_path": "",
            "generated_at": "",
            "coverage_level": "profile",
            "tool_version": "",
            "artifact_schema_version": 0,
        },
        "policy": {
            "storage_mode": "repo-local",
            "refresh_mode": "manual",
            "stale_check_mode": "cheap",
            "analysis_profile": "default",
            "allow_prerelease": True,
        },
        "agent_hints": {
            "recommended_action": "bind",
            "recommended_actions": [
                {
                    "action": "bind",
                    "confidence": "high",
                    "why": "No atlas bundle exists yet.",
                }
            ],
            "why": "No atlas bundle exists yet.",
        },
    }


def load_state(repo_root: Path) -> dict[str, Any]:
    path = state_path(repo_root)
    if path.exists():
        return read_json(path)
    return empty_state(repo_root)


def save_state(repo_root: Path, state: dict[str, Any]) -> None:
    state["runtime"]["updated_at"] = now_iso()
    write_json(state_path(repo_root), state)
