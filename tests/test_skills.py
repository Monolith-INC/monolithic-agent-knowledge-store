"""Validate Agent Plugins v1.0.0 manifest and skill frontmatter contracts."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = (
    "discover-project-knowledge",
    "query-project-knowledge",
    "refresh-project-knowledge",
    "setup-project-knowledge",
)


class SkillsAndManifestTest(unittest.TestCase):
    def test_root_manifest_conforms_to_agent_plugins_v1(self) -> None:
        manifest = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(manifest["name"], "monolithic-agent-knowledge-store")
        self.assertEqual(manifest["license"], "Apache-2.0")

    def test_all_skills_have_valid_frontmatter_and_no_mcp_tools(self) -> None:
        skills_dir = REPO_ROOT / "skills"
        found = sorted(p.name for p in skills_dir.iterdir() if p.is_dir())
        self.assertEqual(tuple(found), EXPECTED_SKILLS)
        for name in EXPECTED_SKILLS:
            text = (skills_dir / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), f"{name}/SKILL.md must start with YAML frontmatter")
            fm = text.split("\n---", 1)[0]
            self.assertRegex(fm, re.compile(rf"^name:\s*{re.escape(name)}$", re.MULTILINE))
            self.assertRegex(fm, re.compile(r"^description:\s*\S+", re.MULTILINE))
            self.assertNotIn("knowledge_put", text)
            self.assertNotIn("knowledge_add", text)


if __name__ == "__main__":
    unittest.main()
