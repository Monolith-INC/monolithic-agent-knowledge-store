"""End-to-end tests for standalone scripts/query.py retrieval, projection, glossary, and links."""

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


class RetrievalCliTest(unittest.TestCase):
    def test_standalone_query_commands_and_current_vs_history_projection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="maks cli ") as tmp:
            project = Path(tmp) / "project with space"
            project.mkdir()

            code, out = run_cli("setup", "--project", str(project), "--language", "en")
            self.assertEqual(code, 0, out)
            self.assertTrue(out["needs_population"])

            # Add sourced glossary entry with aliases
            glossary_path = project / "Project_Knowledge" / "glossary.md"
            glossary_path.write_text(
                glossary_path.read_text(encoding="utf-8")
                + "| UPF | Unified Plugin Framework, framework | Root plugin framework | README.md |\n",
                encoding="utf-8",
            )

            # Curate rev 1 with an obsolete-only term "zephyrlegacy"
            code, c1 = run_cli(
                "curate", "--project", str(project),
                "--unit", "rules/storage", "--fact-id", "storage.mode",
                "--title", "Storage rules", "--tier", "4", "--type", "rules", "--area", "storage",
                "--owner", "store", "--direction", "derived", "--origin", "discovery",
                "--source", "README.md", "--event", "initial",
                "--text", "Uses zephyrlegacy transport linked to [[identity/overview]].",
                "--if-version", "new",
            )
            self.assertEqual(code, 0, c1)

            # Create linked unit so links() resolves outbound + inbound
            code, c_ov = run_cli(
                "curate", "--project", str(project),
                "--unit", "identity/overview", "--fact-id", "overview.name",
                "--title", "Overview", "--tier", "1", "--type", "identity", "--area", "core",
                "--owner", "people", "--direction", "stated", "--origin", "readme",
                "--source", "README.md", "--event", "initial",
                "--text", "Primary project identity.",
                "--if-version", "new",
            )
            self.assertEqual(code, 0, c_ov)

            # Correct storage.mode to rev 2 replacing zephyrlegacy with stdlibpython
            code, c2 = run_cli(
                "curate", "--project", str(project),
                "--unit", "rules/storage", "--fact-id", "storage.mode",
                "--owner", "store", "--direction", "derived", "--origin", "decision",
                "--source", "ADR-002.md", "--event", "retire-mcp",
                "--text", "Uses stdlibpython CLI linked to [[identity/overview]].",
                "--if-version", c1["version"],
            )
            self.assertEqual(code, 0, c2)
            self.assertEqual(c2["revision"], 2)

            # Verify no hidden .locks folder created inside store
            self.assertFalse((project / "Project_Knowledge" / ".locks").exists())

            # Ordinary find excludes obsolete term "zephyrlegacy" BEFORE ranking
            code, f_old = run_cli("find", "--project", str(project), "zephyrlegacy")
            self.assertEqual(code, 0, f_old)
            self.assertEqual(f_old["hits"], [])

            # Ordinary find matches current term "stdlibpython"
            code, f_cur = run_cli("find", "--project", str(project), "stdlibpython")
            self.assertEqual(code, 0, f_cur)
            self.assertEqual(len(f_cur["hits"]), 1)
            self.assertEqual(f_cur["hits"][0]["unit_id"], "rules/storage")

            # History find surfaces obsolete term
            code, f_hist = run_cli("find", "--project", str(project), "zephyrlegacy", "--history")
            self.assertEqual(code, 0, f_hist)
            self.assertEqual(len(f_hist["hits"]), 1)

            # Ordinary fetch excludes obsolete text; --history preserves obsolete text before successor
            code, fetch_cur = run_cli("fetch", "--project", str(project), "rules/storage")
            self.assertEqual(code, 0, fetch_cur)
            self.assertNotIn("zephyrlegacy", fetch_cur["content"])
            self.assertIn("stdlibpython", fetch_cur["content"])

            code, fetch_hist = run_cli("fetch", "--project", str(project), "rules/storage", "--history")
            self.assertEqual(code, 0, fetch_hist)
            self.assertIn("zephyrlegacy", fetch_hist["content"])
            self.assertLess(fetch_hist["content"].index("zephyrlegacy"), fetch_hist["content"].index("stdlibpython"))

            # Catalog, glossary (by alias), links, rebuild-catalog, validate-lineage
            code, cat = run_cli("catalog", "--project", str(project))
            self.assertEqual(code, 0, cat)
            self.assertEqual(cat["count"], 2)

            code, gloss = run_cli("glossary", "--project", str(project), "--term", "Unified Plugin")
            self.assertEqual(code, 0, gloss)
            self.assertEqual(gloss["count"], 1)
            self.assertEqual(gloss["entries"][0]["term"], "UPF")

            code, links = run_cli("links", "--project", str(project), "identity/overview", "--direction", "in")
            self.assertEqual(code, 0, links)
            self.assertEqual(links["in"], ["rules/storage"])

            code, reb = run_cli("rebuild-catalog", "--project", str(project))
            self.assertEqual(code, 0, reb)
            self.assertEqual(reb["unit_count"], 2)

            code, val = run_cli("validate-lineage", "--project", str(project))
            self.assertEqual(code, 0, val)
            self.assertEqual(val["issues"], [])


if __name__ == "__main__":
    unittest.main()
