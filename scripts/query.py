#!/usr/bin/env python3.12
"""Standalone stdlib Python 3.12+ CLI for Monolithic Agent Knowledge Store (no MCP)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from maks import Err, Ok, Result  # noqa: E402
from maks.agent_hooks import (  # noqa: E402
    DEFAULT_INJECT_DEADLINE_MS,
    DEFAULT_INJECT_MAX_CHARS,
    cmd_gate,
    cmd_inject,
    cmd_orient,
    cmd_session_end,
    record_curated_write,
    record_observed_query,
)
from maks.curation import curate_fact, delete_fact_revision  # noqa: E402
from maks.paths import DEFAULT_STORE_DIR, inspect_locators  # noqa: E402
from maks.refresh import complete_refresh, default_handoff_path, manual_refresh, observe_change, refresh_status  # noqa: E402
from maks.retrieval import (  # noqa: E402
    cmd_catalog,
    cmd_fetch,
    cmd_find,
    cmd_glossary,
    cmd_links,
    cmd_rebuild_catalog,
    cmd_validate_lineage,
    open_store,
)
from maks.setup import migrate_store, setup_store  # noqa: E402


def _resolve_store(project: Path, explicit_root: str | None) -> Result[Path]:
    state = inspect_locators(project)
    if isinstance(state, Err):
        return state
    if explicit_root:
        candidate = (project / explicit_root).resolve() if not Path(explicit_root).is_absolute() else Path(explicit_root).resolve()
        if state.value.active_path and candidate != state.value.active_path:
            return Err(
                "locator_conflict",
                f"Explicit --root {explicit_root!r} disagrees with active locator {state.value.active_rel!r}.",
            )
        return Ok(candidate)
    if state.value.active_path is None:
        return Err("store_not_configured", "No project knowledge store is configured. Run `query.py setup` first.")
    return Ok(state.value.active_path)


def _emit(result: Result[dict]) -> int:
    match result:
        case Ok(value=payload):
            print(json.dumps({"ok": True, **payload}, indent=2, ensure_ascii=False))
            return 2 if payload.get("decision") == "block" else 0
        case Err(code=code, message=message, detail=detail):
            body = {"ok": False, "error": {"code": code, "message": message, **({"detail": detail} if detail else {})}}
            print(json.dumps(body, indent=2, ensure_ascii=False), file=sys.stderr)
            return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone Project Knowledge Store CLI (stdlib Python 3.12+).")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", default=".", help="Project root directory.")
        p.add_argument("--root", default=None, help="Optional explicit store root (checked against locator).")

    p_cat = sub.add_parser("catalog", help="List current units from the store routing table.")
    add_common(p_cat)
    p_cat.add_argument("--path-prefix", default=None)
    p_cat.add_argument("--type", dest="unit_type", default=None)
    p_cat.add_argument("--updated-after", default=None)

    p_find = sub.add_parser("find", help="Search current fact sections (or full history with --history).")
    add_common(p_find)
    p_find.add_argument("terms", help="Search query terms.")
    p_find.add_argument("--path-prefix", default=None)
    p_find.add_argument("--type", dest="unit_type", default=None)
    p_find.add_argument("--area", default=None)
    p_find.add_argument("--limit", type=int, default=8)
    p_find.add_argument("--history", action="store_true", help="Include obsolete/deprecated revisions.")
    p_find.add_argument("--session", default="default", help="Session ID for query-first gate observation.")

    p_fetch = sub.add_parser("fetch", help="Fetch a unit or anchor (current-only by default).")
    add_common(p_fetch)
    p_fetch.add_argument("unit_id", help="Unit identifier.")
    p_fetch.add_argument("--anchor", default=None)
    p_fetch.add_argument("--start-line", type=int, default=None)
    p_fetch.add_argument("--end-line", type=int, default=None)
    p_fetch.add_argument("--max-tokens", type=int, default=None)
    p_fetch.add_argument("--history", action="store_true", help="Include obsolete/deprecated revisions.")
    p_fetch.add_argument("--session", default="default", help="Session ID for query-first gate observation.")

    p_gloss = sub.add_parser("glossary", help="Read sourced glossary entries and aliases.")
    add_common(p_gloss)
    p_gloss.add_argument("--term", default=None)

    p_links = sub.add_parser("links", help="Inspect outbound and inbound unit links.")
    add_common(p_links)
    p_links.add_argument("unit_id")
    p_links.add_argument("--direction", choices=("out", "in", "both"), default="both")

    p_rebuild = sub.add_parser("rebuild-catalog", help="Rebuild catalog.tsv deterministically.")
    add_common(p_rebuild)

    p_val = sub.add_parser("validate-lineage", help="Validate fact revision lineage across all units.")
    add_common(p_val)

    p_check = sub.add_parser("check-locator", help="Inspect locator configuration and detect conflicts.")
    p_check.add_argument("--project", default=".")

    p_setup = sub.add_parser("setup", help="Initialize a visible project knowledge store.")
    p_setup.add_argument("--project", default=".")
    p_setup.add_argument("--root", default=DEFAULT_STORE_DIR)
    p_setup.add_argument("--language", default="en")
    p_setup.add_argument("--local-only", action="store_true")

    p_mig = sub.add_parser("migrate", help="Verify and migrate a legacy store into a visible store.")
    p_mig.add_argument("--project", default=".")
    p_mig.add_argument("--from", dest="legacy_rel", required=True)
    p_mig.add_argument("--root", default=DEFAULT_STORE_DIR)
    p_mig.add_argument("--language", default="en")
    p_mig.add_argument("--local-only", action="store_true")

    p_cur = sub.add_parser("curate", help="Version-checked curation write path.")
    add_common(p_cur)
    p_cur.add_argument("--unit", required=True)
    p_cur.add_argument("--fact-id", required=True)
    p_cur.add_argument("--text", required=True)
    p_cur.add_argument("--owner", required=True, choices=("people", "store"))
    p_cur.add_argument("--direction", required=True, choices=("stated", "derived"))
    p_cur.add_argument("--origin", required=True)
    p_cur.add_argument("--source", required=True)
    p_cur.add_argument("--event", required=True)
    p_cur.add_argument("--if-version", required=True)
    p_cur.add_argument("--title", default="")
    p_cur.add_argument("--tier", type=int, default=4)
    p_cur.add_argument("--type", dest="unit_type", default="rules")
    p_cur.add_argument("--area", default="general")
    p_cur.add_argument("--read-when", default="")
    p_cur.add_argument("--session", default="default")

    p_del = sub.add_parser("delete-fact", help="Exceptional approval-gated deletion of a specific fact revision.")
    add_common(p_del)
    p_del.add_argument("--unit", required=True)
    p_del.add_argument("--fact-id", required=True)
    p_del.add_argument("--revision", type=int, required=True)
    p_del.add_argument("--scope", required=True, choices=("active-store", "git-history", "external-copies"))
    p_del.add_argument("--approval", required=True)
    p_del.add_argument("--if-version", required=True)

    p_orient = sub.add_parser("orient", help="Session-start orientation summary.")
    add_common(p_orient)
    p_orient.add_argument("--session", default="default")

    p_inject = sub.add_parser("inject", help="Bounded per-message snippet injection with deadline.")
    add_common(p_inject)
    p_inject.add_argument("message")
    p_inject.add_argument("--max-chars", type=int, default=DEFAULT_INJECT_MAX_CHARS)
    p_inject.add_argument("--deadline-ms", type=int, default=DEFAULT_INJECT_DEADLINE_MS)
    p_inject.add_argument("--limit", type=int, default=3)

    p_gate = sub.add_parser("gate", help="Query-first gate check with non-blocking fallback.")
    add_common(p_gate)
    p_gate.add_argument("--session", default="default")
    p_gate.add_argument("--action", default="read")
    p_gate.add_argument("--target", default="")

    p_end = sub.add_parser("session-end", help="End-of-session curation check.")
    add_common(p_end)
    p_end.add_argument("--session", default="default")

    p_obs = sub.add_parser("observe-change", help="Observe default-branch changed paths and queue bounded refresh handoff.")
    add_common(p_obs)
    p_obs.add_argument("--handoff", default=None)
    p_obs.add_argument("--event-id", required=True)
    p_obs.add_argument("--revision", required=True)
    p_obs.add_argument("--changed", default="", help="Comma-separated list of changed paths.")
    p_obs.add_argument("--order", type=int, default=0)
    p_obs.add_argument("--catch-up", action="store_true")

    p_rstat = sub.add_parser("refresh-status", help="Inspect observed/pending/completed refresh handoff state.")
    p_rstat.add_argument("--project", default=".")
    p_rstat.add_argument("--handoff", default=None)

    p_rcomp = sub.add_parser("complete-refresh", help="Mark a pending refresh event completed.")
    p_rcomp.add_argument("--project", default=".")
    p_rcomp.add_argument("--handoff", default=None)
    p_rcomp.add_argument("--event-id", required=True)
    p_rcomp.add_argument("--revision", required=True)
    p_rcomp.add_argument("--order", type=int, default=0)

    p_mref = sub.add_parser("manual-refresh", help="Run non-Git source-fingerprint refresh check.")
    add_common(p_mref)
    p_mref.add_argument("--snapshot", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 12):
        return _emit(Err("python_version", f"Python 3.12+ is required, found {sys.version.split()[0]}."))

    args = build_parser().parse_args(argv)
    project = Path(args.project).resolve()

    match args.command:
        case "check-locator":
            res = inspect_locators(project)
            if isinstance(res, Err):
                return _emit(res)
            st = res.value
            return _emit(Ok({
                "knowledgeRoot": st.active_rel,
                "store": str(st.active_path) if st.active_path else None,
                "locator_source": st.locator_source,
                "legacy_candidates": list(st.legacy_candidates),
                "language": st.language,
                "tracked": st.tracked,
            }))
        case "setup":
            return _emit(setup_store(project, rel_root=args.root, language=args.language, local_only=args.local_only))
        case "migrate":
            return _emit(migrate_store(project, legacy_rel=args.legacy_rel, target_rel=args.root, language=args.language, local_only=args.local_only))
        case "refresh-status":
            handoff = Path(args.handoff).resolve() if args.handoff else default_handoff_path(project)
            return _emit(refresh_status(handoff))
        case "complete-refresh":
            handoff = Path(args.handoff).resolve() if args.handoff else default_handoff_path(project)
            return _emit(complete_refresh(handoff, event_id=args.event_id, revision=args.revision, order=args.order))
        case "gate":
            resolved = _resolve_store(project, args.root)
            store_root = resolved.value if isinstance(resolved, Ok) else None
            return _emit(cmd_gate(project, store_root, session_id=args.session, action=args.action, target=args.target))
        case "session-end":
            resolved = _resolve_store(project, args.root)
            store_root = resolved.value if isinstance(resolved, Ok) else None
            return _emit(cmd_session_end(project, store_root, session_id=args.session))

    resolved = _resolve_store(project, args.root)
    if isinstance(resolved, Err):
        return _emit(resolved)
    store_root = resolved.value

    match args.command:
        case "catalog":
            return _emit(cmd_catalog(store_root, path_prefix=args.path_prefix, unit_type=args.unit_type, updated_after=args.updated_after))
        case "find":
            res = cmd_find(store_root, args.terms, path_prefix=args.path_prefix, unit_type=args.unit_type, area=args.area, limit=args.limit, include_history=args.history)
            if isinstance(res, Ok):
                record_observed_query(project, args.session, command="find", terms=args.terms, hit_count=len(res.value["hits"]))
            return _emit(res)
        case "fetch":
            res = cmd_fetch(store_root, args.unit_id, anchor=args.anchor, start_line=args.start_line, end_line=args.end_line, max_tokens=args.max_tokens, include_history=args.history)
            if isinstance(res, Ok):
                record_observed_query(project, args.session, command="fetch", unit_id=args.unit_id, hit_count=1)
            return _emit(res)
        case "glossary":
            return _emit(cmd_glossary(store_root, term=args.term))
        case "links":
            return _emit(cmd_links(store_root, args.unit_id, direction=args.direction))
        case "rebuild-catalog":
            return _emit(cmd_rebuild_catalog(store_root))
        case "validate-lineage":
            return _emit(cmd_validate_lineage(store_root))
        case "curate":
            res = curate_fact(
                open_store(store_root),
                unit_id=args.unit,
                fact_id=args.fact_id,
                text=args.text,
                owner=args.owner,
                direction=args.direction,
                origin=args.origin,
                source=args.source,
                event=args.event,
                if_version=args.if_version,
                title=args.title,
                tier=args.tier,
                unit_type=args.unit_type,
                area=args.area,
                read_when=args.read_when,
            )
            if isinstance(res, Ok):
                record_curated_write(project, args.session)
            return _emit(res)
        case "delete-fact":
            return _emit(delete_fact_revision(
                open_store(store_root),
                unit_id=args.unit,
                fact_id=args.fact_id,
                revision=args.revision,
                scope=args.scope,
                approval=args.approval,
                if_version=args.if_version,
            ))
        case "orient":
            return _emit(cmd_orient(project, store_root, session_id=args.session))
        case "inject":
            return _emit(cmd_inject(project, store_root, args.message, max_chars=args.max_chars, deadline_ms=args.deadline_ms, limit=args.limit))
        case "observe-change":
            handoff = Path(args.handoff).resolve() if args.handoff else default_handoff_path(project)
            paths = [p.strip() for p in args.changed.split(",") if p.strip()]
            return _emit(observe_change(store_root, handoff, event_id=args.event_id, revision=args.revision, changed_paths=paths, order=args.order, catch_up=args.catch_up))
        case "manual-refresh":
            snap = Path(args.snapshot).resolve() if args.snapshot else None
            return _emit(manual_refresh(project, store_root, snapshot_path=snap))
        case _:
            return _emit(Err("unknown_command", f"Unknown command: {args.command}"))


if __name__ == "__main__":
    raise SystemExit(main())
