from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module: {module_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime_module = load_module("atlas_runtime", SCRIPTS_DIR / "runtime.py")
state_module = load_module("atlas_state", SCRIPTS_DIR / "state.py")
benchmark_module = load_module("atlas_benchmark", SCRIPTS_DIR / "benchmark.py")
build_skill_module = load_module("atlas_build_skill", SCRIPTS_DIR / "build_skill_dist.py")
install_skill_module = load_module("atlas_install_skill", SCRIPTS_DIR / "install_skill.py")

AtlasRuntime = runtime_module.AtlasRuntime
atlas_root = state_module.atlas_root
read_json = state_module.read_json


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    return proc.stdout.strip()


def init_git_repo(repo_root: Path) -> None:
    run(["git", "init"], repo_root)
    run(["git", "config", "user.name", "Rust Repo Atlas Tests"], repo_root)
    run(["git", "config", "user.email", "atlas-tests@example.com"], repo_root)
    run(["git", "add", "."], repo_root)
    run(["git", "commit", "-m", "init"], repo_root)


def temp_repo_root(name: str) -> Path:
    base = Path(tempfile.mkdtemp(prefix="rust-repo-atlas-"))
    repo_root = base / name
    repo_root.mkdir(parents=True, exist_ok=True)
    return repo_root


def cleanup_repo_root(repo_root: Path) -> None:
    shutil.rmtree(repo_root.parent, ignore_errors=True)


def create_generic_workspace_repo(*, name: str = "toy-workspace", initialize_git: bool = False) -> Path:
    repo_root = temp_repo_root(name)
    write_text(
        repo_root / "Cargo.toml",
        """[workspace]
members = ["crates/core", "crates/app"]
resolver = "2"
""",
    )
    write_text(repo_root / "README.md", "# Toy Workspace\n\nA small Rust workspace used for atlas tests.\n")
    write_text(
        repo_root / "crates" / "core" / "Cargo.toml",
        """[package]
name = "toy-core"
version = "0.1.0"
edition = "2021"
""",
    )
    write_text(repo_root / "crates" / "core" / "src" / "lib.rs", 'pub fn greet() -> &' + "'static str" + ' { "hello" }\n')
    write_text(
        repo_root / "crates" / "app" / "Cargo.toml",
        """[package]
name = "toy-app"
version = "0.1.0"
edition = "2021"

[dependencies]
toy-core = { path = "../core" }

[[bin]]
name = "toy-app"
path = "src/main.rs"
""",
    )
    write_text(
        repo_root / "crates" / "app" / "src" / "main.rs",
        """fn main() {
    println!("hello from toy-app");
}
""",
    )
    if initialize_git:
        init_git_repo(repo_root)
    return repo_root


def create_nested_no_workspace_repo(*, initialize_git: bool = False) -> Path:
    repo_root = temp_repo_root("mixed-no-workspace")
    write_text(repo_root / "package.json", '{"name": "mixed-no-workspace"}\n')
    write_text(repo_root / "README.md", "# Mixed No Workspace\n\nA repo with a nested Rust subtree.\n")
    packages = {
        "rust/crates/core": ("nested-core", "lib"),
        "rust/crates/app": ("nested-app", "bin"),
    }
    for rel_path, (package_name, kind) in packages.items():
        manifest_lines = [
            "[package]",
            f'name = "{package_name}"',
            'version = "0.1.0"',
            'edition = "2021"',
        ]
        if kind == "bin":
            manifest_lines.extend(["", "[[bin]]", f'name = "{package_name}"', 'path = "src/main.rs"'])
            src_file = "main.rs"
            src_contents = 'fn main() { println!("nested"); }\n'
        else:
            src_file = "lib.rs"
            src_contents = "pub fn marker() {}\n"
        write_text(repo_root / rel_path / "Cargo.toml", "\n".join(manifest_lines) + "\n")
        write_text(repo_root / rel_path / "src" / src_file, src_contents)
    if initialize_git:
        init_git_repo(repo_root)
    return repo_root


def create_burn_fixture_repo(*, initialize_git: bool = False) -> Path:
    repo_root = temp_repo_root("burn")
    write_text(
        repo_root / "Cargo.toml",
        """[workspace]
members = [
    "crates/burn",
    "crates/burn-backend",
    "crates/burn-autodiff",
    "crates/burn-fusion",
    "crates/burn-flex",
    "crates/burn-train",
    "crates/burn-dataset",
    "crates/burn-store",
    "examples/guide",
]
resolver = "2"
""",
    )
    write_text(
        repo_root / "README.md",
        """# Burn

Burn is both a tensor library and a deep learning framework.

## Backend

Burn uses backend-generic abstractions and backend decorators such as autodiff and fusion.

## Training & Inference

Training and inference are first-class surfaces, with dedicated training, dataset, and store crates.
""",
    )
    packages = {
        "crates/burn": ("burn", "lib"),
        "crates/burn-backend": ("burn-backend", "lib"),
        "crates/burn-autodiff": ("burn-autodiff", "lib"),
        "crates/burn-fusion": ("burn-fusion", "lib"),
        "crates/burn-flex": ("burn-flex", "lib"),
        "crates/burn-train": ("burn-train", "lib"),
        "crates/burn-dataset": ("burn-dataset", "lib"),
        "crates/burn-store": ("burn-store", "lib"),
        "examples/guide": ("guide", "bin"),
    }
    dependencies = {
        "crates/burn": ['burn-backend = { path = "../burn-backend" }'],
        "crates/burn-autodiff": ['burn-backend = { path = "../burn-backend" }'],
        "crates/burn-fusion": ['burn-backend = { path = "../burn-backend" }'],
        "crates/burn-train": [
            'burn-dataset = { path = "../burn-dataset" }',
            'burn-store = { path = "../burn-store" }',
        ],
        "examples/guide": ['burn-train = { path = "../../crates/burn-train" }'],
    }
    for rel_path, (package_name, kind) in packages.items():
        manifest_lines = [
            "[package]",
            f'name = "{package_name}"',
            'version = "0.1.0"',
            'edition = "2021"',
        ]
        if dependencies.get(rel_path):
            manifest_lines.extend(["", "[dependencies]", *dependencies[rel_path]])
        if kind == "bin":
            manifest_lines.extend(["", "[[bin]]", f'name = "{package_name}"', 'path = "src/main.rs"'])
            src_file = "main.rs"
            src_contents = 'fn main() { println!("guide"); }\n'
        else:
            src_file = "lib.rs"
            src_contents = "pub fn marker() {}\n"
        write_text(repo_root / rel_path / "Cargo.toml", "\n".join(manifest_lines) + "\n")
        write_text(repo_root / rel_path / "src" / src_file, src_contents)
    if initialize_git:
        init_git_repo(repo_root)
    return repo_root


def create_codex_fixture_repo(*, initialize_git: bool = False) -> Path:
    repo_root = temp_repo_root("codex")
    write_text(
        repo_root / "README.md",
        """# Codex CLI

Top-level install surfaces wrap the maintained Rust CLI implementation.
""",
    )
    write_text(
        repo_root / "package.json",
        """{
  "name": "codex-monorepo",
  "private": true
}
""",
    )
    write_text(repo_root / "pnpm-workspace.yaml", "packages:\n  - codex-cli\n")
    workspace_root = repo_root / "codex-rs"
    write_text(
        workspace_root / "Cargo.toml",
        """[workspace]
members = [
    "cli",
    "tui",
    "exec",
    "core",
    "config",
    "state",
    "app-server",
    "protocol",
    "codex-mcp",
    "mcp-server",
    "shell-command",
    "sandboxing",
    "execpolicy",
    "linux-sandbox",
    "windows-sandbox-rs",
]
resolver = "2"
""",
    )
    write_text(
        workspace_root / "README.md",
        """# Codex CLI (Rust Implementation)

The Rust implementation is the maintained Codex CLI and serves as the default experience.

## Code Organization

- `core/` contains the business logic.
- `exec/` provides a headless CLI.
- `tui/` provides the interactive terminal UI.
- `cli/` dispatches between entry surfaces.

## Model Context Protocol Support

Codex acts as both an MCP client and an experimental MCP server.
""",
    )
    write_text(workspace_root / "core" / "README.md", "# codex-core\n\nThis crate implements the business logic for Codex.\n")
    write_text(
        workspace_root / "app-server" / "README.md",
        "# codex-app-server\n\n`codex app-server` powers rich interfaces and uses a shared protocol surface.\n",
    )
    write_text(
        workspace_root / "protocol" / "README.md",
        "# codex-protocol\n\nThis crate defines the shared protocol types.\n",
    )
    packages = {
        "cli": ("codex-cli", "bin"),
        "tui": ("codex-tui", "bin"),
        "exec": ("codex-exec", "bin"),
        "core": ("codex-core", "lib"),
        "config": ("codex-config", "lib"),
        "state": ("codex-state", "lib"),
        "app-server": ("codex-app-server", "lib"),
        "protocol": ("codex-protocol", "lib"),
        "codex-mcp": ("codex-mcp", "lib"),
        "mcp-server": ("codex-mcp-server", "lib"),
        "shell-command": ("codex-shell-command", "lib"),
        "sandboxing": ("codex-sandboxing", "lib"),
        "execpolicy": ("codex-execpolicy", "lib"),
        "linux-sandbox": ("codex-linux-sandbox", "lib"),
        "windows-sandbox-rs": ("codex-windows-sandbox", "lib"),
    }
    dependencies = {
        "cli": [
            'codex-tui = { path = "../tui" }',
            'codex-exec = { path = "../exec" }',
        ],
        "tui": ['codex-core = { path = "../core" }'],
        "exec": ['codex-core = { path = "../core" }'],
        "app-server": [
            'codex-core = { path = "../core" }',
            'codex-protocol = { path = "../protocol" }',
        ],
        "codex-mcp": ['codex-core = { path = "../core" }'],
        "mcp-server": ['codex-mcp = { path = "../codex-mcp" }'],
        "sandboxing": ['codex-execpolicy = { path = "../execpolicy" }'],
    }
    for rel_path, (package_name, kind) in packages.items():
        manifest_lines = [
            "[package]",
            f'name = "{package_name}"',
            'version = "0.1.0"',
            'edition = "2021"',
        ]
        if dependencies.get(rel_path):
            manifest_lines.extend(["", "[dependencies]", *dependencies[rel_path]])
        if kind == "bin":
            manifest_lines.extend(["", "[[bin]]", f'name = "{package_name}"', 'path = "src/main.rs"'])
            src_file = "main.rs"
            src_contents = 'fn main() { println!("codex"); }\n'
        else:
            src_file = "lib.rs"
            src_contents = "pub fn marker() {}\n"
        write_text(workspace_root / rel_path / "Cargo.toml", "\n".join(manifest_lines) + "\n")
        write_text(workspace_root / rel_path / "src" / src_file, src_contents)
    if initialize_git:
        init_git_repo(repo_root)
    return repo_root


def bundle_path(repo_root: Path) -> Path:
    state = read_json(atlas_root(repo_root) / "state.json")
    return Path(state["artifacts"]["current_bundle_path"])


def load_bundle_json(repo_root: Path, filename: str) -> dict[str, Any]:
    return read_json(bundle_path(repo_root) / filename)
