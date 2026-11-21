---
name: publish-docs
description: Publish active project knowledge facts into explicit marked regions of existing project documentation using revalidated, version-bound patches.
---

# Publish Project Documentation

Use this skill to update explicit `<!-- maks:region id="..." facts="unit:fact" -->` regions in existing project documentation from current store facts.

## Rules

1. Run `python3.12 scripts/query.py publish-docs <doc-path> --project <project>` to generate a checked patch bound to active fact revisions, the region mapping digest, and the current destination document version.
2. If `status` is `frozen_external_edit` or `frozen`, stop and preserve the existing document text without assuming authorship.
3. Apply the patch only to a qualified destination via `python3.12 scripts/query.py apply-doc-patch <patch.json> --qualified-destination --project <project>`, which revalidates all three preconditions at apply time.
4. On interruption, re-run with the same `flow_id` so the append-only `flow-log.jsonl` converges without duplicating flows or overwriting external edits.
