#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from runtime import AtlasRuntime
from state import atlas_root, load_state, now_iso, read_json, save_state


DEFAULT_TASKS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "tasks"
DEFAULT_ANSWERS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "answers"
DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "reports"


def _print(data: dict[str, Any]) -> int:
    print(json.dumps(data, ensure_ascii=True, indent=2))
    return 0


def _normalize_text(value: object) -> str:
    return " ".join(str(value).lower().replace("\\", "/").split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return _normalize_text(phrase) in _normalize_text(text)


def _normalize_location(value: str) -> tuple[str, str]:
    normalized = _normalize_text(value)
    if "#" in normalized:
        path, anchor = normalized.split("#", 1)
        return path, anchor
    return normalized, ""


def _location_matches(answer_location: str, gold_location: str) -> bool:
    answer_path, answer_anchor = _normalize_location(answer_location)
    gold_path, gold_anchor = _normalize_location(gold_location)
    if answer_path != gold_path:
        return False
    if not gold_anchor or not answer_anchor:
        return True
    return answer_anchor == gold_anchor


def _normalize_relation(relation: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _normalize_text(relation.get("lhs", "")),
        _normalize_text(relation.get("relation", "")),
        _normalize_text(relation.get("rhs", "")),
    )


def load_task(path: str | Path) -> dict[str, Any]:
    task = read_json(Path(path))
    task["task_path"] = str(Path(path).resolve())
    return task


def _write_json_if_requested(path: str | Path | None, data: dict[str, Any]) -> str:
    if not path:
        return ""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return str(resolved)


def _write_text_if_requested(path: str | Path | None, text: str) -> str:
    if not path:
        return ""
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")
    return str(resolved)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _resolve_optional_path(path: str | Path | None) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser().resolve())


def list_tasks(tasks_dir: str | Path = DEFAULT_TASKS_DIR) -> dict[str, Any]:
    base = Path(tasks_dir).resolve()
    tasks = [load_task(path) for path in sorted(base.rglob("*.json"))]
    return {
        "tasks_dir": str(base),
        "task_count": len(tasks),
        "tasks": [
            {
                "task_id": task.get("task_id", ""),
                "repo_name": task.get("repo_name", ""),
                "condition": task.get("condition", ""),
                "task_path": task["task_path"],
            }
            for task in tasks
        ],
    }


def prepare_condition(
    repo_root: str | Path,
    condition: str,
    *,
    coverage_level: str = "core",
    version_policy: str = "latest",
    allow_prerelease: bool = True,
) -> dict[str, Any]:
    repo_root = Path(repo_root).expanduser().resolve()
    if condition == "baseline":
        shutil.rmtree(atlas_root(repo_root), ignore_errors=True)
        return {
            "repo_root": str(repo_root),
            "condition": condition,
            "atlas_present": False,
            "prepared_at": now_iso(),
        }

    runtime = AtlasRuntime(repo_root)
    runtime.bind(version_policy=version_policy, allow_prerelease=allow_prerelease)
    effective_coverage = "profile" if condition == "partial-atlas" else coverage_level
    refreshed = runtime.refresh(coverage_level=effective_coverage)
    state = refreshed["state"]

    if condition == "stale-atlas":
        stale_state = load_state(repo_root)
        original_snapshot_id = stale_state["artifacts"]["current_snapshot_id"]
        stale_state["artifacts"]["current_snapshot_id"] = f"{original_snapshot_id}:benchmark-stale"
        stale_state["freshness"] = {
            "status": "stale",
            "reasons": ["benchmark_condition"],
            "last_checked_at": now_iso(),
            "checked_against": stale_state["snapshot"]["identity"],
        }
        stale_state["agent_hints"] = {
            "recommended_action": "inspect_drift",
            "recommended_actions": [
                {
                    "action": "reuse_only_as_background",
                    "confidence": "medium",
                    "why": "Benchmark stale-atlas condition prepared.",
                },
                {
                    "action": "refresh_before_relying_on_claims",
                    "confidence": "high",
                    "why": "Benchmark stale-atlas condition prepared.",
                },
            ],
            "why": "Benchmark stale-atlas condition prepared.",
        }
        save_state(repo_root, stale_state)
        state = stale_state

    return {
        "repo_root": str(repo_root),
        "condition": condition,
        "coverage_level": effective_coverage,
        "atlas_present": True,
        "bundle_path": state["artifacts"]["current_bundle_path"],
        "snapshot_id": state["snapshot"]["identity"],
        "freshness": state["freshness"],
        "prepared_at": now_iso(),
    }


