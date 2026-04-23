from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from test_support import build_skill_module, install_skill_module


class AtlasSkillDistributionTests(unittest.TestCase):
    def tearDown(self) -> None:
        for path in getattr(self, "_temp_dirs", []):
            shutil.rmtree(path, ignore_errors=True)

    def remember_temp_dir(self) -> Path:
        self._temp_dirs = getattr(self, "_temp_dirs", [])
        path = Path(tempfile.mkdtemp(prefix="rust-repo-atlas-skill-"))
        self._temp_dirs.append(path)
        return path

    def test_build_skill_package_creates_distributable_layout(self) -> None:
        output_root = self.remember_temp_dir()

        result = build_skill_module.build_skill_package(output_root=output_root)

        package_root = Path(result["package_dir"])
        self.assertTrue((package_root / "SKILL.md").exists())
        self.assertTrue((package_root / "agents" / "openai.yaml").exists())
        self.assertTrue((package_root / "scripts" / "controller.py").exists())
        self.assertTrue((package_root / "references" / "runtime-state.md").exists())
        self.assertFalse((package_root / "benchmarks").exists())
        self.assertFalse((package_root / "tests").exists())

        skill_body = (package_root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/runtime-state.md", skill_body)
        self.assertNotIn("spec/runtime-state.md", skill_body)

    def test_install_skill_builds_and_replaces_existing_install(self) -> None:
        build_output_root = self.remember_temp_dir()
        dest_root = self.remember_temp_dir()

        first_install = install_skill_module.install_skill(
            build_output_root=build_output_root,
            dest_root=dest_root,
        )
        install_dir = Path(first_install["install_dir"])
        self.assertTrue((install_dir / "SKILL.md").exists())
        self.assertFalse(first_install["replaced_existing"])

        second_install = install_skill_module.install_skill(
            build_output_root=build_output_root,
            dest_root=dest_root,
            upgrade=True,
        )
        self.assertTrue((install_dir / "agents" / "openai.yaml").exists())
        self.assertTrue(second_install["replaced_existing"])


if __name__ == "__main__":
    unittest.main()
