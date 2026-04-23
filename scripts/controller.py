#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime import AtlasRuntime


def _print(data: dict) -> int:
    print(json.dumps(data, ensure_ascii=True, indent=2))
    return 0


def bind_command(args: argparse.Namespace) -> int:
    runtime = AtlasRuntime(args.repo_root)
    return _print(
        runtime.bind(
            version_policy=args.version_policy,
            allow_prerelease=args.allow_prerelease,
        )
    )


def inspect_command(args: argparse.Namespace) -> int:
    runtime = AtlasRuntime(args.repo_root)
    return _print(runtime.inspect())


def refresh_command(args: argparse.Namespace) -> int:
    runtime = AtlasRuntime(args.repo_root)
    return _print(runtime.refresh(coverage_level=args.coverage_level))


def drift_command(args: argparse.Namespace) -> int:
    runtime = AtlasRuntime(args.repo_root)
    return _print(runtime.drift())


def explain_command(args: argparse.Namespace) -> int:
    runtime = AtlasRuntime(args.repo_root)
    return _print(runtime.explain())


def validate_command(args: argparse.Namespace) -> int:
    runtime = AtlasRuntime(args.repo_root)
    return _print(runtime.validate())


def close_command(args: argparse.Namespace) -> int:
    runtime = AtlasRuntime(args.repo_root)
    return _print(runtime.close())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="rust-repo-atlas controller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bind_parser = subparsers.add_parser("bind")
    bind_parser.add_argument("--repo-root", required=True)
    bind_parser.add_argument(
        "--version-policy",
        default="latest",
        choices=["stable", "latest", "pinned"],
    )
    bind_parser.add_argument(
        "--allow-prerelease",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    bind_parser.set_defaults(func=bind_command)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--repo-root", required=True)
    inspect_parser.set_defaults(func=inspect_command)

    refresh_parser = subparsers.add_parser("refresh")
    refresh_parser.add_argument("--repo-root", required=True)
    refresh_parser.add_argument(
        "--coverage-level",
        default="profile",
        choices=["profile", "core", "deep"],
    )
    refresh_parser.set_defaults(func=refresh_command)

    drift_parser = subparsers.add_parser("drift")
    drift_parser.add_argument("--repo-root", required=True)
    drift_parser.set_defaults(func=drift_command)

    explain_parser = subparsers.add_parser("explain")
    explain_parser.add_argument("--repo-root", required=True)
    explain_parser.set_defaults(func=explain_command)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--repo-root", required=True)
    validate_parser.set_defaults(func=validate_command)

    close_parser = subparsers.add_parser("close")
    close_parser.add_argument("--repo-root", required=True)
    close_parser.set_defaults(func=close_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
