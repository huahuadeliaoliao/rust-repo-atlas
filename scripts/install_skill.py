#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from build_skill_dist import PACKAGE_NAME, build_skill_package


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def install_skill(
    *,
    repo_root: str | Path | None = None,
    package_dir: str | Path | None = None,
    build_output_root: str | Path | None = None,
    dest_root: str | Path | None = None,
    name: str = PACKAGE_NAME,
    build: bool = True,
    upgrade: bool = False,
    force: bool = False,
) -> dict[str, object]:
    repo_root_path = Path(repo_root).expanduser().resolve() if repo_root else _default_repo_root()
    dest_root_path = (
        Path(dest_root).expanduser().resolve()
        if dest_root
        else (Path.home() / ".codex" / "skills").resolve()
    )

    build_result: dict[str, object] | None = None
    package_path: Path | None = Path(package_dir).expanduser().resolve() if package_dir else None
    if build:
        build_result = build_skill_package(
            repo_root=repo_root_path,
            output_root=build_output_root,
            package_name=name,
        )
        package_path = Path(str(build_result["package_dir"])).resolve()

    if package_path is None:
        raise ValueError("package_dir is required when build=False")
    if not package_path.exists():
        raise FileNotFoundError(f"skill package does not exist: {package_path}")

    install_dir = dest_root_path / name
    target_exists = install_dir.exists()
    if target_exists and not (upgrade or force):
        raise FileExistsError(f"skill already installed at {install_dir}; use --upgrade or --force")
    if target_exists:
        shutil.rmtree(install_dir)

    dest_root_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(package_path, install_dir)

    return {
        "repo_root": str(repo_root_path),
        "package_dir": str(package_path),
        "install_dir": str(install_dir),
        "installed": True,
        "build_performed": build,
        "replaced_existing": target_exists,
        "build_result": build_result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the rust-repo-atlas skill into a Codex skills directory")
    parser.add_argument("--repo-root")
    parser.add_argument("--package-dir")
    parser.add_argument("--build-output-root")
    parser.add_argument("--dest")
    parser.add_argument("--name", default=PACKAGE_NAME)
    parser.add_argument(
        "--build",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rebuild the distributable skill package before installing",
    )
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = install_skill(
        repo_root=args.repo_root,
        package_dir=args.package_dir,
        build_output_root=args.build_output_root,
        dest_root=args.dest,
        name=args.name,
        build=args.build,
        upgrade=args.upgrade,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
