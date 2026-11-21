---
name: query-project-knowledge
description: Use before broad file reads, architectural decisions, code reviews, or answering project questions to retrieve source-backed project facts from Project_Knowledge (current-only by default, explicit --history).
---

# Query Project Knowledge

Use this skill to retrieve source-backed project facts before reading files broadly, making architectural decisions, or answering project questions.

## Commands

Run all commands with Python 3.12+ against the project root:

- **List routing table (no bodies):**
  `python3.12 <plugin-root>/scripts/query.py catalog --project <project-root>`
- **Search current facts (obsolete revisions excluded before ranking):**
  `python3.12 <plugin-root>/scripts/query.py find --project <project-root> "<search terms>" [--type <type>] [--area <area>] [--limit 8]`
- **Fetch a unit or `#anchor` within a token budget:**
  `python3.12 <plugin-root>/scripts/query.py fetch --project <project-root> <unit-id> [--anchor <slug>] [--max-tokens 1200]`
- **Inspect full revision history (including obsolete/deprecated facts):**
  `python3.12 <plugin-root>/scripts/query.py fetch --project <project-root> <unit-id> --history`
- **Read sourced glossary and aliases:**
  `python3.12 <plugin-root>/scripts/query.py glossary --project <project-root> [--term "<term>"]`
- **Inspect inbound/outbound links:**
  `python3.12 <plugin-root>/scripts/query.py links --project <project-root> <unit-id> [--direction both|out|in]`
- **Rebuild catalog after external changes:**
  `python3.12 <plugin-root>/scripts/query.py rebuild-catalog --project <project-root>`

## Fallback

If the store is empty, missing, stale, or yields no relevant hit, continue with focused primary-source reads and record any durable findings afterward through `discover-project-knowledge` (`query.py curate`).
