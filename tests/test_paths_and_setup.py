"""Tests for visible store paths, locator conflict refusal, fresh setup, spaces, and migration."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from maks import Err, Ok  # noqa: E402
from maks.paths import DEFAULT_STORE_DIR, LOCATOR_FILE, inspect_locators, validate_visible_store_path  # noqa: E402
from maks.setup import migrate_store, setup_store  # noqa: E402


class PathsAndSetupTest(unittest.TestCase):
    def test_fresh_git_and_non_git_setup_with_spaces(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maks test space ") as tmp:
            project = Path(tmp) / "my project"
            project.mkdir()

            # Non-Git fresh setup with default visible Project_Knowledge
            res = setup_store(project, language="pt")
            self.assertIsInstance(res, Ok)
            assert isinstance(res, Ok)
            self.assertEqual(res.value["knowledgeRoot"], DEFAULT_STORE_DIR)
            self.assertEqual(res.value["tracked"], True)
            self.assertEqual(res.value["needs_population"], True)
            self.assertTrue((project / LOCATOR_FILE).is_file())
            self.assertIn("Guia de Consulta", (project / DEFAULT_STORE_DIR / "QUERY_GUIDE.md").read_text(encoding="utf-8"))
            self.assertIn("Glossário do Projeto", (project / DEFAULT_STORE_DIR / "glossary.md").read_text(encoding="utf-8"))
            self.assertFalse((project / DEFAULT_STORE_DIR / ".locks").exists())

            # Git local-only setup adds .gitignore rule
            git_project = Path(tmp) / "git repo with spaces"
            (git_project / ".git").mkdir(parents=True)
            (git_project / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            res_local = setup_store(git_project, rel_root="Docs Knowledge/Store", language="en", local_only=True)
            self.assertIsInstance(res_local, Ok)
            assert isinstance(res_local, Ok)
            self.assertEqual(res_local.value["tracked"], False)
            self.assertIn("/Docs Knowledge/Store/", (git_project / ".gitignore").read_text(encoding="utf-8"))

    def test_rejects_escaping_paths_hidden_ancestors_and_escaping_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            outside = Path(tmp) / "outside"
            project.mkdir()
            outside.mkdir()

            for bad in ("../outside", "/etc/knowledge", ".hidden/store", "docs/.secret/store", ""):
                res = validate_visible_store_path(project, bad)
                self.assertIsInstance(res, Err, f"Expected error for {bad!r}")

            if os.name != "nt":
                link = project / "linked_out"
                link.symlink_to(outside)
                res_link = validate_visible_store_path(project, "linked_out/store")
                self.assertIsInstance(res_link, Err)
                assert isinstance(res_link, Err)
                self.assertEqual(res_link.code, "symlink_escape")

    def test_conflicting_store_locations_fail_without_creating_second_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / LOCATOR_FILE).write_text(json.dumps({"knowledgeRoot": "Project_Knowledge"}), encoding="utf-8")
            review_dir = project / ".monolithic-code-review"
            review_dir.mkdir()
            (review_dir / "sources.json").write_text(
                json.dumps({"knowledge": {"root": "Other_Knowledge"}}), encoding="utf-8"
            )
            res = inspect_locators(project)
            self.assertIsInstance(res, Err)
            assert isinstance(res, Err)
            self.assertEqual(res.code, "locator_conflict")
            self.assertFalse((project / "Other_Knowledge").exists())

    def test_migration_verifies_preserves_recovery_copy_and_survives_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            legacy = project / ".project-knowledge" / "knowledge"
            (legacy / "rules").mkdir(parents=True)
            unit_text = (
                "---\n"
                "id: rules/sample\n"
                "tier: 4\n"
                "type: rules\n"
                "area: core\n"
                "title: Sample\n"
                "read_when: always\n"
                "provenance: derived\n"
                "sources:\n"
                "  - README.md\n"
                "updated: 2026-11-19\n"
                "version: 1\n"
                "status: current\n"
                "---\n\n"
                "# Sample\n\nLegacy content.\n"
            )
            (legacy / "rules" / "sample.md").write_text(unit_text, encoding="utf-8")
            (project / ".project-knowledge.json").write_text(
                json.dumps({"knowledgeRoot": ".project-knowledge/knowledge"}), encoding="utf-8"
            )

            # Interrupted migration must leave locator untouched and legacy intact
            interrupted = migrate_store(
                project,
                legacy_rel=".project-knowledge/knowledge",
                target_rel="Project_Knowledge",
                simulate_interrupt=True,
            )
            self.assertIsInstance(interrupted, Err)
            self.assertFalse((project / LOCATOR_FILE).exists())
            self.assertTrue((legacy / "rules" / "sample.md").is_file())

            # Successful migration copies, verifies, rebuilds catalog, preserves recovery copy
            migrated = migrate_store(project, legacy_rel=".project-knowledge/knowledge", target_rel="Project_Knowledge")
            self.assertIsInstance(migrated, Ok)
            assert isinstance(migrated, Ok)
            self.assertEqual(migrated.value["verified_files"], 1)
            self.assertTrue((project / "Project_Knowledge" / "rules" / "sample.md").is_file())
            self.assertTrue((project / "Project_Knowledge" / "catalog.tsv").is_file())
            self.assertTrue((legacy / "rules" / "sample.md").is_file(), "Legacy recovery copy must remain intact")

            # Locator now resolves cleanly to visible Project_Knowledge without conflict
            loc = inspect_locators(project)
            self.assertIsInstance(loc, Ok)
            assert isinstance(loc, Ok)
            self.assertEqual(loc.value.active_rel, "Project_Knowledge")


if __name__ == "__main__":
    unittest.main()
