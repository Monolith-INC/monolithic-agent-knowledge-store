"""Agent hooks: session orientation, bounded per-message injection, query-first gate, and session-end check."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from . import Ok, Result
from .curation import current_facts_view
from .retrieval import SUPPORT_UNIT_IDS, open_store

DEFAULT_INJECT_MAX_CHARS = 1200
DEFAULT_INJECT_DEADLINE_MS = 800
DEFAULT_REMINDER = (
    "Run your own task-specific `.monolithic-agent-knowledge-store/bin/maks find` or `fetch` "
    "before broad project reads, edits, architectural decisions, or project answers."
)

_READ_ONLY_CLI_COMMANDS = frozenset({
    "catalog",
    "find",
    "fetch",
    "glossary",
    "links",
    "check-locator",
    "orient",
    "refresh-status",
    "validate-lineage",
})
_CLI_CMD_RE = re.compile(
    r"(?:query\.py|bin/maks)\s+(?P<subcmd>[a-z][a-z-]+)\b"
)


def _gate_dir() -> Path:
    base = Path(tempfile.gettempdir()) / "maks-gate"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _session_state_path(project_root: Path, session_id: str) -> Path:
    key = hashlib.sha256(f"{project_root.resolve()}::{session_id}".encode("utf-8")).hexdigest()[:24]
    return _gate_dir() / f"{key}.json"


def _active_session_path(project_root: Path) -> Path:
    key = hashlib.sha256(f"{project_root.resolve()}::__active__".encode("utf-8")).hexdigest()[:24]
    return _gate_dir() / f"{key}.active"


def _set_active_session(project_root: Path, session_id: str) -> None:
    p = _active_session_path(project_root)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(session_id, encoding="utf-8", newline="\n")
    tmp.replace(p)


def _get_active_session(project_root: Path) -> str | None:
    p = _active_session_path(project_root)
    if not p.is_file():
        return None
    try:
        val = p.read_text(encoding="utf-8").strip()
        return val or None
    except OSError:
        return None


def _cli_prefix(project_root: Path) -> str:
    launcher = project_root / ".monolithic-agent-knowledge-store" / "bin" / "maks"
    if launcher.is_file():
        return ".monolithic-agent-knowledge-store/bin/maks"
    installed_query = project_root / ".monolithic-agent-knowledge-store" / "scripts" / "query.py"
    if installed_query.is_file():
        return "python3.12 .monolithic-agent-knowledge-store/scripts/query.py"
    return "python3.12 scripts/query.py"


def _read_session_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"observed_queries": [], "curated_writes": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"observed_queries": [], "curated_writes": 0}
    except (OSError, json.JSONDecodeError):
        return {"observed_queries": [], "curated_writes": 0}


def _write_session_state(path: Path, state: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def _append_query_to_session(
    project_root: Path,
    session_id: str,
    entry: dict[str, Any],
) -> None:
    path = _session_state_path(project_root, session_id)
    state = _read_session_state(path)
    entries = list(state.get("observed_queries") or [])
    entries.append(entry)
    state["observed_queries"] = entries[-25:]
    _write_session_state(path, state)


def record_observed_query(
    project_root: Path,
    session_id: str,
    *,
    command: str,
    terms: str | None = None,
    unit_id: str | None = None,
    hit_count: int = 0,
) -> None:
    """Record an agent-initiated task query (`find` or `fetch`); `catalog` and `inject` never satisfy the gate."""
    if command not in {"find", "fetch"}:
        return
    entry = {
        "command": command,
        "terms": terms,
        "unit_id": unit_id,
        "hit_count": hit_count,
        "timestamp": round(time.time(), 3),
    }
    _append_query_to_session(project_root, session_id, entry)
    if session_id == "default":
        active = _get_active_session(project_root)
        if active and active != "default":
            _append_query_to_session(project_root, active, entry)


def record_curated_write(project_root: Path, session_id: str) -> None:
    targets = {session_id}
    if session_id == "default":
        active = _get_active_session(project_root)
        if active:
            targets.add(active)
    for sid in targets:
        path = _session_state_path(project_root, sid)
        state = _read_session_state(path)
        state["curated_writes"] = int(state.get("curated_writes") or 0) + 1
        _write_session_state(path, state)


def is_knowledge_cli_command(action: str, target: str) -> bool:
    """Allow Bash/shell invocations of the knowledge store's own read-only CLI commands to prevent self-deadlock."""
    if action.lower() not in {"bash", "shell", "run_command", "exec"}:
        return False
    m = _CLI_CMD_RE.search(target or "")
    return bool(m and m.group("subcmd") in _READ_ONLY_CLI_COMMANDS)


def cmd_orient(project_root: Path, store_root: Path, *, session_id: str = "default") -> Result[dict[str, Any]]:
    """Session-start orientation: resets session gate state and returns concise store summary."""
    _write_session_state(_session_state_path(project_root, session_id), {"observed_queries": [], "curated_writes": 0})
    _set_active_session(project_root, session_id)

    store = open_store(store_root)
    rows = [r for r in store.catalog() if r["id"] not in SUPPORT_UNIT_IDS]
    areas = sorted({r["area"] for r in rows if r.get("area")})
    cli = _cli_prefix(project_root)
    return Ok({
        "session_id": session_id,
        "store": str(store_root),
        "curated_unit_count": len(rows),
        "areas": areas[:10],
        "empty": len(rows) == 0,
        "reminder": DEFAULT_REMINDER,
        "query_command": f'{cli} find --project "{project_root}" "<terms>"',
    })