def score_answer(task: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    final_answer = str(answer.get("final_answer") or answer.get("answer") or "")
    required_mentions = list(task.get("must_include", []))
    forbidden_mentions = list(task.get("must_not_claim", []))
    gold_locations = list(task.get("gold_locations", []))
    gold_relations = list(task.get("gold_relations", []))
    expected_refresh = str(task.get("expected_refresh_decision", "")).strip()

    matched_required = [item for item in required_mentions if _contains_phrase(final_answer, item)]
    forbidden_hits = [item for item in forbidden_mentions if _contains_phrase(final_answer, item)]
    matched_locations = [
        location
        for location in gold_locations
        if any(_location_matches(candidate, location) for candidate in answer.get("locations", []))
    ]

    answer_relations = {_normalize_relation(item) for item in answer.get("relations", []) if isinstance(item, dict)}
    matched_relations = [
        relation
        for relation in gold_relations
        if _normalize_relation(relation) in answer_relations
    ]

    required_recall = len(matched_required) / len(required_mentions) if required_mentions else 1.0
    localization_accuracy = len(matched_locations) / len(gold_locations) if gold_locations else 1.0
    relation_accuracy = len(matched_relations) / len(gold_relations) if gold_relations else 1.0
    refresh_discipline = 1.0
    if expected_refresh:
        refresh_discipline = 1.0 if _normalize_text(answer.get("refresh_decision", "")) == _normalize_text(expected_refresh) else 0.0

    components = [
        required_recall,
        0.0 if forbidden_hits else 1.0,
        localization_accuracy,
        relation_accuracy,
        refresh_discipline,
    ]

    return {
        "task_id": task.get("task_id", ""),
        "repo_name": task.get("repo_name", ""),
        "task_condition": task.get("condition", ""),
        "answer_condition": answer.get("condition", ""),
        "answer_label": answer.get("answer_label", ""),
        "metrics": {
            "required_mentions_recall": required_recall,
            "forbidden_mentions_violations": len(forbidden_hits),
            "localization_accuracy": localization_accuracy,
            "relation_accuracy": relation_accuracy,
            "refresh_discipline": refresh_discipline,
            "automatic_score": sum(components) / len(components),
        },
        "details": {
            "matched_required_mentions": matched_required,
            "missing_required_mentions": [item for item in required_mentions if item not in matched_required],
            "forbidden_hits": forbidden_hits,
            "matched_locations": matched_locations,
            "missed_locations": [item for item in gold_locations if item not in matched_locations],
            "matched_relations": matched_relations,
            "missed_relations": [item for item in gold_relations if item not in matched_relations],
            "expected_refresh_decision": expected_refresh,
            "actual_refresh_decision": answer.get("refresh_decision", ""),
        },
    }


def score_answer_file(task_path: str | Path, answer_path: str | Path) -> dict[str, Any]:
    return score_answer(load_task(task_path), read_json(Path(answer_path)))


def score_batch(tasks_dir: str | Path, answers_dir: str | Path, *, label: str = "") -> dict[str, Any]:
    tasks_dir = Path(tasks_dir).resolve()
    answers_dir = Path(answers_dir).resolve()
    tasks = [load_task(path) for path in sorted(tasks_dir.rglob("*.json"))]
    answers = []
    for path in sorted(answers_dir.rglob("*.json")):
        answer = read_json(path)
        answer.setdefault("answer_path", str(path.resolve()))
        answer.setdefault("answer_label", label or answers_dir.name)
        answers.append(answer)
    tasks_by_id = {task["task_id"]: task for task in tasks if task.get("task_id")}
    scored: list[dict[str, Any]] = []
    missing_tasks: list[str] = []
    for answer in answers:
        task_id = str(answer.get("task_id", "")).strip()
        task = tasks_by_id.get(task_id)
        if task is None:
            missing_tasks.append(task_id or "<missing-task-id>")
            continue
        scored.append(score_answer(task, answer))
    average_score = _mean([item["metrics"]["automatic_score"] for item in scored])
    average_required = _mean([item["metrics"]["required_mentions_recall"] for item in scored])
    average_localization = _mean([item["metrics"]["localization_accuracy"] for item in scored])
    average_relation = _mean([item["metrics"]["relation_accuracy"] for item in scored])
    average_refresh = _mean([item["metrics"]["refresh_discipline"] for item in scored])
    repo_summary: list[dict[str, Any]] = []
    repos = sorted({item["repo_name"] for item in scored})
    for repo_name in repos:
        repo_items = [item for item in scored if item["repo_name"] == repo_name]
        repo_summary.append(
            {
                "repo_name": repo_name,
                "result_count": len(repo_items),
                "average_automatic_score": _mean([item["metrics"]["automatic_score"] for item in repo_items]),
                "average_localization_accuracy": _mean([item["metrics"]["localization_accuracy"] for item in repo_items]),
                "average_relation_accuracy": _mean([item["metrics"]["relation_accuracy"] for item in repo_items]),
            }
        )
    task_summary = [
        {
            "task_id": item["task_id"],
            "repo_name": item["repo_name"],
            "automatic_score": item["metrics"]["automatic_score"],
            "required_mentions_recall": item["metrics"]["required_mentions_recall"],
            "localization_accuracy": item["metrics"]["localization_accuracy"],
            "relation_accuracy": item["metrics"]["relation_accuracy"],
            "refresh_discipline": item["metrics"]["refresh_discipline"],
            "forbidden_mentions_violations": item["metrics"]["forbidden_mentions_violations"],
        }
        for item in scored
    ]
    return {
        "label": label or answers_dir.name,
        "tasks_dir": str(tasks_dir),
        "answers_dir": str(answers_dir),
        "task_count": len(tasks),
        "result_count": len(scored),
        "task_coverage": len(scored) / len(tasks) if tasks else 0.0,
        "missing_task_ids": missing_tasks,
        "average_automatic_score": average_score,
        "average_required_mentions_recall": average_required,
        "average_localization_accuracy": average_localization,
        "average_relation_accuracy": average_relation,
        "average_refresh_discipline": average_refresh,
        "repo_summary": repo_summary,
        "task_summary": task_summary,
        "results": scored,
    }


def render_markdown_report(score_batch_result: dict[str, Any]) -> str:
    label = score_batch_result.get("label", "")
    lines = [
        "# Benchmark Report",
        "",
        f"- Label: `{label}`" if label else "- Label: `unnamed`",
        f"- Tasks dir: `{score_batch_result.get('tasks_dir', '')}`",
        f"- Answers dir: `{score_batch_result.get('answers_dir', '')}`",
        f"- Task coverage: `{score_batch_result.get('result_count', 0)}/{score_batch_result.get('task_count', 0)}`",
        f"- Average automatic score: `{score_batch_result.get('average_automatic_score', 0.0):.3f}`",
        "",
        "## Repo Summary",
        "",
        "| Repo | Count | Avg Score | Avg Localization | Avg Relation |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in score_batch_result.get("repo_summary", []):
        lines.append(
            f"| `{item['repo_name']}` | {item['result_count']} | {item['average_automatic_score']:.3f} | {item['average_localization_accuracy']:.3f} | {item['average_relation_accuracy']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Task Summary",
            "",
            "| Task | Repo | Score | Required | Localization | Relation | Refresh | Forbidden |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in score_batch_result.get("task_summary", []):
        lines.append(
            f"| `{item['task_id']}` | `{item['repo_name']}` | {item['automatic_score']:.3f} | {item['required_mentions_recall']:.3f} | {item['localization_accuracy']:.3f} | {item['relation_accuracy']:.3f} | {item['refresh_discipline']:.3f} | {item['forbidden_mentions_violations']} |"
        )
    if score_batch_result.get("missing_task_ids"):
        lines.extend(["", "## Missing Task IDs", ""])
        for task_id in score_batch_result["missing_task_ids"]:
            lines.append(f"- `{task_id}`")
    lines.append("")
    return "\n".join(lines)


def score_batch_and_write(
    tasks_dir: str | Path,
    answers_dir: str | Path,
    *,
    label: str = "",
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
) -> dict[str, Any]:
    result = score_batch(tasks_dir, answers_dir, label=label)
    markdown = render_markdown_report(result)
    json_path = _resolve_optional_path(out_json)
    md_path = _resolve_optional_path(out_md)
    if json_path or md_path:
        result["written_outputs"] = {
            "json_path": json_path,
            "markdown_path": md_path,
        }
    _write_json_if_requested(json_path, result)
    _write_text_if_requested(md_path, markdown)
    return result


def score_suite(
    tasks_dir: str | Path,
    answers_root: str | Path = DEFAULT_ANSWERS_DIR,
    *,
    baseline_label: str = "",
) -> dict[str, Any]:
    tasks_dir = Path(tasks_dir).resolve()
    answers_root = Path(answers_root).resolve()
    batches: list[dict[str, Any]] = []
    for child in sorted(answers_root.iterdir()):
        if not child.is_dir():
            continue
        if not any(child.rglob("*.json")):
            continue
        batches.append(score_batch(tasks_dir, child, label=child.name))

    chosen_baseline = baseline_label.strip()
    if not chosen_baseline:
        chosen_baseline = next(
            (batch["label"] for batch in batches if "baseline" in batch["label"].lower()),
            batches[0]["label"] if batches else "",
        )

    set_summary = [
        {
            "label": batch["label"],
            "result_count": batch["result_count"],
            "task_coverage": batch["task_coverage"],
            "average_automatic_score": batch["average_automatic_score"],
            "average_required_mentions_recall": batch["average_required_mentions_recall"],
            "average_localization_accuracy": batch["average_localization_accuracy"],
            "average_relation_accuracy": batch["average_relation_accuracy"],
            "average_refresh_discipline": batch["average_refresh_discipline"],
        }
        for batch in sorted(batches, key=lambda item: (-item["average_automatic_score"], item["label"]))
    ]

    comparisons: list[dict[str, Any]] = []
    baseline_batch = next((batch for batch in batches if batch["label"] == chosen_baseline), None)
    if baseline_batch is not None:
        baseline_results = {item["task_id"]: item for item in baseline_batch["results"]}
        for batch in batches:
            if batch["label"] == chosen_baseline:
                continue
            task_deltas: list[dict[str, Any]] = []
            improved_tasks = 0
            regressed_tasks = 0
            unchanged_tasks = 0
            for item in batch["results"]:
                baseline_result = baseline_results.get(item["task_id"])
                if baseline_result is None:
                    continue
                delta = item["metrics"]["automatic_score"] - baseline_result["metrics"]["automatic_score"]
                if delta > 1e-9:
                    improved_tasks += 1
                elif delta < -1e-9:
                    regressed_tasks += 1
                else:
                    unchanged_tasks += 1
                task_deltas.append(
                    {
                        "task_id": item["task_id"],
                        "repo_name": item["repo_name"],
                        "baseline_score": baseline_result["metrics"]["automatic_score"],
                        "candidate_score": item["metrics"]["automatic_score"],
                        "delta": delta,
                    }
                )
            comparisons.append(
                {
                    "baseline_label": chosen_baseline,
                    "candidate_label": batch["label"],
                    "average_score_delta": _mean([item["delta"] for item in task_deltas]),
                    "improved_tasks": improved_tasks,
                    "regressed_tasks": regressed_tasks,
                    "unchanged_tasks": unchanged_tasks,
                    "task_deltas": sorted(task_deltas, key=lambda item: (-item["delta"], item["task_id"])),
                }
            )

    return {
        "tasks_dir": str(tasks_dir),
        "answers_root": str(answers_root),
        "set_count": len(batches),
        "baseline_label": chosen_baseline,
        "set_summary": set_summary,
        "comparisons": comparisons,
        "batches": batches,
    }


def render_suite_markdown_report(score_suite_result: dict[str, Any]) -> str:
    baseline_label = score_suite_result.get("baseline_label", "")
    lines = [
        "# Benchmark Suite Report",
        "",
        f"- Tasks dir: `{score_suite_result.get('tasks_dir', '')}`",
        f"- Answers root: `{score_suite_result.get('answers_root', '')}`",
        f"- Sets scored: `{score_suite_result.get('set_count', 0)}`",
        f"- Baseline label: `{baseline_label}`" if baseline_label else "- Baseline label: `none`",
        "",
        "## Set Summary",
        "",
        "| Label | Coverage | Avg Score | Avg Required | Avg Localization | Avg Relation | Avg Refresh |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in score_suite_result.get("set_summary", []):
        lines.append(
            f"| `{item['label']}` | {item['result_count']} | {item['average_automatic_score']:.3f} | {item['average_required_mentions_recall']:.3f} | {item['average_localization_accuracy']:.3f} | {item['average_relation_accuracy']:.3f} | {item['average_refresh_discipline']:.3f} |"
        )
    if score_suite_result.get("comparisons"):
        lines.extend(
            [
                "",
                "## Deltas Vs Baseline",
                "",
                "| Candidate | Avg Delta | Improved | Regressed | Unchanged |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in score_suite_result["comparisons"]:
            lines.append(
                f"| `{item['candidate_label']}` | {item['average_score_delta']:.3f} | {item['improved_tasks']} | {item['regressed_tasks']} | {item['unchanged_tasks']} |"
            )
        for item in score_suite_result["comparisons"]:
            lines.extend(
                [
                    "",
                    f"## Task Deltas: `{item['candidate_label']}` vs `{item['baseline_label']}`",
                    "",
                    "| Task | Repo | Baseline | Candidate | Delta |",
                    "| --- | --- | ---: | ---: | ---: |",
                ]
            )
            for delta in item.get("task_deltas", []):
                lines.append(
                    f"| `{delta['task_id']}` | `{delta['repo_name']}` | {delta['baseline_score']:.3f} | {delta['candidate_score']:.3f} | {delta['delta']:.3f} |"
                )
    lines.append("")
    return "\n".join(lines)


def score_suite_and_write(
    tasks_dir: str | Path,
    answers_root: str | Path = DEFAULT_ANSWERS_DIR,
    *,
    baseline_label: str = "",
    out_json: str | Path | None = None,
    out_md: str | Path | None = None,
) -> dict[str, Any]:
    result = score_suite(tasks_dir, answers_root, baseline_label=baseline_label)
    markdown = render_suite_markdown_report(result)
    json_path = _resolve_optional_path(out_json)
    md_path = _resolve_optional_path(out_md)
    if json_path or md_path:
        result["written_outputs"] = {
            "json_path": json_path,
            "markdown_path": md_path,
        }
    _write_json_if_requested(json_path, result)
    _write_text_if_requested(md_path, markdown)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="rust-repo-atlas benchmark helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-tasks")
    list_parser.add_argument("--tasks-dir", default=str(DEFAULT_TASKS_DIR))
    list_parser.set_defaults(func=lambda args: list_tasks(args.tasks_dir))

    prepare_parser = subparsers.add_parser("prepare-condition")
    prepare_parser.add_argument("--repo-root", required=True)
    prepare_parser.add_argument(
        "--condition",
        required=True,
        choices=["baseline", "fresh-atlas", "stale-atlas", "partial-atlas"],
    )
    prepare_parser.add_argument("--coverage-level", default="core", choices=["profile", "core", "deep"])
    prepare_parser.add_argument("--version-policy", default="latest", choices=["stable", "latest", "pinned"])
    prepare_parser.add_argument(
        "--allow-prerelease",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    prepare_parser.set_defaults(
        func=lambda args: prepare_condition(
            args.repo_root,
            args.condition,
            coverage_level=args.coverage_level,
            version_policy=args.version_policy,
            allow_prerelease=args.allow_prerelease,
        )
    )

    score_parser = subparsers.add_parser("score-answer")
    score_parser.add_argument("--task", required=True)
    score_parser.add_argument("--answer", required=True)
    score_parser.set_defaults(func=lambda args: score_answer_file(args.task, args.answer))

    batch_parser = subparsers.add_parser("score-batch")
    batch_parser.add_argument("--tasks-dir", default=str(DEFAULT_TASKS_DIR))
    batch_parser.add_argument("--answers-dir", required=True)
    batch_parser.add_argument("--label", default="")
    batch_parser.add_argument("--out-json")
    batch_parser.add_argument("--out-md")
    batch_parser.set_defaults(
        func=lambda args: score_batch_and_write(
            args.tasks_dir,
            args.answers_dir,
            label=args.label,
            out_json=args.out_json,
            out_md=args.out_md,
        )
    )

    suite_parser = subparsers.add_parser("score-suite")
    suite_parser.add_argument("--tasks-dir", default=str(DEFAULT_TASKS_DIR))
    suite_parser.add_argument("--answers-root", default=str(DEFAULT_ANSWERS_DIR))
    suite_parser.add_argument("--baseline-label", default="")
    suite_parser.add_argument("--out-json")
    suite_parser.add_argument("--out-md")
    suite_parser.set_defaults(
        func=lambda args: score_suite_and_write(
            args.tasks_dir,
            args.answers_root,
            baseline_label=args.baseline_label,
            out_json=args.out_json,
            out_md=args.out_md,
        )
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return _print(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
