"""Tests for version-checked curation, conflicts, Git merge lineage checks, and approval-gated delete."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from maks import Err, Ok  # noqa: E402
from maks.curation import curate_fact, delete_fact_revision, validate_unit_lineage  # noqa: E402
from maks.retrieval import open_store  # noqa: E402


class CurationTest(unittest.TestCase):
    def test_stale_version_conflict_and_original_before_successor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = open_store(Path(tmp))
            first = curate_fact(
                store,
                unit_id="rules/auth",
                fact_id="auth.token",
                text="Tokens expire in 1h.",
                owner="store",
                direction="derived",
                origin="discovery",
                source="src/auth.py",
                event="discover",
                if_version="new",
            )
            self.assertIsInstance(first, Ok)
            assert isinstance(first, Ok)

            # Second write succeeds with current version
            second = curate_fact(
                store,
                unit_id="rules/auth",
                fact_id="auth.token",
                text="Tokens expire in 15m.",
                owner="store",
                direction="derived",
                origin="review",
                source="src/auth.py",
                event="tighten-ttl",
                if_version=first.value["version"],
            )
            self.assertIsInstance(second, Ok)

            # Competing write with stale version token is rejected with version_conflict
            stale = curate_fact(
                store,
                unit_id="rules/auth",
                fact_id="auth.token",
                text="Tokens expire in 24h.",
                owner="store",
                direction="derived",
                origin="stale-agent",
                source="src/auth.py",
                event="stale-edit",
                if_version=first.value["version"],
            )
            self.assertIsInstance(stale, Err)
            assert isinstance(stale, Err)
            self.assertEqual(stale.code, "version_conflict")

            # Lineage is valid and original precedes successor
            raw = store.unit("rules/auth").body
            self.assertEqual(validate_unit_lineage("rules/auth", raw), ())
            self.assertLess(raw.index("Tokens expire in 1h."), raw.index("Tokens expire in 15m."))

    def test_competing_git_merge_successors_detected_and_block_curation(self) -> None:
        merged_body = (
            "# Auth\n\n"
            "### fact:auth.token [rev:1 status:obsolete]\n"
            "- owner: store\n- direction: derived\n- origin: discovery\n- source: a.py\n- event: init\n\n"
            "Original 1h.\n\n"
            "### fact:auth.token [rev:2 status:current]\n"
            "- owner: store\n- direction: derived\n- origin: branch-a\n- source: a.py\n- event: edit-a\n\n"
            "Branch A 15m.\n\n"
            "### fact:auth.token [rev:3 status:current]\n"
            "- owner: store\n- direction: derived\n- origin: branch-b\n- source: a.py\n- event: edit-b\n\n"
            "Branch B 30m.\n"
        )
        issues = validate_unit_lineage("rules/auth", merged_body)
        self.assertTrue(any("competing current revisions" in msg for msg in issues))

    def test_exceptional_delete_requires_exact_fact_revision_and_scope_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = open_store(Path(tmp))
            created = curate_fact(
                store,
                unit_id="rules/temp",
                fact_id="temp.note",
                text="Sensitive accidental paste.",
                owner="store",
                direction="derived",
                origin="manual",
                source="notes.md",
                event="init",
                if_version="new",
            )
            assert isinstance(created, Ok)

            # Wrong approval token refused
            denied = delete_fact_revision(
                store,
                unit_id="rules/temp",
                fact_id="temp.note",
                revision=1,
                scope="active-store",
                approval="yes delete it",
                if_version=created.value["version"],
            )
            self.assertIsInstance(denied, Err)
            assert isinstance(denied, Err)
            self.assertEqual(denied.code, "approval_required")

            # Exact approval token for active-store succeeds
            approved = delete_fact_revision(
                store,
                unit_id="rules/temp",
                fact_id="temp.note",
                revision=1,
                scope="active-store",
                approval="DELETE rules/temp:temp.note:rev1:active-store",
                if_version=created.value["version"],
            )
            self.assertIsInstance(approved, Ok)
            self.assertNotIn("Sensitive accidental paste.", store.unit("rules/temp").body)


if __name__ == "__main__":
    unittest.main()
