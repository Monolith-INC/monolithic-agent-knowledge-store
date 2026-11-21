---
name: ingest-docs
description: Ingest people-owned passages from existing project documentation into the knowledge store while skipping generated regions and preserving external edits.
---

# Ingest Project Documentation

Use this skill to extract people-owned prose from existing project documents into curated store facts without re-ingesting generated spans.

## Rules

1. Run `python3.12 scripts/query.py ingest-docs <doc-path> --project <project>` first.
2. Quote only the returned `quoted_passages` as source evidence when curating facts with `query.py curate`.
3. Never re-ingest `skipped_regions` delimited by `<!-- maks:region ... -->` markers.
4. If `status` is `frozen_external_edit` or `frozen`, preserve the existing document text without assuming who authored it and ask the user how to reconcile the conflict before writing.
5. Keep private material, local transcript paths, and raw diagnostic traces out of tracked store records.
