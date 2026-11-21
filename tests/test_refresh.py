"""Tests for default-branch refresh handoffs (observed/pending/completed) and non-Git manual refresh."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from maks import Ok  # noqa: E402
from maks.curation import curate_fact  # noqa: E402
from maks.refresh import complete_refresh, manual_refresh, observe_change, refresh_status  # noqa: E402
from maks.retrieval import open_store  # noqa: E402
from maks.setup import setup_store  # noqa: E402


class RefreshTest(unittest.TestCase):
    def test_observed_pending_completed_noop_duplicate_and_out_of_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "repo"
            project.mkdir()
            (project / "src").mkdir()
            (project / "src" / "api.py").write_text("v1\n", encoding="utf-8")

            setup_store(project)
            store_root = project / "Project_Knowledge"
            curate_fact(
                open_store(store_root),
                unit_id="mechanics/api",
                fact_id="api.route",
                text="Uses /v1/items.",
                owner="store",
                direction="derived",
                origin="discovery",
                source="src/api.py",
                event="init",
                if_version="new",
            )
            handoff = project / "handoff.json"

            # Unrelated / store-only change produces no-op
            noop = observe_change(store_root, handoff, event_id="ev-1", revision="sha-1", changed_paths=["Project_Knowledge/catalog.tsv"], order=1)
            self.assertIsInstance(noop, Ok)
            assert isinstance(noop, Ok)
            self.assertEqual(noop.value["status"], "noop")

            # Affected source queues pending refresh
            pend = observe_change(store_root, handoff, event_id="ev-2", revision="sha-2", changed_paths=["src/api.py"], order=2)
            self.assertIsInstance(pend, Ok)
            assert isinstance(pend, Ok)
            self.assertEqual(pend.value["status"], "pending")
            self.assertEqual(pend.value["affected_units"], ["mechanics/api"])

            # Duplicate event is ignored idempotently
            dup = observe_change(store_root, handoff, event_id="ev-2", revision="sha-2", changed_paths=["src/api.py"], order=2)
            assert isinstance(dup, Ok)
            self.assertEqual(dup.value["status"], "duplicate_ignored")

            # Complete ev-2 advances completed_revision to sha-2
            done = complete_refresh(handoff, event_id="ev-2", revision="sha-2", order=2)
            assert isinstance(done, Ok)
            self.assertEqual(done.value["completed_revision"], "sha-2")

            # Late/out-of-order event does not move completed_revision backwards
            late = observe_change(store_root, handoff, event_id="ev-old", revision="sha-0", changed_paths=["src/api.py"], order=0)
            assert isinstance(late, Ok)
            self.assertEqual(late.value["status"], "stale_event_ignored")

            status = refresh_status(handoff)
            assert isinstance(status, Ok)
            self.assertEqual(status.value["completed_revision"], "sha-2")
            self.assertEqual(status.value["pending"], [])

    def test_manual_non_git_refresh_detects_stale_and_unverified_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "no-git-project"
            project.mkdir()
            src = project / "config.txt"
            src.write_text("mode=alpha\n", encoding="utf-8")

            setup_store(project)
            store_root = project / "Project_Knowledge"
            curate_fact(
                open_store(store_root),
                unit_id="rules/config",
                fact_id="config.mode",
                text="Mode is alpha.",
                owner="store",
                direction="derived",
                origin="discovery",
                source="config.txt",
                event="init",
                if_version="new",
            )
            snap = project / "snap.json"

            # First run baselines fingerprints
            r1 = manual_refresh(project, store_root, snapshot_path=snap)
            assert isinstance(r1, Ok)
            self.assertEqual(r1.value["stale_units"], [])
            self.assertEqual(r1.value["unverified_units"], [])

            # Working-tree edit detected as stale without Git
            src.write_text("mode=beta\n", encoding="utf-8")
            r2 = manual_refresh(project, store_root, snapshot_path=snap)
            assert isinstance(r2, Ok)
            self.assertEqual(len(r2.value["stale_units"]), 1)
            self.assertEqual(r2.value["stale_units"][0]["unit_id"], "rules/config")

            # Missing source marked unverified with auto_publish_allowed=False
            src.unlink()
            r3 = manual_refresh(project, store_root, snapshot_path=snap)
            assert isinstance(r3, Ok)
            self.assertEqual(len(r3.value["unverified_units"]), 1)
            self.assertFalse(r3.value["unverified_units"][0]["auto_publish_allowed"])


if __name__ == "__main__":
    unittest.main()
