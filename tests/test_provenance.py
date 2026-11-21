"""Verify vendored upstream engine provenance and zero-MCP package boundary."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = REPO_ROOT / "vendor" / "review-knowledge"


class ProvenanceTest(unittest.TestCase):
    def test_vendored_files_match_sha256_provenance_unchanged(self) -> None:
        prov_path = VENDOR_ROOT / "provenance.json"
        self.assertTrue(prov_path.is_file(), "provenance.json must exist")
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
        self.assertEqual(prov["repository"], "https://github.com/Monolith-INC/monolithic-code-review-toolkit")
        self.assertEqual(prov["commit"], "7461aed54f12c050fcff4cb70998d23206721d25")
        self.assertTrue(prov["files"])
        for rel, expected_digest in prov["files"].items():
            file_path = VENDOR_ROOT / rel
            self.assertTrue(file_path.is_file(), f"Missing vendored file: {rel}")
            actual_digest = hashlib.sha256(file_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            self.assertEqual(actual_digest, expected_digest, f"Vendored file modified: {rel}")

    def test_no_mcp_files_shipped(self) -> None:
        self.assertFalse((REPO_ROOT / "mcp.json").exists(), "Standalone store must not ship mcp.json")
        self.assertFalse(
            (VENDOR_ROOT / "adapters" / "knowledge" / "mcrt_knowledge_mcp.py").exists(),
            "Legacy MCP server must not be vendored",
        )


if __name__ == "__main__":
    unittest.main()
