"""Tests for session orientation, bounded injection, query-first gate, fallback, and session-end checks."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

QUERY_PY = Path(__file__).resolve().parents[1] / "scripts" / "query.py"


def run_cli(*args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(QUERY_PY), *args], capture_output=True, text=True, check=False)
    stream = proc.stdout.strip() or proc.stderr.strip()
    return proc.returncode, json.loads(stream)


class AgentHooksTest(unittest.TestCase):
    def test_orient_inject_gate_and_session_end_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "app"
            project.mkdir()

            # Unconfigured store permits fallback without looping
            code, gate_unconf = run_cli("gate", "--project", str(project), "--session", "s1", "--action", "read")
            self.assertEqual(code, 0, gate_unconf)
            self.assertEqual(gate_unconf["decision"], "allow")
            self.assertEqual(gate_unconf["reason"], "fallback_store_unavailable")

            # Empty store also permits fallback
            run_cli("setup", "--project", str(project))
            code, gate_empty = run_cli("gate", "--project", str(project), "--session", "s1", "--action", "read")
            self.assertEqual(code, 0, gate_empty)
            self.assertEqual(gate_empty["decision"], "allow")
            self.assertEqual(gate_empty["reason"], "fallback_store_empty")

            # Curate one unit
            code, _ = run_cli(
                "curate", "--project", str(project), "--session", "setup-s",
                "--unit", "rules/deploy", "--fact-id", "deploy.target",
                "--title", "Deploy rules", "--tier", "4", "--type", "rules", "--area", "ops",
                "--owner", "store", "--direction", "derived", "--origin", "discovery",
                "--source", "README.md", "--event", "init",
                "--text", "Deployments target Cloud Run in us-central1 with zero downtime.",
                "--if-version", "new",
            )
            self.assertEqual(code, 0)

            # Orientation reports store and reminder
            code, orient = run_cli("orient", "--project", str(project), "--session", "s1")
            self.assertEqual(code, 0, orient)
            self.assertEqual(orient["curated_unit_count"], 1)
            self.assertIn("ops", orient["areas"])

            # Automatic inject returns bounded snippet & reminder, and does NOT satisfy the gate
            code, inj = run_cli("inject", "--project", str(project), "Cloud Run deployment", "--max-chars", "200")
            self.assertEqual(code, 0, inj)
            self.assertEqual(len(inj["snippets"]), 1)
            self.assertLessEqual(inj["chars_used"], 200)

            # Timeout fallback preserves reminder
            code, inj_to = run_cli("inject", "--project", str(project), "Cloud Run", "--deadline-ms", "0")
            self.assertEqual(code, 0, inj_to)
            self.assertTrue(inj_to["timed_out"])
            self.assertTrue(inj_to["reminder"])

            # Bare catalog also does NOT satisfy the gate
            run_cli("catalog", "--project", str(project))
            code, gate_blocked = run_cli("gate", "--project", str(project), "--session", "s1", "--action", "edit", "--target", "deploy")
            self.assertEqual(code, 2, gate_blocked)
            self.assertEqual(gate_blocked["decision"], "block")
            self.assertIn("query.py find", gate_blocked["suggested_command"])

            # Running an actual task find satisfies the gate for s1 (even on zero hits, never loops)
            code, _ = run_cli("find", "--project", str(project), "--session", "s1", "Cloud Run")
            self.assertEqual(code, 0)
            code, gate_ok = run_cli("gate", "--project", str(project), "--session", "s1", "--action", "edit", "--target", "deploy")
            self.assertEqual(code, 0, gate_ok)
            self.assertEqual(gate_ok["decision"], "allow")
            self.assertEqual(gate_ok["reason"], "observed_query")

            # Session-end notices queries happened without curation in s1
            code, end = run_cli("session-end", "--project", str(project), "--session", "s1")
            self.assertEqual(code, 0, end)
            self.assertTrue(end["needs_curation_check"])


if __name__ == "__main__":
    unittest.main()
