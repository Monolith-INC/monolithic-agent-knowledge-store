# Host Qualification Matrix

This document records per-host, per-action coverage for active knowledge retrieval, bounded prompt injection, query-first gating, and fallback behavior across **Claude Code**, **Codex**, and **Cursor**.

## Latency & Injection Budget

- **Default per-message injection budget:** `max_chars = 1200`, `deadline_ms = 800`, `limit = 3` snippets (`scripts/query.py inject`).
- **Timeout / empty fallback:** If lookup exceeds `deadline_ms` or returns zero hits, `inject` returns `snippets: []` while preserving the task-query reminder (`DEFAULT_REMINDER`).
- **Gate non-looping rule:** An automatic `inject` lookup or bare `catalog` listing never satisfies `gate`; only an observed `find` or `fetch` query (or an explicit fallback condition: missing/unconfigured store, 0 curated units) satisfies it.

## Per-Host Coverage Matrix

| Surface / Action | Claude Code | Codex | Cursor |
| --- | --- | --- | --- |
| **Session-start orientation (`query.py orient`)** | Supported (`SessionStart` hook) | Supported (`SessionStart` hook) | Supported (`sessionStart` hook) |
| **Per-message bounded snippets + reminder (`query.py inject`)** | Supported (`UserPromptSubmit` hook injects context before model turn) | Supported (`UserPromptSubmit` hook injects context) | **Instructions-only / Verify host version** (submit hook provides submit decision + user message; context injection must be verified on target Cursor build before claiming enforced delivery) |
| **Query observation (`find` / `fetch` recorded per session)** | Supported (`scripts/query.py` records observed queries per `(project, session_id)`) | Supported (`scripts/query.py` records observed queries per `(project, session_id)`) | Supported (`scripts/query.py` records observed queries per `(project, session_id)`) |
| **Enforced query-first gate on shell / tool calls (`query.py gate`)** | Supported (`PreToolUse` matcher for `Read`, `Grep`, `Glob`, `Edit`, `Write`, `Bash`) | Partial (`PreToolUse` covers shell/`apply_patch` local tools; generic file-read matcher is **unsupported** — instructions-only for direct file reads) | Partial (documented tool hooks cover supported tools; verify matcher coverage per Cursor version) |
| **Direct project answers with no tool calls** | **Instructions-only** (no pre-response tool interception; governed by orientation + prompt reminder) | **Instructions-only** | **Instructions-only** |
| **Subagent handoffs** | Supported when subagent inherits `--session` or starts its own session orientation | Supported via session orientation + `query.py` skill | Supported via session orientation + `query.py` skill |
| **End-of-session curation check (`query.py session-end`)** | Supported (`Stop` / session-end hook) | Supported (`Stop` / checkpoint hook) | Supported via explicit checkpoint / skill |

## Reporting Unsupported Surfaces

Where a host lacks a required hook matcher (for example, generic file-read interception in Codex, direct no-tool answers on all hosts, or pre-turn context injection on Cursor builds without it), setup and documentation report the surface as **instructions-only** rather than claiming enforced interception. The `query-project-knowledge` skill and session-start reminder remain active on every host.
