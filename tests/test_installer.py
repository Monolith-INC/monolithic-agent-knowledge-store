"""Tests for scripts/install.sh non-interactive/CI offline installation and uninstall."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


def _pack_local_zip(dest_zip: Path) -> None:
    allowlist = [
        "plugin.json",
        "LICENSE",
        "NOTICE",
        "README.md",
        "skills",
        "scripts",
        "vendor",
        "docs/host-qualification.md",
        "docs/knowledge-refresh-workflow.yml",
    ]
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in allowlist:
            p = REPO_ROOT / entry
            if p.is_file():
                zf.write(p, entry)
            elif p.is_dir():
                for child in sorted(p.rglob("*")):
                    if child.is_file() and "__pycache__" not in child.parts and not child.name.endswith(".pyc"):
                        zf.write(child, child.relative_to(REPO_ROOT).as_posix())


@unittest.skipIf(os.name == "nt" or shutil.which("bash") is None, "install.sh requires bash on POSIX")
class InstallerTest(unittest.TestCase):
    def test_non_interactive_offline_install_and_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "monolithic-agent-knowledge-store-0.2.0.zip"
            _pack_local_zip(archive)

            app = tmp_path / "target app"
            app.mkdir()
            # Pre-seed an unpopulated legacy UPF locator and an unrelated user hook to verify safe reconciliation & merge
            (app / ".project-knowledge.json").write_text(
                json.dumps({"schemaVersion": 1, "knowledgeRoot": ".project-knowledge/knowledge"}),
                encoding="utf-8",
            )
            (app / ".claude").mkdir()
            (app / ".claude" / "settings.local.json").write_text(
                json.dumps({"hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "echo user-hook"}]}]}}),
                encoding="utf-8",
            )
            env = {**os.environ, "MAKS_RELEASE_ZIP": str(archive), "MAKS_PYTHON": sys.executable}

            inst = subprocess.run(
                ["bash", str(INSTALL_SH), "--dest", str(app), "--target", "claude", "--root", "Project_Knowledge", "--language", "en"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(inst.returncode, 0, inst.stderr + inst.stdout)
            self.assertTrue((app / ".monolithic-agent-knowledge-store" / "bin" / "maks").is_file())
            self.assertTrue((app / ".monolithic-agent-knowledge-store" / "scripts" / "query.py").is_file())
            skill_text = (app / ".claude" / "skills" / "discover-project-knowledge" / "SKILL.md").read_text(encoding="utf-8")
            self.assertNotIn("<plugin-root>", skill_text)
            self.assertIn(".monolithic-agent-knowledge-store/bin/maks", skill_text)
            self.assertTrue((app / ".claude" / "skills" / "ingest-docs" / "SKILL.md").is_file())
            self.assertTrue((app / ".claude" / "skills" / "publish-docs" / "SKILL.md").is_file())
            self.assertTrue((app / "project-knowledge.json").is_file())
            self.assertTrue((app / "Project_Knowledge" / "QUERY_GUIDE.md").is_file())
            # Hooks merged non-destructively (preserving unrelated user hook)
            settings = json.loads((app / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            self.assertEqual(len(settings["hooks"]["PreToolUse"]), 2)
            self.assertEqual(len(settings["hooks"]["SessionStart"]), 1)

            uninst = subprocess.run(
                ["bash", str(INSTALL_SH), "--dest", str(app), "--target", "claude", "--uninstall"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(uninst.returncode, 0, uninst.stderr + uninst.stdout)
            self.assertFalse((app / ".monolithic-agent-knowledge-store").exists())
            self.assertFalse((app / ".claude" / "skills" / "query-project-knowledge").exists())
            self.assertFalse((app / ".claude" / "skills" / "ingest-docs").exists())
            self.assertFalse((app / ".claude" / "skills" / "publish-docs").exists())
            # Unrelated user hook preserved, MAKS hooks removed
            settings_after = json.loads((app / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            self.assertEqual(len(settings_after["hooks"]["PreToolUse"]), 1)
            self.assertNotIn("SessionStart", settings_after["hooks"])
            # Uninstall must preserve user knowledge data
            self.assertTrue((app / "Project_Knowledge" / "QUERY_GUIDE.md").is_file())


if __name__ == "__main__":
    unittest.main()
