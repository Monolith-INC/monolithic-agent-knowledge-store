"""Tests for ingest-docs, publish-docs, apply-doc-patch, and flow-log recovery."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_PY = REPO_ROOT / "scripts" / "query.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from maks import Err, Ok  # noqa: E402
from maks.curation import curate_fact  # noqa: E402
from maks.doc_sync import FLOW_LOG_NAME, apply_doc_patch, ingest_docs, publish_docs  # noqa: E402
from maks.retrieval import open_store  # noqa: E402
from maks.setup import setup_store  # noqa: E402


class DocSyncTest(unittest.TestCase):
    def _setup_project_with_fact(self, project: Path) -> tuple[Path, Path]:
        res = setup_store(project)
        self.assertIsInstance(res, Ok)
        store_root = project / "Project_Knowledge"
        c = curate_fact(
            open_store(store_root),
            unit_id="rules/auth",
            fact_id="auth-token",
            text="Tokens expire after 15 minutes.",
            owner="store",
            direction="derived",
            origin="docs/architecture.md",
            source="src/auth.py",
            event="initial",
            if_version="new",
            title="Auth Rules",
        )
        self.assertIsInstance(c, Ok)
        doc = project / "docs" / "architecture.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(
            "# Architecture\n\n"
            "People-owned overview paragraph.\n\n"
            '<!-- maks:region id="auth-summary" facts="rules/auth:auth-token" -->\n'
            "placeholder\n"
            "<!-- /maks:region -->\n\n"
            "Closing human note.\n",
            encoding="utf-8",
        )
        return store_root, doc

    def test_publish_apply_roundtrip_and_ingest_skips_generated_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "app"
            project.mkdir()
            store_root, doc = self._setup_project_with_fact(project)

            pub = publish_docs(project, store_root, "docs/architecture.md", flow_id="flow-pub-1")
            self.assertIsInstance(pub, Ok)
            self.assertEqual(pub.value["status"], "patch_ready")
            patch = pub.value["patch"]

            # Automatic writes require a qualified destination
            unqual = apply_doc_patch(project, store_root, patch, qualified_destination=False)
            self.assertIsInstance(unqual, Err)
            self.assertEqual(unqual.code, "unqualified_destination")

            applied = apply_doc_patch(project, store_root, patch, qualified_destination=True)
            self.assertIsInstance(applied, Ok)
            self.assertEqual(applied.value["status"], "applied")
            self.assertIn("Tokens expire after 15 minutes.", doc.read_text(encoding="utf-8"))

            # Ingest quotes people-owned passages and skips the generated region
            ing = ingest_docs(project, store_root, "docs/architecture.md", flow_id="flow-ing-1")
            self.assertIsInstance(ing, Ok)
            self.assertEqual(ing.value["status"], "completed")
            self.assertEqual(ing.value["skipped_regions"], ["auth-summary"])
            self.assertEqual(ing.value["external_edits"], [])
            quotes = "\n".join(p["quote"] for p in ing.value["quoted_passages"])
            self.assertIn("People-owned overview paragraph.", quotes)
            self.assertIn("Closing human note.", quotes)
            self.assertNotIn("Tokens expire after 15 minutes.", quotes)

            # Replaying completed flow_id converges without duplicating
            ing_again = ingest_docs(project, store_root, "docs/architecture.md", flow_id="flow-ing-1")
            self.assertIsInstance(ing_again, Ok)
            self.assertEqual(ing_again.value["status"], "already_completed")

    def test_external_edit_preserved_revalidation_blocks_stale_patch_and_recovery_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "app"
            project.mkdir()
            store_root, doc = self._setup_project_with_fact(project)

            pub1 = publish_docs(project, store_root, "docs/architecture.md", flow_id="flow-1")
            self.assertIsInstance(pub1, Ok)
            self.assertIsInstance(apply_doc_patch(project, store_root, pub1.value["patch"], qualified_destination=True), Ok)

            # Simulate an external edit inside the published region
            edited = doc.read_text(encoding="utf-8").replace(
                "Tokens expire after 15 minutes.",
                "Tokens expire after 30 minutes (manual hotfix).",
            )
            doc.write_text(edited, encoding="utf-8")

            # Both publish and ingest detect external edit, freeze, and preserve text without assuming authorship
            pub_frozen = publish_docs(project, store_root, "docs/architecture.md", flow_id="flow-frozen")
            self.assertIsInstance(pub_frozen, Ok)
            self.assertEqual(pub_frozen.value["status"], "frozen_external_edit")
            self.assertEqual(pub_frozen.value["external_edits"][0]["authorship"], "unknown")
            self.assertIn("manual hotfix", pub_frozen.value["external_edits"][0]["preserved_text"])

            ing_frozen = ingest_docs(project, store_root, "docs/architecture.md", flow_id="flow-ing-frozen")
            self.assertIsInstance(ing_frozen, Ok)
            self.assertEqual(ing_frozen.value["status"], "frozen_external_edit")

            # Stale patch rejected at apply time when destination version changed
            stale_apply = apply_doc_patch(project, store_root, pub1.value["patch"], qualified_destination=True)
            self.assertIsInstance(stale_apply, Err)
            self.assertEqual(stale_apply.code, "destination_version_mismatch")

            # Simulate interruption AFTER target write but BEFORE completion log entry
            doc.write_text(pub1.value["patch"]["proposed_content"], encoding="utf-8")
            rec_patch = dict(pub1.value["patch"])
            rec_patch["flow_id"] = "flow-crash-after-write"
            recovered = apply_doc_patch(project, store_root, rec_patch, qualified_destination=True)
            self.assertIsInstance(recovered, Ok)
            self.assertEqual(recovered.value["status"], "recovered_after_write")

            # Flow log excludes private paths and raw diagnostics
            log_text = (store_root / FLOW_LOG_NAME).read_text(encoding="utf-8")
            self.assertNotIn(str(project), log_text)
            self.assertNotIn("Traceback", log_text)

    def test_cli_doc_sync_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "app"
            project.mkdir()
            self._setup_project_with_fact(project)

            out = subprocess.run(
                [sys.executable, str(QUERY_PY), "publish-docs", "docs/architecture.md", "--project", str(project)],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(out.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "patch_ready")

            patch_file = project / "patch.json"
            patch_file.write_text(json.dumps(payload["patch"]), encoding="utf-8")
            app_out = subprocess.run(
                [
                    sys.executable,
                    str(QUERY_PY),
                    "apply-doc-patch",
                    str(patch_file),
                    "--qualified-destination",
                    "--project",
                    str(project),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(app_out.stdout)["status"], "applied")


if __name__ == "__main__":
    unittest.main()
