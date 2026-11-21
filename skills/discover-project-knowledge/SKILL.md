---
name: discover-project-knowledge
description: Populate and curate the five-tier project knowledge store from verified repository sources using the single version-checked query.py curate write path.
---

# Discover Project Knowledge

Use this skill to derive durable, source-backed project facts from repository evidence and record them in the five-tier knowledge store (`identity`, `structure`, `mechanics`, `rules`, `evolution`).

## Rules

1. **Verify the active store first:** Run `python3.12 <plugin-root>/scripts/query.py check-locator --project <project-root>`. If no store is configured, run `setup-project-knowledge` first.
2. **Write exclusively through `query.py curate`:**
   - Never bypass version tokens or lineage validation with raw file edits or shell redirects to unit Markdown files.
   - Always fetch the unit's current `version` token first (`query.py fetch <unit_id>`) or pass `--if-version new` for a new unit.
   - Every curated fact must record `--owner`, `--direction`, `--origin`, `--source`, and `--event`.
3. **Preserve fact history:**
   - When correcting an existing fact, pass its existing `--fact-id` and current `--if-version`; `query.py curate` keeps the original text marked `obsolete` immediately before the new `current` revision.
   - Never delete facts during ordinary discovery. Record open questions explicitly rather than guessing unverified details.
4. **Update the sourced glossary and verify lineage:**
   - Record domain terms and aliases with their source references in `glossary.md`.
   - Finish by running `python3.12 <plugin-root>/scripts/query.py validate-lineage --project <project-root>` and `catalog` to confirm the store is populated and conflict-free.
