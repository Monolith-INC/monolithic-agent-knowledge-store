"""Version-checked curation, current-fact ReadView projection, and lineage validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import Err, Ok, Result, load_engine

VALID_OWNERS = frozenset({"people", "store"})
VALID_DIRECTIONS = frozenset({"stated", "derived"})
VALID_FACT_STATUSES = frozenset({"current", "obsolete", "deprecated"})
VALID_DELETE_SCOPES = frozenset({"active-store", "git-history", "external-copies"})
REQUIRED_META_KEYS = ("owner", "direction", "origin", "source", "event")

_FACT_HEADER_RE = re.compile(
    r"^###\s+fact:(?P<fact_id>[A-Za-z0-9._/-]+)\s+\[rev:(?P<rev>\d+)\s+status:(?P<status>[a-z]+)\]\s*$"
)
_META_LINE_RE = re.compile(r"^-\s+(?P<key>[a-z_]+):\s*(?P<value>.*)$")
_FACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


@dataclass(frozen=True)
class FactRevision:
    fact_id: str
    rev: int
    status: str
    meta: dict[str, str]
    text: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class _Block:
    kind: str  # "raw" | "fact"
    lines: tuple[str, ...]
    fact: FactRevision | None = None


def _split_blocks(body: str) -> tuple[_Block, ...]:
    """Split a unit body into alternating raw text blocks and structured fact-revision blocks."""
    lines = body.splitlines()
    blocks: list[_Block] = []
    idx = 0
    raw_buf: list[str] = []

    def flush_raw() -> None:
        if raw_buf:
            blocks.append(_Block(kind="raw", lines=tuple(raw_buf)))
            raw_buf.clear()

    while idx < len(lines):
        match = _FACT_HEADER_RE.match(lines[idx])
        if not match:
            raw_buf.append(lines[idx])
            idx += 1
            continue

        flush_raw()
        start = idx
        idx += 1
        meta: dict[str, str] = {}
        while idx < len(lines):
            m = _META_LINE_RE.match(lines[idx])
            if not m:
                break
            meta[m.group("key")] = m.group("value").strip()
            idx += 1

        content_lines: list[str] = []
        while idx < len(lines) and not _FACT_HEADER_RE.match(lines[idx]) and not re.match(r"^##\s+", lines[idx]):
            content_lines.append(lines[idx])
            idx += 1

        block_lines = tuple(lines[start:idx])
        text = "\n".join(content_lines).strip()
        fact = FactRevision(
            fact_id=match.group("fact_id"),
            rev=int(match.group("rev")),
            status=match.group("status"),
            meta=meta,
            text=text,
            start_line=start + 1,
            end_line=idx,
        )
        blocks.append(_Block(kind="fact", lines=block_lines, fact=fact))

    flush_raw()
    return tuple(blocks)


def parse_fact_revisions(body: str) -> tuple[FactRevision, ...]:
    return tuple(block.fact for block in _split_blocks(body) if block.fact is not None)


def current_facts_view(unit: Any) -> str:
    """ReadView that strips obsolete/deprecated fact revisions before BM25 ranking and fetch."""
    kept: list[str] = []
    for block in _split_blocks(unit.body):
        if block.fact is not None and block.fact.status in {"obsolete", "deprecated"}:
            continue
        kept.extend(block.lines)
    return "\n".join(kept).rstrip() + ("\n" if kept else "")


def _render_fact_block(fact_id: str, rev: int, status: str, meta: dict[str, str], text: str) -> tuple[str, ...]:
    header = f"### fact:{fact_id} [rev:{rev} status:{status}]"
    meta_lines = tuple(f"- {key}: {meta[key]}" for key in REQUIRED_META_KEYS if key in meta)
    extra_keys = sorted(set(meta) - set(REQUIRED_META_KEYS))
    extra_lines = tuple(f"- {key}: {meta[key]}" for key in extra_keys)
    return (header, *meta_lines, *extra_lines, "", text.strip(), "")


def validate_unit_lineage(unit_id: str, body: str) -> tuple[str, ...]:
    """Validate single current revision per fact_id, metadata completeness, and predecessor-before-successor order."""
    issues: list[str] = []
    by_fact: dict[str, list[FactRevision]] = {}
    for fact in parse_fact_revisions(body):
        if fact.status not in VALID_FACT_STATUSES:
            issues.append(f"{unit_id}: fact {fact.fact_id} rev:{fact.rev} has invalid status {fact.status!r}.")
        missing_meta = [key for key in REQUIRED_META_KEYS if not fact.meta.get(key)]
        if missing_meta:
            issues.append(f"{unit_id}: fact {fact.fact_id} rev:{fact.rev} missing metadata: {', '.join(missing_meta)}.")
        by_fact.setdefault(fact.fact_id, []).append(fact)

    for fact_id, revisions in sorted(by_fact.items()):
        currents = [r for r in revisions if r.status == "current"]
        if len(currents) > 1:
            revs = ", ".join(f"rev:{r.rev}" for r in currents)
            issues.append(
                f"{unit_id}: competing current revisions for fact {fact_id} ({revs}); "
                "reconcile against sources while retaining both in history."
            )
        rev_nums = [r.rev for r in revisions]
        if len(set(rev_nums)) != len(rev_nums):
            issues.append(f"{unit_id}: duplicate revision numbers for fact {fact_id}: {rev_nums}.")
        if rev_nums != sorted(rev_nums):
            issues.append(f"{unit_id}: revisions for fact {fact_id} are out of order ({rev_nums}); original must precede successor.")
        if currents and revisions[-1].status != "current":
            issues.append(f"{unit_id}: current revision for fact {fact_id} must immediately follow its obsolete predecessor.")
    return tuple(issues)


NON_FILE_SOURCE_PREFIXES = ("interview:", "git:", "url:", "decision:")


def normalize_sources(raw: str | list[str] | tuple[str, ...]) -> list[str]:
    """Expand repeatable or semicolon-delimited source strings into clean unique entries."""
    items = [raw] if isinstance(raw, str) else list(raw)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        for part in str(item).split(";"):
            cleaned = part.strip().replace("\\", "/")
            while cleaned.startswith("./"):
                cleaned = cleaned[2:]
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                out.append(cleaned)
    return out


def _validate_sources_exist(project_root: Path, sources: list[str]) -> list[str]:
    root = project_root.resolve()
    missing: list[str] = []
    for src in sources:
        if src.lower().startswith(NON_FILE_SOURCE_PREFIXES):
            continue
        candidate = (root / src).resolve()
        if not candidate.is_relative_to(root) or not candidate.exists():
            missing.append(src)
    return missing


def _format_new_unit(
    *,
    unit_id: str,
    title: str,
    tier: int,
    unit_type: str,
    area: str,
    read_when: str,
    provenance: str,
    sources: list[str],
    body: str,
    links: list[str] | None = None,
    derived_from_commit: str = "",
    supersedes: str = "",
) -> str:
    engine = load_engine()
    fields: dict[str, Any] = {
        "id": unit_id,
        "tier": tier,
        "type": unit_type,
        "area": area,
        "title": title,
        "read_when": read_when,
        "provenance": provenance,
        "sources": sources,
        "status": "current",
    }
    if links:
        fields["links"] = links
    if derived_from_commit.strip():
        fields["derived_from_commit"] = derived_from_commit.strip()
    if supersedes.strip():
        fields["supersedes"] = supersedes.strip()
    return engine.dump_frontmatter(fields) + "\n" + body.lstrip("\n")


def curate_fact(
    store: Any,
    *,
    unit_id: str,
    fact_id: str,
    text: str,
    owner: str,
    direction: str,
    origin: str,
    source: str | list[str] | tuple[str, ...],
    event: str,
    if_version: str,
    title: str = "",
    tier: int = 4,
    unit_type: str = "rules",
    area: str = "general",
    read_when: str = "",
    links: list[str] | tuple[str, ...] = (),
    derived_from_commit: str = "",
    supersedes: str = "",
    open_questions: str = "",
    project_root: Path | None = None,
) -> Result[dict[str, Any]]:
    """Single version-checked write path; corrections preserve original text immediately before successor."""
    engine = load_engine()
    if not _FACT_ID_RE.match(fact_id):
        return Err("invalid_fact_id", f"Invalid fact_id {fact_id!r}.")
    if owner not in VALID_OWNERS:
        return Err("invalid_owner", f"owner must be one of {sorted(VALID_OWNERS)}, got {owner!r}.")
    if direction not in VALID_DIRECTIONS:
        return Err("invalid_direction", f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {direction!r}.")
    if not text.strip():
        return Err("empty_text", "Fact text must be non-empty.")

    norm_sources = normalize_sources(source)
    if not norm_sources:
        return Err("missing_metadata", "At least one non-empty --source is required.")
    for label, val in (("origin", origin), ("event", event)):
        if not val.strip():
            return Err("missing_metadata", f"{label} must be non-empty.")
    if project_root is not None:
        missing = _validate_sources_exist(project_root, norm_sources)
        if missing:
            return Err(
                "unverified_source",
                f"Source path(s) do not exist in project: {missing}. Pass repeatable --source <path> for existing files or prefix non-file citations with interview:/git:/url:/decision:.",
                detail={"missing_sources": missing},
            )

    norm_links = [lnk.strip() for lnk in links if lnk.strip()]
    meta = {
        "owner": owner,
        "direction": direction,
        "origin": origin.strip(),
        "source": ", ".join(norm_sources),
        "event": event.strip(),
    }

    existing = store.units.get(unit_id)
    if existing is None:
        if if_version != engine.NEW_VERSION:
            return Err("unknown_unit", f"{unit_id} does not exist; pass if_version='new' to create it.")
        block = _render_fact_block(fact_id, 1, "current", meta, text)
        heading = f"# {title or unit_id}\n\n"
        extra_sections: list[str] = []
        if norm_links:
            extra_sections.append("## Related\n\n" + "\n".join(f"- [[{lnk}]]" for lnk in norm_links) + "\n")
        if open_questions.strip():
            extra_sections.append(f"## Open questions\n\n{open_questions.strip()}\n")
        full_text = _format_new_unit(
            unit_id=unit_id,
            title=title or unit_id,
            tier=tier,
            unit_type=unit_type,
            area=area,
            read_when=read_when or f"when working on {area}",
            provenance=direction,
            sources=norm_sources,
            links=norm_links,
            derived_from_commit=derived_from_commit,
            supersedes=supersedes,
            body=heading + "\n".join(block) + ("\n" + "\n".join(extra_sections) if extra_sections else ""),
        )
        new_rev = 1
    else:
        lineage_issues = validate_unit_lineage(unit_id, existing.body)
        if lineage_issues:
            return Err(
                "lineage_conflict",
                "Cannot curate a unit with unresolved lineage conflicts.",
                detail={"issues": list(lineage_issues)},
            )
        blocks = list(_split_blocks(existing.body))
        matching_indices = [i for i, b in enumerate(blocks) if b.fact is not None and b.fact.fact_id == fact_id]
        if matching_indices:
            last_idx = matching_indices[-1]
            last_fact = blocks[last_idx].fact
            assert last_fact is not None
            new_rev = last_fact.rev + 1
            obsolete_lines = _render_fact_block(
                last_fact.fact_id,
                last_fact.rev,
                "obsolete" if last_fact.status == "current" else last_fact.status,
                last_fact.meta,
                last_fact.text,
            )
            successor_lines = _render_fact_block(fact_id, new_rev, "current", meta, text)
            blocks[last_idx] = _Block(kind="raw", lines=obsolete_lines)
            blocks.insert(last_idx + 1, _Block(kind="raw", lines=successor_lines))
        else:
            new_rev = 1
            blocks.append(_Block(kind="raw", lines=_render_fact_block(fact_id, 1, "current", meta, text)))

        new_body = "\n".join(line for b in blocks for line in b.lines).rstrip() + "\n"
        fields = dict(existing.fields)
        sources_list = normalize_sources(list(fields.get("sources") or []))
        for src in norm_sources:
            if src not in sources_list:
                sources_list.append(src)
        fields["sources"] = sources_list
        if norm_links:
            existing_links = [str(x).strip() for x in (fields.get("links") or []) if str(x).strip()]
            for lnk in norm_links:
                if lnk not in existing_links:
                    existing_links.append(lnk)
            fields["links"] = existing_links
        if derived_from_commit.strip():
            fields["derived_from_commit"] = derived_from_commit.strip()
        if supersedes.strip():
            fields["supersedes"] = supersedes.strip()
        full_text = engine.dump_frontmatter(fields) + "\n" + new_body.lstrip("\n")

    try:
        written = store.put(unit_id, full_text, if_version=if_version)
    except engine.VersionConflict as exc:
        return Err("version_conflict", str(exc), detail={"expected": if_version, "current": getattr(exc, "current", "")})
    except engine.StoreError as exc:
        return Err("store_error", str(exc))

    from .retrieval import sync_clean_catalog, update_manifest_summary

    sync_clean_catalog(store.root, store)
    update_manifest_summary(store.root, store, project_root=project_root)
    return Ok({**written, "fact_id": fact_id, "revision": new_rev, "status": "current", "sources": norm_sources})


def delete_fact_revision(
    store: Any,
    *,
    unit_id: str,
    fact_id: str,
    revision: int,
    scope: str,
    approval: str,
    if_version: str,
) -> Result[dict[str, Any]]:
    """Exceptional deletion requiring direct approval for the exact fact, revision, and scope."""
    engine = load_engine()
    if scope not in VALID_DELETE_SCOPES:
        return Err("invalid_scope", f"scope must be one of {sorted(VALID_DELETE_SCOPES)}, got {scope!r}.")
    expected_approval = f"DELETE {unit_id}:{fact_id}:rev{revision}:{scope}"
    if approval != expected_approval:
        return Err(
            "approval_required",
            f"Exceptional deletion requires exact direct approval token: {expected_approval!r}.",
            detail={"required_approval": expected_approval},
        )
    if scope != "active-store":
        return Err(
            "manual_scope",
            f"Scope {scope!r} cannot be mutated automatically by query.py; handle {scope} outside active-store curation.",
        )

    existing = store.units.get(unit_id)
    if existing is None:
        return Err("unknown_unit", f"Unit {unit_id!r} does not exist.")

    blocks = list(_split_blocks(existing.body))
    remaining = [
        b for b in blocks if not (b.fact is not None and b.fact.fact_id == fact_id and b.fact.rev == revision)
    ]
    if len(remaining) == len(blocks):
        return Err("not_found", f"Fact {fact_id} rev:{revision} not found in {unit_id}.")

    new_body = "\n".join(line for b in remaining for line in b.lines).rstrip() + "\n"
    full_text = engine.dump_frontmatter(dict(existing.fields)) + "\n" + new_body.lstrip("\n")
    try:
        written = store.put(unit_id, full_text, if_version=if_version)
    except engine.VersionConflict as exc:
        return Err("version_conflict", str(exc), detail={"expected": if_version, "current": getattr(exc, "current", "")})
    except engine.StoreError as exc:
        return Err("store_error", str(exc))

    from .retrieval import sync_clean_catalog

    sync_clean_catalog(store.root, store)
    return Ok({**written, "deleted": {"unit_id": unit_id, "fact_id": fact_id, "revision": revision, "scope": scope}})
