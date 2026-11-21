---
name: refresh-project-knowledge
description: Recover pending default-branch refresh handoffs or run a non-Git source-fingerprint refresh, updating affected units through query.py curate without overwriting fact history.
---

# Refresh Project Knowledge

Use this skill to keep curated facts current after default-branch changes (merges or direct pushes) or working-tree edits in Git and non-Git projects.

## Steps

1. **Check pending handoffs:**
   `python3.12 <plugin-root>/scripts/query.py refresh-status --project <project-root>`
2. **Run on-demand fingerprint check (works without Git and with working-tree edits):**
   `python3.12 <plugin-root>/scripts/query.py manual-refresh --project <project-root>`
   - Inspect `stale_units` (source file fingerprint changed) and `unverified_units` (missing/unreadable source — never automatically published).
3. **Verify and curate affected units only:**
   - Read the changed primary sources for each affected unit.
   - Update only warranted facts through `scripts/query.py curate` using the unit's current `--if-version` token (preserving obsolete text immediately before its successor).
   - If a source-only check shows no affected facts, complete as a no-op.
4. **Mark handoff completed:**
   `python3.12 <plugin-root>/scripts/query.py complete-refresh --project <project-root> --event-id <id> --revision <sha> --order <n>`
