#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Callable


PACKAGE_NAME = "rust-repo-atlas"

_REFERENCE_REWRITES = {
    "spec/runtime-state.md": "references/runtime-state.md",
    "spec/artifact-schema.md": "references/artifact-schema.md",
    "spec/benchmark-protocol.md": "references/benchmark-protocol.md",
    "spec/authoring-checklist.md": "references/authoring-checklist.md",
}

_COPY_PLAN: tuple[tuple[str, str, Callable[[str], str] | None], ...] = (
    ("SKILL.md", "SKILL.md", None),
    ("agents/openai.yaml", "agents/openai.yaml", None),
    ("scripts/controller.py", "scripts/controller.py", None),
    ("scripts/runtime.py", "scripts/runtime.py", None),
    ("scripts/state.py", "scripts/state.py", None),
    ("spec/runtime-state.md", "references/runtime-state.md", None),
    ("spec/artifact-schema.md", "references/artifact-schema.md", None),
    ("spec/benchmark-protocol.md", "references/benchmark-protocol.md", None),
    ("spec/authoring-checklist.md", "references/authoring-checklist.md", None),
)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _rewrite_skill_body(text: str) -> str:
    rewritten = text
    for source, target in _REFERENCE_REWRITES.items():
        rewritten = rewritten.replace(source, target)
    return rewritten


def _copy_text_file(src: Path, dst: Path, transform: Callable[[str], str] | None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if transform is None:
        shutil.copy2(src, dst)
        return
    dst.write_text(transform(src.read_text(encoding="utf-8")), encoding="utf-8")


def build_skill_package(
    *,
    repo_root: str | Path | None = None,
    output_root: str | Path | None = None,
    package_name: str = PACKAGE_NAME,
) -> dict[str, object]:
    repo_root_path = Path(repo_root).expanduser().resolve() if repo_root else _default_repo_root()
    output_root_path = (
        Path(output_root).expanduser().resolve()
        if output_root
        else (repo_root_path / "skill").resolve()
    )
    package_dir = output_root_path / package_name
    shutil.rmtree(package_dir, ignore_errors=True)
    package_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[str] = []
    for source_rel, target_rel, transform in _COPY_PLAN:
        source_path = repo_root_path / source_rel
        if not source_path.exists():
            raise FileNotFoundError(f"missing build source: {source_path}")
        effective_transform = _rewrite_skill_body if source_rel == "SKILL.md" else transform
        target_path = package_dir / target_rel
        _copy_text_file(source_path, target_path, effective_transform)
        copied_files.append(target_rel)

    return {
        "repo_root": str(repo_root_path),
        "output_root": str(output_root_path),
        "package_name": package_name,
        "package_dir": str(package_dir),
        "file_count": len(copied_files),
        "files": copied_files,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a distributable rust-repo-atlas skill package")
    parser.add_argument("--repo-root")
    parser.add_argument("--output-root")
    parser.add_argument("--package-name", default=PACKAGE_NAME)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = build_skill_package(
        repo_root=args.repo_root,
        output_root=args.output_root,
        package_name=args.package_name,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
