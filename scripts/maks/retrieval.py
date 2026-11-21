"""Retrieval commands over the vendored KnowledgeStore with current-only default projection."""

from __future__ import annotations

import re
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import Err, Ok, Result, load_engine
from .curation import current_facts_view, validate_unit_lineage

GLOSSARY_NAME = "glossary.md"
MANIFEST_NAME = "manifest.md"
SUPPORT_UNIT_IDS = frozenset({"QUERY_GUIDE", "glossary"})
_GLOSSARY_ROW_RE = re.compile(
    r"^\|\s*(?P<term>[^|]+?)\s*\|\s*(?P<aliases>[^|]*?)\s*\|\s*(?P<definition>[^|]+?)\s*\|\s*(?P<source>[^|]+?)\s*\|$"
)


def open_store(store_root: Path) -> Any:
    engine = load_engine()
    return engine.KnowledgeStore(store_root)


def sync_clean_catalog(store_root: Path, store: Any | None = None) -> Path:
    """Rebuild catalog.tsv via upstream engine and strip non-curated support rows (QUERY_GUIDE, glossary)."""
    st = store if store is not None else open_store(store_root)
    catalog_path = Path(st.write_catalog())
    lines = catalog_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return catalog_path
    header = lines[0]
    cleaned = [header] + [
        line for line in lines[1:]
        if line.strip() and line.split("\t", 1)[0] not in SUPPORT_UNIT_IDS
    ]
    catalog_path.write_text("\n".join(cleaned) + "\n", encoding="utf-8", newline="\n")
    return catalog_path


def _git_head_sha(project_root: Path | None) -> str:
    if project_root is None:
        return ""
    git_dir = project_root / ".git"
    if not ((git_dir / "HEAD").is_file() or git_dir.is_file()):
        return ""
    try:
        return subprocess.check_output(
            ["git", "-C", str(project_root), "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def update_manifest_summary(store_root: Path, store: Any | None = None, *, project_root: Path | None = None) -> None:
    """Keep manifest.md metadata synchronized with curated unit counts, tiers, and git HEAD."""
    manifest_path = store_root / MANIFEST_NAME
    if not manifest_path.is_file():
        return
    st = store if store is not None else open_store(store_root)
    curated = [u for uid, u in sorted(st.units.items()) if uid not in SUPPORT_UNIT_IDS]
    tiers = sorted({int(u.fields["tier"]) for u in curated if str(u.fields.get("tier", "")).isdigit()})
    stated = sum(1 for u in curated if str(u.fields.get("provenance", "")).lower() == "stated")
    derived = sum(1 for u in curated if str(u.fields.get("provenance", "")).lower() == "derived")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    sha = _git_head_sha(project_root)

    existing = manifest_path.read_text(encoding="utf-8")
    language = "en"
    rel_root = store_root.name
    for line in existing.splitlines():
        if line.startswith("language:"):
            language = line.split(":", 1)[1].strip() or "en"
        elif line.startswith("store_root:"):
            rel_root = line.split(":", 1)[1].strip() or store_root.name

    fm = [
        "---",
        "schema_version: 1",
        f"store_root: {rel_root}",
        f"language: {language}",
        f"updated: {today}",
        f"unit_count: {len(curated)}",
        f"stated_units: {stated}",
        f"derived_units: {derived}",
        f"tiers_present: [{', '.join(str(t) for t in tiers)}]",
    ]
    if sha:
        fm.append(f"derived_from_commit: {sha}")
    fm.append("---")
    body = (
        "\n# Project Knowledge Store\n\n"
        "Five-tier Markdown knowledge store (`identity`, `structure`, `mechanics`, `rules`, `evolution`).\n"
    )
    manifest_path.write_text("\n".join(fm) + "\n" + body, encoding="utf-8", newline="\n")


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
        limit=limit + len(SUPPORT_UNIT_IDS),
        view=view,
    )
    filtered = [asdict(hit) for hit in hits if hit.unit_id not in SUPPORT_UNIT_IDS][:limit]
    return Ok({
        "query": terms,
        "history": include_history,
        "hits": filtered,
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


def cmd_curate_glossary(
    store_root: Path,
    *,
    term: str,
    definition: str,
    source: str,
    aliases: tuple[str, ...] | list[str] = (),
) -> Result[dict[str, Any]]:
    """Safely add or update a sourced term in glossary.md without raw file edits."""
    path = store_root / GLOSSARY_NAME
    if not path.is_file():
        return Err("missing_glossary", f"Glossary file {path} does not exist. Run setup to generate it.")
    clean_term = term.strip().replace("|", "/")
    clean_def = definition.strip().replace("|", "/")
    clean_src = source.strip().replace("|", "/")
    if not clean_term or not clean_def or not clean_src:
        return Err("missing_metadata", "Glossary entries require non-empty --term, --definition, and --source.")
    clean_aliases = ", ".join(a.strip().replace("|", "/") for a in aliases if a.strip()) or "-"
    new_row = f"| {clean_term} | {clean_aliases} | {clean_def} | {clean_src} |"

    lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    out_lines: list[str] = []
    for line in lines:
        m = _GLOSSARY_ROW_RE.match(line.strip())
        if m and m.group("term").strip().lower() == clean_term.lower():
            out_lines.append(new_row)
            replaced = True
        else:
            out_lines.append(line)
    if not replaced:
        out_lines.append(new_row)
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8", newline="\n")
    return Ok({
        "path": str(path),
        "term": clean_term,
        "updated": replaced,
        "added": not replaced,
    })


def cmd_links(store_root: Path, unit_id: str, *, direction: str = "both") -> Result[dict[str, Any]]:
    engine = load_engine()
    store = open_store(store_root)
    try:
        return Ok(store.links(unit_id, direction=direction))
    except engine.StoreError as exc:
        return Err(getattr(exc, "kind", "store_error"), str(exc))


def cmd_rebuild_catalog(store_root: Path, *, project_root: Path | None = None) -> Result[dict[str, Any]]:
    store = open_store(store_root)
    catalog_path = sync_clean_catalog(store_root, store)
    update_manifest_summary(store_root, store, project_root=project_root)
    rows = [row for row in store.catalog() if row["id"] not in SUPPORT_UNIT_IDS]
    return Ok({"catalog": str(catalog_path), "unit_count": len(rows)})


def cmd_validate_lineage(store_root: Path) -> Result[dict[str, Any]]:
    store = open_store(store_root)
    issues: list[str] = []
    checked = 0
    for unit_id, unit in sorted(store.units.items()):
        if unit_id in SUPPORT_UNIT_IDS:
            continue
        if unit.fmt == "md":
            checked += 1
            issues.extend(validate_unit_lineage(unit_id, unit.body))
    if issues:
        return Err("lineage_invalid", f"Found {len(issues)} lineage issue(s).", detail={"issues": issues})
    return Ok({"store": str(store_root), "units_checked": checked, "issues": []})
