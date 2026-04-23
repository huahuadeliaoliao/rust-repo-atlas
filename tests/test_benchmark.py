from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from test_support import (
    atlas_root,
    benchmark_module,
    cleanup_repo_root,
    create_generic_workspace_repo,
    read_json,
)


class AtlasBenchmarkTests(unittest.TestCase):
    def tearDown(self) -> None:
        for repo_root in getattr(self, "_repo_roots", []):
            cleanup_repo_root(repo_root)
        for path in getattr(self, "_temp_dirs", []):
            shutil.rmtree(path, ignore_errors=True)

    def remember(self, repo_root: Path) -> Path:
        self._repo_roots = getattr(self, "_repo_roots", [])
        self._repo_roots.append(repo_root)
        return repo_root

    def remember_temp_dir(self) -> Path:
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        path = Path(tempfile.mkdtemp(prefix="rust-repo-atlas-benchmark-"))
        self._temp_dirs.append(path)
        return path

    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    def test_prepare_condition_handles_baseline_partial_and_stale(self) -> None:
        repo_root = self.remember(create_generic_workspace_repo(initialize_git=True))

        fresh = benchmark_module.prepare_condition(repo_root, "fresh-atlas")
        self.assertEqual(fresh["condition"], "fresh-atlas")
        self.assertTrue((atlas_root(repo_root) / "state.json").exists())

        partial = benchmark_module.prepare_condition(repo_root, "partial-atlas")
        self.assertEqual(partial["coverage_level"], "profile")
        state = read_json(atlas_root(repo_root) / "state.json")
        self.assertEqual(state["artifacts"]["coverage_level"], "profile")

        stale = benchmark_module.prepare_condition(repo_root, "stale-atlas")
        self.assertEqual(stale["condition"], "stale-atlas")
        state = read_json(atlas_root(repo_root) / "state.json")
        self.assertEqual(state["freshness"]["status"], "stale")

        baseline = benchmark_module.prepare_condition(repo_root, "baseline")
        self.assertEqual(baseline["condition"], "baseline")
        self.assertFalse(atlas_root(repo_root).exists())

    def test_score_answer_reports_perfect_match(self) -> None:
        task = {
            "task_id": "burn.trace.backend.decorator-path.001",
            "must_include": ["burn-backend", "burn-autodiff", "burn-fusion"],
            "must_not_claim": ["single monolithic crate"],
            "gold_locations": [
                "crates/burn-backend/src/backend/base.rs#Backend",
                "crates/burn-autodiff/src/backend.rs#Autodiff",
            ],
            "gold_relations": [
                {"lhs": "Autodiff", "relation": "decorates", "rhs": "Backend"},
                {"lhs": "Fusion", "relation": "decorates", "rhs": "Backend"},
            ],
            "expected_refresh_decision": "reuse",
        }
        answer = {
            "task_id": task["task_id"],
            "final_answer": "burn-backend defines the core interface, while burn-autodiff and burn-fusion extend it as separate decorator crates.",
            "locations": [
                "crates/burn-backend/src/backend/base.rs#Backend",
                "crates/burn-autodiff/src/backend.rs#Autodiff",
            ],
            "relations": [
                {"lhs": "Autodiff", "relation": "decorates", "rhs": "Backend"},
                {"lhs": "Fusion", "relation": "decorates", "rhs": "Backend"},
            ],
            "refresh_decision": "reuse",
        }

        result = benchmark_module.score_answer(task, answer)

        self.assertEqual(result["metrics"]["required_mentions_recall"], 1.0)
        self.assertEqual(result["metrics"]["forbidden_mentions_violations"], 0)
        self.assertEqual(result["metrics"]["localization_accuracy"], 1.0)
        self.assertEqual(result["metrics"]["relation_accuracy"], 1.0)
        self.assertEqual(result["metrics"]["refresh_discipline"], 1.0)
        self.assertEqual(result["metrics"]["automatic_score"], 1.0)

    def test_score_answer_penalizes_missing_and_forbidden_content(self) -> None:
        task = {
            "task_id": "codex.localize.rust-focus-root.001",
            "must_include": ["codex-rs", "workspace root"],
            "must_not_claim": ["repository root itself is the only Rust workspace"],
            "gold_locations": ["codex-rs/Cargo.toml"],
            "gold_relations": [{"lhs": "codex-rs", "relation": "contains", "rhs": "primary Rust workspace"}],
            "expected_refresh_decision": "reuse",
        }
        answer = {
            "task_id": task["task_id"],
            "final_answer": "The repository root itself is the only Rust workspace.",
            "locations": ["README.md"],
            "relations": [],
            "refresh_decision": "refresh",
        }

        result = benchmark_module.score_answer(task, answer)

        self.assertLess(result["metrics"]["required_mentions_recall"], 1.0)
        self.assertEqual(result["metrics"]["forbidden_mentions_violations"], 1)
        self.assertEqual(result["metrics"]["localization_accuracy"], 0.0)
        self.assertEqual(result["metrics"]["relation_accuracy"], 0.0)
        self.assertEqual(result["metrics"]["refresh_discipline"], 0.0)
        self.assertLess(result["metrics"]["automatic_score"], 0.5)

    def test_score_batch_and_write_emits_json_and_markdown_reports(self) -> None:
        temp_root = self.remember_temp_dir()
        tasks_dir = temp_root / "tasks"
        answers_dir = temp_root / "answers" / "reference_atlas"
        task = {
            "task_id": "toy.trace.001",
            "repo_name": "toy",
            "condition": "fresh-atlas",
            "must_include": ["toy-core", "toy-app"],
            "must_not_claim": ["single binary only"],
            "gold_locations": ["crates/core/Cargo.toml", "crates/app/Cargo.toml"],
            "gold_relations": [{"lhs": "toy-app", "relation": "depends-on", "rhs": "toy-core"}],
            "expected_refresh_decision": "reuse",
        }
        answer = {
            "task_id": task["task_id"],
            "condition": "fresh-atlas",
            "final_answer": "toy-core contains the shared library while toy-app is the executable surface.",
            "locations": ["crates/core/Cargo.toml", "crates/app/Cargo.toml"],
            "relations": [{"lhs": "toy-app", "relation": "depends-on", "rhs": "toy-core"}],
            "refresh_decision": "reuse",
        }
        self.write_json(tasks_dir / "toy.trace.001.json", task)
        self.write_json(answers_dir / "toy.trace.001.json", answer)

        out_json = temp_root / "reports" / "reference_atlas.json"
        out_md = temp_root / "reports" / "reference_atlas.md"
        result = benchmark_module.score_batch_and_write(
            tasks_dir,
            answers_dir,
            label="reference_atlas",
            out_json=out_json,
            out_md=out_md,
        )

        self.assertEqual(result["average_automatic_score"], 1.0)
        self.assertTrue(out_json.exists())
        self.assertTrue(out_md.exists())
        self.assertIn("reference_atlas", out_md.read_text(encoding="utf-8"))
        written_outputs = result.get("written_outputs", {})
        self.assertEqual(written_outputs.get("json_path"), str(out_json.resolve()))
        self.assertEqual(written_outputs.get("markdown_path"), str(out_md.resolve()))
        persisted = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(persisted["written_outputs"]["json_path"], str(out_json.resolve()))
        self.assertEqual(persisted["written_outputs"]["markdown_path"], str(out_md.resolve()))

    def test_score_suite_compares_candidate_set_against_baseline(self) -> None:
        temp_root = self.remember_temp_dir()
        tasks_dir = temp_root / "tasks"
        answers_root = temp_root / "answers"
        task = {
            "task_id": "toy.trace.001",
            "repo_name": "toy",
            "condition": "fresh-atlas",
            "must_include": ["toy-core", "toy-app"],
            "must_not_claim": ["single binary only"],
            "gold_locations": ["crates/core/Cargo.toml", "crates/app/Cargo.toml"],
            "gold_relations": [{"lhs": "toy-app", "relation": "depends-on", "rhs": "toy-core"}],
            "expected_refresh_decision": "reuse",
        }
        baseline_answer = {
            "task_id": task["task_id"],
            "condition": "baseline",
            "final_answer": "toy-app is the main executable.",
            "locations": ["crates/app/Cargo.toml"],
            "relations": [],
            "refresh_decision": "reuse",
        }
        atlas_answer = {
            "task_id": task["task_id"],
            "condition": "fresh-atlas",
            "final_answer": "toy-core provides shared logic and toy-app is the executable surface that depends on it.",
            "locations": ["crates/core/Cargo.toml", "crates/app/Cargo.toml"],
            "relations": [{"lhs": "toy-app", "relation": "depends-on", "rhs": "toy-core"}],
            "refresh_decision": "reuse",
        }
        self.write_json(tasks_dir / "toy.trace.001.json", task)
        self.write_json(answers_root / "reference_baseline" / "toy.trace.001.json", baseline_answer)
        self.write_json(answers_root / "reference_atlas" / "toy.trace.001.json", atlas_answer)

        out_json = temp_root / "reports" / "suite.json"
        out_md = temp_root / "reports" / "suite.md"
        result = benchmark_module.score_suite_and_write(
            tasks_dir,
            answers_root,
            out_json=out_json,
            out_md=out_md,
        )

        self.assertEqual(result["set_count"], 2)
        self.assertEqual(result["baseline_label"], "reference_baseline")
        self.assertEqual(result["set_summary"][0]["label"], "reference_atlas")
        self.assertGreater(result["set_summary"][0]["average_automatic_score"], result["set_summary"][1]["average_automatic_score"])
        comparison = next(item for item in result["comparisons"] if item["candidate_label"] == "reference_atlas")
        self.assertGreater(comparison["average_score_delta"], 0.0)
        self.assertEqual(comparison["improved_tasks"], 1)
        self.assertTrue(out_json.exists())
        self.assertTrue(out_md.exists())
        markdown = benchmark_module.render_suite_markdown_report(result)
        self.assertIn("reference_baseline", markdown)
        self.assertIn("reference_atlas", markdown)
        persisted = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(persisted["written_outputs"]["json_path"], str(out_json.resolve()))
        self.assertEqual(persisted["written_outputs"]["markdown_path"], str(out_md.resolve()))


if __name__ == "__main__":
    unittest.main()
