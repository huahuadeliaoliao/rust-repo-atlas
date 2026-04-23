from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from test_support import (
    AtlasRuntime,
    atlas_root,
    bundle_path,
    cleanup_repo_root,
    create_burn_fixture_repo,
    create_codex_fixture_repo,
    create_generic_workspace_repo,
    create_nested_no_workspace_repo,
    load_bundle_json,
    read_json,
    write_text,
)


class AtlasRuntimeRegressionTests(unittest.TestCase):
    def tearDown(self) -> None:
        for repo_root in getattr(self, "_repo_roots", []):
            cleanup_repo_root(repo_root)

    def remember(self, repo_root: Path) -> Path:
        self._repo_roots = getattr(self, "_repo_roots", [])
        self._repo_roots.append(repo_root)
        return repo_root

    def test_refresh_generates_bundle_and_validate_passes_for_git_workspace(self) -> None:
        repo_root = self.remember(create_generic_workspace_repo(initialize_git=True))
        runtime = AtlasRuntime(repo_root)

        bind_state = runtime.bind()
        self.assertEqual(bind_state["binding"]["workspace_kind"], "cargo-workspace")
        refresh_result = runtime.refresh(coverage_level="core")

        self.assertTrue(refresh_result["validation"]["valid"])
        bundle_dir = bundle_path(repo_root)
        for name in (
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
        ):
            self.assertTrue((bundle_dir / name).exists(), name)

        crate_graph = load_bundle_json(repo_root, "crate-graph.json")
        impact_index = load_bundle_json(repo_root, "impact-index.json")
        self.assertIn({"from": "toy-app", "to": "toy-core", "kind": "normal", "optional": False, "target": "", "features": [], "reason": "workspace dependency"}, crate_graph["edges"])
        toy_core_seed = next(item for item in impact_index["seeds"] if item["target"] == "toy-core")
        affected_targets = {item["target"] for item in toy_core_seed["likely_affected"]}
        self.assertIn("toy-app", affected_targets)

    def test_drift_marks_bundle_stale_after_dirty_change(self) -> None:
        repo_root = self.remember(create_generic_workspace_repo(initialize_git=True))
        runtime = AtlasRuntime(repo_root)
        runtime.refresh(coverage_level="core")

        write_text(repo_root / "README.md", "# Toy Workspace\n\nThe repo changed after refresh.\n")
        drift = runtime.drift()

        self.assertEqual(drift["freshness"]["status"], "stale")
        self.assertIn("dirty_changed", drift["freshness"]["reasons"])

    def test_dirty_bundle_tracks_content_fingerprint(self) -> None:
        repo_root = self.remember(create_generic_workspace_repo(initialize_git=True))
        runtime = AtlasRuntime(repo_root)

        write_text(repo_root / "README.md", "# Toy Workspace\n\nDirty state captured during refresh.\n")
        runtime.refresh(coverage_level="core")
        write_text(repo_root / "README.md", "# Toy Workspace\n\nDirty state changed again.\n")
        drift = runtime.drift()

        self.assertEqual(drift["freshness"]["status"], "stale")
        self.assertIn("content_fingerprint_changed", drift["freshness"]["reasons"])

    def test_validate_reports_missing_artifact_after_manual_removal(self) -> None:
        repo_root = self.remember(create_generic_workspace_repo(initialize_git=False))
        runtime = AtlasRuntime(repo_root)
        runtime.refresh(coverage_level="core")

        missing_path = bundle_path(repo_root) / "flows.json"
        missing_path.unlink()
        validation = runtime.validate()

        self.assertFalse(validation["valid"])
        self.assertIn("flows.json", validation["missing_files"])

    def test_explain_returns_soft_agent_decision_context(self) -> None:
        repo_root = self.remember(create_generic_workspace_repo(initialize_git=True))
        runtime = AtlasRuntime(repo_root)
        runtime.refresh(coverage_level="profile")

        explanation = runtime.explain()

        self.assertEqual(explanation["freshness"], "fresh")
        self.assertEqual(explanation["coverage"]["level"], "profile")
        self.assertIn("workspace-localization", explanation["safe_for"])
        self.assertTrue(explanation["recommended_actions"])
        self.assertIn("rust_focus_candidates", explanation)

    def test_nested_no_workspace_prefers_common_rust_subtree_candidate(self) -> None:
        repo_root = self.remember(create_nested_no_workspace_repo(initialize_git=False))
        runtime = AtlasRuntime(repo_root)
        state = runtime.bind()

        self.assertEqual(state["binding"]["workspace_kind"], "mixed")
        self.assertTrue(state["binding"]["rust_focus_root"].endswith("/rust/crates"))
        candidates = state["binding"]["rust_focus_candidates"]
        self.assertEqual(candidates[0]["relative_path"], "rust/crates")

    def test_burn_specific_enricher_builds_expected_subsystems_and_flows(self) -> None:
        repo_root = self.remember(create_burn_fixture_repo(initialize_git=False))
        runtime = AtlasRuntime(repo_root)
        runtime.refresh(coverage_level="core")

        global_model = load_bundle_json(repo_root, "global-model.json")
        flows = load_bundle_json(repo_root, "flows.json")
        diagnostics = load_bundle_json(repo_root, "diagnostics.json")

        subsystem_names = {item["name"] for item in global_model["subsystems"]}
        self.assertIn("backend-decorators", subsystem_names)
        self.assertIn("backend-implementations", subsystem_names)
        self.assertIn("training-and-data", subsystem_names)
        self.assertEqual(global_model["coverage"]["level"], "core")
        decorator_claim = next(item for item in global_model["claims"] if item["id"] == "claim.burn.decorator-model")
        self.assertIn("agent_note", decorator_claim["evidence_profile"])
        flow_ids = {item["id"] for item in flows["flows"]}
        self.assertIn("flow.burn.backend-stack", flow_ids)
        self.assertIn("flow.burn.training-path", flow_ids)
        crate_graph = load_bundle_json(repo_root, "crate-graph.json")
        coupling_map = load_bundle_json(repo_root, "coupling-map.json")
        impact_index = load_bundle_json(repo_root, "impact-index.json")
        self.assertIn("burn-autodiff", crate_graph["reverse_dependencies"]["burn-backend"])
        self.assertTrue(any(pair["lhs"] == "burn-autodiff" and pair["rhs"] == "burn-backend" for pair in coupling_map["strong_pairs"]))
        backend_seed = next(item for item in impact_index["seeds"] if item["target"] == "burn-backend")
        backend_affected = {item["target"] for item in backend_seed["likely_affected"]}
        self.assertIn("burn-autodiff", backend_affected)
        self.assertEqual(diagnostics["semantic_inputs"]["repo_specific_enricher"], "burn")
        self.assertEqual(diagnostics["semantic_inputs"]["repo_family"]["name"], "burn")

    def test_codex_specific_enricher_detects_mixed_language_workspace(self) -> None:
        repo_root = self.remember(create_codex_fixture_repo(initialize_git=False))
        runtime = AtlasRuntime(repo_root)
        bind_state = runtime.bind()
        refresh_result = runtime.refresh(coverage_level="core")

        self.assertEqual(bind_state["binding"]["workspace_kind"], "mixed")
        self.assertIn("javascript", bind_state["binding"]["language_context"])

        global_model = load_bundle_json(repo_root, "global-model.json")
        flows = load_bundle_json(repo_root, "flows.json")
        diagnostics = load_bundle_json(repo_root, "diagnostics.json")

        claims = {item["id"] for item in global_model["claims"]}
        self.assertIn("claim.codex.mixed-repo", claims)
        self.assertIn("claim.codex.core-architecture", claims)
        flow_ids = {item["id"] for item in flows["flows"]}
        self.assertIn("flow.codex.cli-stack", flow_ids)
        self.assertIn("flow.codex.app-server-stack", flow_ids)
        crate_graph = load_bundle_json(repo_root, "crate-graph.json")
        impact_index = load_bundle_json(repo_root, "impact-index.json")
        self.assertIn("codex-tui", crate_graph["direct_dependencies"]["codex-cli"])
        core_seed = next(item for item in impact_index["seeds"] if item["target"] == "codex-core")
        core_affected = {item["target"] for item in core_seed["likely_affected"]}
        self.assertIn("codex-exec", core_affected)
        self.assertTrue(refresh_result["validation"]["valid"])
        self.assertEqual(diagnostics["semantic_inputs"]["repo_specific_enricher"], "codex")


if __name__ == "__main__":
    unittest.main()
