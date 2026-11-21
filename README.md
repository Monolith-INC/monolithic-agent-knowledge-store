# Monolithic Agent Knowledge Store

[![Release](https://img.shields.io/github/v/release/Monolith-INC/monolithic-agent-knowledge-store?display_name=tag&sort=semver)](https://github.com/Monolith-INC/monolithic-agent-knowledge-store/releases/latest)
[![CI](https://img.shields.io/github/actions/workflow/status/Monolith-INC/monolithic-agent-knowledge-store/ci.yml?branch=main&label=CI)](https://github.com/Monolith-INC/monolithic-agent-knowledge-store/actions)
[![License](https://img.shields.io/badge/license-Apache%202.0-lightgrey)](https://github.com/Monolith-INC/monolithic-agent-knowledge-store/blob/main/LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)

A standalone, **Agent Plugins Specification v1.0.0** compliant plugin providing a visible, source-backed, versioned five-tier project knowledge store.

It runs on **user-provided Python 3.12+ using the Python standard library only** — no MCP server, no virtual environment, and no third-party packages required.

---

## Install

**One command.** Run it from a terminal while your application repository is the current directory (or pass `--dest` in CI). You do **not** need to clone this plugin repository.

### Interactive (recommended)

```bash
bash <(curl -fsSL https://github.com/Monolith-INC/monolithic-agent-knowledge-store/releases/latest/download/install.sh)
```

The wizard will:

1. Confirm the target project folder (defaults to your current directory)
2. Ask which agent host(s) to wire (`all-agents`, `claude`, `cursor`, `codex`)
3. Confirm the visible store directory (defaults to `Project_Knowledge`) and documentation language
4. Download the latest release, install the plugin under `<your-app>/.monolithic-agent-knowledge-store/`, wire skills for the selected host(s), and initialize `project-knowledge.json`

### Non-interactive / CI

```bash
curl -fsSL https://github.com/Monolith-INC/monolithic-agent-knowledge-store/releases/latest/download/install.sh \
  | bash -s -- --dest /absolute/path/to/your-app
```

Optional flags: `--target claude|cursor|codex|all-agents`, `--root <visible-dir>`, `--language <lang>`, `--local-only`, `--uninstall`.

Pin a release with `MAKS_VERSION=v0.3.0`. Offline installs can set `MAKS_RELEASE_ZIP=/path/to/monolithic-agent-knowledge-store-*.zip`.

### Requirements

- Python 3.12+ (standard library only; no `pip install` or venv required)
- `bash` and `curl` (or a local zip via `MAKS_RELEASE_ZIP`)

After install, **restart the agent session** in that project so skills reload.

---

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
| `migrate` | Verify and copy a legacy store into a visible store, preserve an inactive recovery copy, and update the single locator. |
| `check-locator` | Verify single-store locator integrity and refuse conflicting store locations. |
| `curate` | Single version-checked write path recording `owner`, `direction`, `origin`, `source`, and `event`; corrections keep the original text immediately before its successor (`obsolete` → `current`). |
| `delete-fact` | Exceptional deletion requiring direct approval for the exact fact, revision, and scope. |
| `validate-lineage` | Verify every unit has at most one `current` revision per `fact_id` and no competing Git merge successors. |
| `orient` / `inject` / `gate` / `session-end` | Agent hook commands for session-start orientation, bounded per-message snippet injection (with deadline), query-first gating with non-blocking fallback, and end-of-session curation reminders. |
| `observe-change` / `refresh-status` / `complete-refresh` / `manual-refresh` | Default-branch refresh handoff (`observed` → `pending` → `completed`, affected-sources-only, idempotent catch-up) and non-Git live source-fingerprint refresh. |
| `ingest-docs` / `publish-docs` / `apply-doc-patch` | Bidirectional doc sync with explicit region markers, checked patches revalidated at apply time, external-edit preservation, and append-only `flow-log.jsonl` recovery. |

See [docs/host-qualification.md](docs/host-qualification.md) for per-host coverage across Claude Code, Codex, and Cursor, and [docs/knowledge-refresh-workflow.yml](docs/knowledge-refresh-workflow.yml) for the reference default-branch refresh workflow.

## Deliberate Design Choices

- **Zero MCP & zero third-party dependencies:** Agents invoke `scripts/query.py` directly using user-provided Python 3.12+.
- **Single visible store & locator:** Defaults to `Project_Knowledge/` and `project-knowledge.json` at the project root; conflicting store locations fail with a diagnostic rather than creating a second store.
- **No hidden `.locks/` directory:** Uses visible `knowledge-write.lock` with portable OS locking on Linux, macOS, and native Windows.
- **Projected current-only reads:** `find` and `fetch` strip `obsolete` and `deprecated` fact revisions *before* ranking and token-budget slicing; pass `--history` when historical lineage is needed.

## Running Tests

```bash
# Owned tests (stdlib Python 3.12+ only)
python3.12 -m unittest discover -s tests -t . -p 'test_*.py' -v

# Unchanged upstream engine tests
PYTHONPATH=vendor/review-knowledge/adapters/knowledge \
  python3.12 -m unittest discover -s vendor/review-knowledge/adapters/knowledge/tests -p 'test_*.py' -v
```
