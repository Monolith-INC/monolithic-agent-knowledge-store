# Monolithic Agent Knowledge Store

A standalone, **Agent Plugins Specification v1.0.0** compliant plugin providing a visible, source-backed, versioned five-tier project knowledge store.

It runs on **user-provided Python 3.12+ using the Python standard library only** — no UPF runtime, no MCP server, no virtual environment, and no third-party packages required.

## Quick Start

```bash
# 1. Set up a visible knowledge store (defaults to Project_Knowledge/ at project root)
python3.12 scripts/query.py setup --project /path/to/project --language en

# 2. Curate a fact through the single version-checked write path
python3.12 scripts/query.py curate --project /path/to/project \
  --unit rules/architecture \
  --fact-id arch.storage \
  --title "Architecture rules" \
  --tier 4 --type rules --area architecture \
  --owner store --direction derived --origin discovery \
  --source "README.md" --event "initial-discovery" \
  --text "All state persists as visible Markdown files." \
  --if-version new

# 3. Query current facts (obsolete revisions are excluded before ranking and fetch)
python3.12 scripts/query.py catalog --project /path/to/project
python3.12 scripts/query.py find --project /path/to/project "visible Markdown"
python3.12 scripts/query.py fetch --project /path/to/project rules/architecture
python3.12 scripts/query.py fetch --project /path/to/project rules/architecture --history
python3.12 scripts/query.py glossary --project /path/to/project
python3.12 scripts/query.py links --project /path/to/project rules/architecture
python3.12 scripts/query.py rebuild-catalog --project /path/to/project
python3.12 scripts/query.py validate-lineage --project /path/to/project
```

## Commands (`scripts/query.py`)

| Command | Purpose |
| --- | --- |
| `catalog` | List current units from the store's routing table (no unit bodies). |
| `find <terms>` | BM25 search over **current** fact sections (excludes obsolete/deprecated revisions before ranking). Pass `--history` to search full text. |
| `fetch <unit_id>` | Fetch a unit or `#anchor` within a token budget (`--max-tokens`), excluding obsolete/deprecated revisions by default. Pass `--history` to inspect full revision history. |
| `glossary` | Read the sourced project glossary (`glossary.md`) and term aliases. |
| `links <unit_id>` | Inspect outbound and inbound `[[unit-id]]` links (`--direction out\|in\|both`). |
| `rebuild-catalog` | Deterministically rebuild `catalog.tsv` from the store files. |
| `setup` | Create and locate one visible store (`Project_Knowledge` by default or custom visible path), write `project-knowledge.json`, configure Git tracking or local-only `.gitignore`, and generate `QUERY_GUIDE.md` and `glossary.md` in the documentation language. |
| `migrate` | Verify and copy a legacy store (e.g., `.project-knowledge/knowledge`) into a visible store, preserve an inactive recovery copy, and update the single locator. |
| `curate` | Single version-checked write path recording `owner`, `direction`, `origin`, `source`, and `event`; corrections keep the original text immediately before its successor (`obsolete` → `current`). |
| `validate-lineage` | Verify every unit has at most one `current` revision per `fact_id` and no corrupted/competing Git merge successors. |

## Deliberate Differences from Legacy MCP Runtime

- **No MCP server (`mcp.json`) and no private Python provisioning:** Agents invoke `scripts/query.py` directly using the user's Python 3.12+.
- **Visible store & locator by default:** Defaults to `Project_Knowledge/` and a single visible `project-knowledge.json` at the project root instead of hidden `.project-knowledge/` and `.project-knowledge.json`.
- **No hidden `.locks/` directory:** Uses the upstream engine's visible `knowledge-write.lock` file (`Monolith-INC/monolithic-code-review-toolkit` PR #10) with portable OS locking on Linux, macOS, and native Windows.
- **Projected current-only reads:** `find` and `fetch` strip `obsolete` and `deprecated` fact revisions *before* ranking and token-budget slicing; pass `--history` when historical lineage is needed.

## Running Tests

```bash
# Owned tests (stdlib Python 3.12+ only)
python3.12 -m unittest discover -s tests -t . -p 'test_*.py' -v

# Unchanged upstream engine tests
PYTHONPATH=vendor/review-knowledge/adapters/knowledge \
  python3.12 -m unittest discover -s vendor/review-knowledge/adapters/knowledge/tests -p 'test_*.py' -v
```
