"""Retrieval commands over the vendored KnowledgeStore with current-only default projection."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import Err, Ok, Result, load_engine
from .curation import current_facts_view, validate_unit_lineage

GLOSSARY_NAME = "glossary.md"
SUPPORT_UNIT_IDS = frozenset({"QUERY_GUIDE", "glossary"})
_GLOSSARY_ROW_RE = re.compile(r"^\|\s*(?P<term>[^|]+?)\s*\|\s*(?P<aliases>[^|]*?)\s*\|\s*(?P<definition>[^|]+?)\s*\|\s*(?P<source>[^|]+?)\s*\|$")


def open_store(store_root: Path) -> Any:
    engine = load_engine()
    return engine.KnowledgeStore(store_root)


def cmd_catalog(
    store_root: Path,
    *,
    path_prefix: str | None = None,
    unit_type: str | None = None,
    updated_after: str | None = None,
) -> Result[dict[str, Any]]:
    store = open_store(store_root)
    rows = [
        row for row in store.catalog(path_prefix=path_prefix, type=unit_type, updated_after=updated_after)
        if row["id"] not in SUPPORT_UNIT_IDS
    ]
    return Ok({"store": str(store_root), "count": len(rows), "units": rows})


def cmd_find(
    store_root: Path,
    terms: str,
    *,
    path_prefix: str | None = None,
    unit_type: str | None = None,
    area: str | None = None,
    limit: int = 8,
    include_history: bool = False,
) -> Result[dict[str, Any]]:
    store = open_store(store_root)
    view = None if include_history else current_facts_view
    status = None if include_history else "current"
    hits, guidance = store.find(
        terms,
        path_prefix=path_prefix,
        type=unit_type,
        area=area,
        status=status,
        limit=limit,
        view=view,
    )
    return Ok({
        "query": terms,
        "history": include_history,
        "hits": [asdict(hit) for hit in hits],
        **({"guidance": guidance} if guidance else {}),
    })


def cmd_fetch(
    store_root: Path,
    unit_id: str,
    *,
    anchor: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    max_tokens: int | None = None,
    include_history: bool = False,
) -> Result[dict[str, Any]]:
    engine = load_engine()
    store = open_store(store_root)
    view = None if include_history else current_facts_view
    try:
        fetched = store.fetch(
            unit_id,
            anchor=anchor,
            start_line=start_line,
            end_line=end_line,
            max_tokens=max_tokens,
            view=view,
        )
    except engine.StoreError as exc:
        return Err(getattr(exc, "kind", "store_error"), str(exc))
    return Ok({**fetched, "history": include_history})


def cmd_glossary(store_root: Path, *, term: str | None = None) -> Result[dict[str, Any]]:
    path = store_root / GLOSSARY_NAME
    if not path.is_file():
        return Err("missing_glossary", f"Glossary file {path} does not exist. Run setup to generate it.")
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _GLOSSARY_ROW_RE.match(line.strip())
        if not m:
            continue
        t = m.group("term").strip()
        if t.lower() in {"term", "termo", "término"} or set(t) <= {"-", ":"}:
            continue
        aliases = [a.strip() for a in m.group("aliases").split(",") if a.strip() and a.strip() != "-"]
        entries.append({
            "term": t,
            "aliases": aliases,
            "definition": m.group("definition").strip(),
            "source": m.group("source").strip(),
        })

    if term:
        needle = term.strip().lower()
        entries = [
            e for e in entries
            if needle in e["term"].lower() or any(needle in a.lower() for a in e["aliases"])
        ]
    return Ok({"path": str(path), "count": len(entries), "entries": entries})


def cmd_links(store_root: Path, unit_id: str, *, direction: str = "both") -> Result[dict[str, Any]]:
    engine = load_engine()
    store = open_store(store_root)
    try:
        return Ok(store.links(unit_id, direction=direction))
    except engine.StoreError as exc:
        return Err(getattr(exc, "kind", "store_error"), str(exc))


def cmd_rebuild_catalog(store_root: Path) -> Result[dict[str, Any]]:
    store = open_store(store_root)
    catalog_path = store.write_catalog()
    rows = [row for row in store.catalog() if row["id"] not in SUPPORT_UNIT_IDS]
    return Ok({"catalog": str(catalog_path), "unit_count": len(rows)})


def cmd_validate_lineage(store_root: Path) -> Result[dict[str, Any]]:
    store = open_store(store_root)
    issues: list[str] = []
    for unit_id, unit in sorted(store.units.items()):
        if unit.fmt == "md":
            issues.extend(validate_unit_lineage(unit_id, unit.body))
    if issues:
        return Err("lineage_invalid", f"Found {len(issues)} lineage issue(s).", detail={"issues": issues})
    return Ok({"store": str(store_root), "units_checked": len(store.units), "issues": []})
