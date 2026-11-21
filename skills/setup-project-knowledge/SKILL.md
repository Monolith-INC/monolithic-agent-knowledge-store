---
name: setup-project-knowledge
description: Set up or migrate a single visible, source-backed five-tier project knowledge store (Project_Knowledge) using stdlib Python 3.12+ with zero MCP dependency.
---

# Setup Project Knowledge

Use this skill to initialize a new project knowledge store or safely migrate an existing legacy store into a single visible store governed by `project-knowledge.json`.

## Steps

1. **Verify Python 3.12+:** Locate a user-provided Python 3.12 or newer interpreter (`python3.12`, `python3`, or `py -3.12` on Windows). If none is available, stop and tell the user to install Python 3.12+ (do not provision a private Python or MCP server).
2. **Choose store location and Git tracking:**
   - Offer `Project_Knowledge` at the project root as the default, or accept any valid visible in-project relative path. Reject paths that escape the project root, follow symlinks outside the project, or contain hidden ancestor segments (`.`-prefixed).
   - For Git repositories, offer Git tracking as the default, with a local-only option (adds the store path to `.gitignore`).
   - Confirm the project's documentation language (default: `en`) so the generated query guide (`QUERY_GUIDE.md`) and sourced glossary (`glossary.md`) match the project's docs.
3. **Detect conflicts and legacy stores (`AGE-90`):**
   - Run `python3.12 <plugin-root>/scripts/query.py check-locator --project <project-root>`.
   - If multiple conflicting store paths exist across `project-knowledge.json`, `.project-knowledge.json`, or `.monolithic-code-review/sources.json`, stop and ask the user which single store to bring forward — never create a second active store.
   - When migrating a legacy hidden store, run `python3.12 <plugin-root>/scripts/query.py migrate --project <project-root> --from <legacy-path> --root <visible-root> --language <lang>`. This copies, verifies content and lineage, rebuilds `catalog.tsv`, and preserves the legacy folder as an inactive recovery copy.
4. **Initialize and verify non-empty store (`AGE-115` Scenario 1):**
   - For a fresh store, run `python3.12 <plugin-root>/scripts/query.py setup --project <project-root> --root <visible-root> --language <lang> [--local-only]`.
   - Check `catalog` (`python3.12 <plugin-root>/scripts/query.py catalog --project <project-root>`). **Do not report setup as complete while the store holds 0 curated units** — immediately proceed to `discover-project-knowledge` (or ask the user to authorize running it) to populate the store from verified project sources.
