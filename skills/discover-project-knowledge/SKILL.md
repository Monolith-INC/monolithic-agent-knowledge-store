---
name: discover-project-knowledge
description: Populate and curate the five-tier project knowledge store from verified repository sources using the single version-checked query.py curate write path.
---

# Discover Project Knowledge

Use this skill to derive durable, source-backed project facts from repository evidence and record them in the five-tier knowledge store (`identity`, `structure`, `mechanics`, `rules`, `evolution`).

## Five-Tier Coverage Checklist

Cover every tier that has verifiable evidence in the repository (skip absent domains rather than inventing):
1. **Tier 1 — Identity (`1-identity/` or `identity/`):** `purpose`, `consumers`, `ownership` (what the system is, who uses it, boundaries).
2. **Tier 2 — Structure (`2-structure/` or `structure/`):** `topology`, `directory-conventions`, `domain-model`, `architecture`, `adr-index`.
3. **Tier 3 — Mechanics (`3-mechanics/` or `mechanics/`):** `stack` (SDKs, package manifests, dependencies), `build-tooling`, `testing` (test suites, coverage gaps), `data`, `contracts`, `runtime-ops` (state, auth, gotchas).
4. **Tier 4 — Rules (`4-rules/` or `rules/`):** `coding-standards` (linter/analyzer configs like `analysis_options.yaml`, `tsconfig.json`, `eslint`), `workflow`, `security-compliance`, `nfr-budgets`.
5. **Tier 5 — Evolution (`5-evolution/` or `evolution/`):** `hotspots`, `tech-debt`, `risks`, `backlog`.

## Rules

1. **Verify the active store first:** Run `python3.12 <plugin-root>/scripts/query.py check-locator --project <project-root>`. If no store is configured, run `setup-project-knowledge` first.
2. **Write exclusively through `query.py curate`:**
   - Never bypass version tokens or lineage validation with raw file edits or shell redirects to unit Markdown files.
   - Always fetch the unit's current `version` token first (`query.py fetch <unit_id>`) or pass `--if-version new` for a new unit.
   - Every curated fact must record `--owner`, `--direction` (`stated` for explicit docs/specs; `derived` for code/config observations), `--origin`, `--event`, and **repeatable `--source <path>`** (one resolvable file/dir path per `--source` flag — never pack multiple paths into one string!).
   - Pass repeatable `--link <unit-id>` to connect related units with `[[unit-id]]` links, and `--open-questions "<text>"` when ambiguity remains.
3. **Preserve fact history:**
   - When correcting an existing fact, pass its existing `--fact-id` and current `--if-version`; `query.py curate` keeps the original text marked `obsolete` immediately before its successor (`obsolete` → `current`).
   - Never delete facts during ordinary discovery. Record open questions explicitly rather than guessing unverified details.
4. **Update the sourced glossary via CLI and verify lineage:**
   - Record domain terms and aliases with `python3.12 <plugin-root>/scripts/query.py curate-glossary --project <project-root> --term "<term>" --definition "<def>" --source "<path>" [--alias "<alias>"]`.
   - Finish by running `python3.12 <plugin-root>/scripts/query.py validate-lineage --project <project-root>`, `manual-refresh`, and `catalog` to confirm the store is populated, fingerprintable, and conflict-free.