def cmd_inject(
    project_root: Path,
    store_root: Path,
    message: str,
    *,
    max_chars: int = DEFAULT_INJECT_MAX_CHARS,
    deadline_ms: int = DEFAULT_INJECT_DEADLINE_MS,
    limit: int = 3,
    session_id: str | None = None,
) -> Result[dict[str, Any]]:
    """Bounded per-message snippet injection with strict character and wall-clock budgets."""
    if session_id:
        _set_active_session(project_root, session_id)
    started = time.monotonic()
    deadline_s = max(deadline_ms, 0) / 1000.0
    if not message.strip() or deadline_ms <= 0:
        return Ok({
            "snippets": [],
            "timed_out": deadline_ms <= 0,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "reminder": DEFAULT_REMINDER,
        })

    store = open_store(store_root)
    hits, _ = store.find(message, status="current", limit=max(1, limit) + len(SUPPORT_UNIT_IDS), view=current_facts_view)
    elapsed_s = time.monotonic() - started
    if elapsed_s > deadline_s:
        return Ok({
            "snippets": [],
            "timed_out": True,
            "elapsed_ms": round(elapsed_s * 1000, 2),
            "reminder": DEFAULT_REMINDER,
        })

    snippets: list[dict[str, Any]] = []
    used = 0
    for hit in hits:
        if hit.unit_id in SUPPORT_UNIT_IDS:
            continue
        if len(snippets) >= max(1, limit):
            break
        remaining = max_chars - used
        if remaining <= 40:
            break
        text = hit.snippet[:remaining]
        used += len(text)
        snippets.append({
            "unit_id": hit.unit_id,
            "anchor": hit.anchor,
            "score": hit.score,
            "snippet": text,
            "provenance": f"{hit.unit_id}#{hit.anchor}" if hit.anchor else hit.unit_id,
        })

    return Ok({
        "snippets": snippets,
        "timed_out": False,
        "chars_used": used,
        "max_chars": max_chars,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        "reminder": DEFAULT_REMINDER,
    })


def cmd_gate(
    project_root: Path,
    store_root: Path | None,
    *,
    session_id: str = "default",
    action: str = "read",
    target: str = "",
) -> Result[dict[str, Any]]:
    """Query-first gate: requires an observed agent `find`/`fetch`, with non-blocking fallback and CLI allowlist."""
    if is_knowledge_cli_command(action, target):
        return Ok({
            "decision": "allow",
            "reason": "knowledge_tool_allowlist",
            "action": action,
            "target": target,
        })

    if store_root is None or not store_root.is_dir():
        return Ok({
            "decision": "allow",
            "reason": "fallback_store_unavailable",
            "guidance": "Knowledge store is unavailable; continue with focused primary-source reads.",
        })

    store = open_store(store_root)
    rows = [r for r in store.catalog() if r["id"] not in SUPPORT_UNIT_IDS]
    if not rows:
        return Ok({
            "decision": "allow",
            "reason": "fallback_store_empty",
            "guidance": "Knowledge store has 0 curated units; continue with focused source reads and curate findings.",
        })

    state = _read_session_state(_session_state_path(project_root, session_id))
    observed = list(state.get("observed_queries") or [])
    if observed:
        return Ok({
            "decision": "allow",
            "reason": "observed_query",
            "observed_count": len(observed),
            "last_query": observed[-1],
        })

    hint_terms = target or action
    cli = _cli_prefix(project_root)
    return Ok({
        "decision": "block",
        "reason": "query_required",
        "action": action,
        "target": target,
        "explanation": (
            f"Run a task-specific knowledge query before `{action}` so decisions stay grounded in current project facts. "
            "Automatic prompt snippets and bare catalog listings do not satisfy this gate."
        ),
        "suggested_command": f'{cli} find --project "{project_root}" --session "{session_id}" "{hint_terms}"',
    })


def cmd_session_end(
    project_root: Path,
    store_root: Path | None,
    *,
    session_id: str = "default",
) -> Result[dict[str, Any]]:
    """End-of-session check for identified but unrecorded durable findings."""
    state = _read_session_state(_session_state_path(project_root, session_id))
    observed = len(state.get("observed_queries") or [])
    curated = int(state.get("curated_writes") or 0)
    needs_curation_check = observed > 0 and curated == 0
    return Ok({
        "session_id": session_id,
        "store": str(store_root) if store_root else None,
        "observed_queries": observed,
        "curated_writes": curated,
        "needs_curation_check": needs_curation_check,
        "reminder": (
            "Review whether any durable decisions or verified findings from this session should be recorded via `curate`."
            if needs_curation_check
            else "No unrecorded session curation gap detected."
        ),
    })
