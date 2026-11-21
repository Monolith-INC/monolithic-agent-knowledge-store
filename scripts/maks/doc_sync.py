"""Bidirectional documentation sync (`ingest-docs`, `publish-docs`, `apply-doc-patch`).

Pure stdlib Python 3.12+. Region markers map explicit document spans to stable
`unit_id:fact_id` references without granting new write permissions. All tracked
flow-log records are sanitized to exclude private text, local paths, and raw
diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import Err, Ok, Result
from .curation import parse_fact_revisions
from .paths import validate_visible_store_path
from .retrieval import open_store

FLOW_LOG_NAME = "flow-log.jsonl"

_OPEN_TAG_RE = re.compile(
    r'^<!--\s*maks:region\s+id="(?P<id>[A-Za-z0-9._-]+)"\s+facts="(?P<facts>[^"]+)"(?:\s+hash="(?P<hash>[a-f0-9]{64})")?\s*-->$'
)
_CLOSE_TAG_RE = re.compile(r"^<!--\s*/maks:region\s*-->$")
_ANY_MARKER_RE = re.compile(r"^<!--\s*/?maks:region\b")

_PRIVATE_PATTERNS = (
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"(?:/Users/|/home/|C:\\\\Users\\\\)[^\s\"']+"),
    re.compile(r"(?i)traceback \(most recent call last\)"),
)


@dataclass(frozen=True)
class RegionSpan:
    region_id: str
    fact_refs: tuple[str, ...]
    recorded_hash: str
    start_line: int  # 0-based index of opening tag
    end_line: int  # 0-based index of closing tag
    body: str


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _mapping_digest(regions: tuple[RegionSpan, ...]) -> str:
    canonical = [{"id": r.region_id, "facts": list(r.fact_refs)} for r in regions]
    return _sha256_text(json.dumps(canonical, sort_keys=True, separators=(",", ":")))


def _sanitize_summary(text: str) -> str:
    cleaned = text
    for pat in _PRIVATE_PATTERNS:
        cleaned = pat.sub("[REDACTED]", cleaned)
    return cleaned[:200]


def _validate_doc_path(project: Path, doc_rel: str) -> Result[Path]:
    res = validate_visible_store_path(project, doc_rel)
    if isinstance(res, Err):
        return res
    _, abs_path = res.value
    return Ok(abs_path)


def _read_flow_log(store_root: Path) -> list[dict]:
    log_path = store_root / FLOW_LOG_NAME
    if not log_path.exists():
        return []
    entries: list[dict] = []
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _append_flow_event(
    store_root: Path,
    *,
    flow_id: str,
    direction: str,
    phase: str,
    doc_rel: str,
    status: str,
    mapping_digest: str = "",
    destination_version: str = "",
    after_version: str = "",
    note: str = "",
) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "flow_id": flow_id,
        "direction": direction,
        "phase": phase,
        "doc": Path(doc_rel).as_posix(),
        "status": status,
        "mapping_digest": mapping_digest,
        "destination_version": destination_version,
        "after_version": after_version,
        "note": _sanitize_summary(note),
    }
    log_path = store_root / FLOW_LOG_NAME
    with log_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _parse_regions(text: str) -> Result[tuple[RegionSpan, ...]]:
    lines = text.replace("\r\n", "\n").split("\n")
    regions: list[RegionSpan] = []
    seen_ids: set[str] = set()
    active_open: tuple[str, tuple[str, ...], str, int] | None = None

    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not _ANY_MARKER_RE.match(stripped):
            continue
        m_open = _OPEN_TAG_RE.match(stripped)
        m_close = _CLOSE_TAG_RE.match(stripped)
        if m_open:
            if active_open is not None:
                return Err("ambiguous_region_markers", f"Nested maks:region marker at line {idx + 1}.")
            rid = m_open.group("id")
            if rid in seen_ids:
                return Err("ambiguous_region_markers", f"Duplicate maks:region id {rid!r} at line {idx + 1}.")
            facts = tuple(f.strip() for f in m_open.group("facts").split(",") if f.strip())
            if not facts or any(":" not in f for f in facts):
                return Err("ambiguous_region_markers", f"Region {rid!r} must reference unit_id:fact_id pairs.")
            seen_ids.add(rid)
            active_open = (rid, facts, m_open.group("hash") or "", idx)
        elif m_close:
            if active_open is None:
                return Err("ambiguous_region_markers", f"Unexpected closing maks:region marker at line {idx + 1}.")
            rid, facts, rec_hash, start_idx = active_open
            body = "\n".join(lines[start_idx + 1 : idx])
            regions.append(RegionSpan(rid, facts, rec_hash, start_idx, idx, body))
            active_open = None
        else:
            return Err("ambiguous_region_markers", f"Malformed maks:region marker at line {idx + 1}.")

    if active_open is not None:
        return Err("ambiguous_region_markers", f"Unclosed maks:region {active_open[0]!r} starting at line {active_open[3] + 1}.")
    return Ok(tuple(regions))


def _resolve_active_facts(store_root: Path, fact_refs: tuple[str, ...]) -> Result[tuple[dict[str, int], dict[str, str]]]:
    store = open_store(store_root)
    revisions: dict[str, int] = {}
    texts: dict[str, str] = {}
    for ref in fact_refs:
        unit_id, fact_id = ref.split(":", 1)
        try:
            fetched = store.fetch(unit_id)
        except Exception:
            return Err("missing_fact", f"Referenced unit {unit_id!r} was not found in the active store.")
        blocks = parse_fact_revisions(fetched["content"])
        active = [b for b in blocks if b.fact_id == fact_id and b.status == "current"]
        if len(active) != 1:
            return Err("ambiguous_fact_routing", f"Expected exactly 1 current revision for {ref!r}, found {len(active)}.")
        revisions[ref] = active[0].rev
        texts[ref] = active[0].text
    return Ok((revisions, texts))


def _render_region_body(fact_refs: tuple[str, ...], texts: dict[str, str]) -> str:
    return "\n".join(f"- [{ref}] {texts[ref]}" for ref in fact_refs)


def ingest_docs(project: Path, store_root: Path, doc_rel: str, *, flow_id: str | None = None) -> Result[dict]:
    """Quote people-owned passages, skip generated spans, and flag external edits."""
    path_res = _validate_doc_path(project, doc_rel)
    if isinstance(path_res, Err):
        return path_res
    doc_path = path_res.value
    if not doc_path.is_file():
        return Err("doc_not_found", f"Document {doc_rel!r} does not exist.")

    fid = flow_id or f"ingest-{uuid.uuid4().hex[:12]}"
    text = doc_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    doc_version = _sha256_text(text)

    existing = _read_flow_log(store_root)
    completed = [e for e in existing if e.get("flow_id") == fid and e.get("phase") == "completion"]
    if completed:
        return Ok({
            "flow_id": fid,
            "status": "already_completed",
            "doc": Path(doc_rel).as_posix(),
            "destination_version": doc_version,
        })

    has_intent = any(e.get("flow_id") == fid and e.get("phase") == "intent" for e in existing)
    if not has_intent:
        _append_flow_event(
            store_root,
            flow_id=fid,
            direction="ingest-docs",
            phase="intent",
            doc_rel=doc_rel,
            status="started",
            destination_version=doc_version,
        )

    parsed = _parse_regions(text)
    if isinstance(parsed, Err):
        _append_flow_event(
            store_root,
            flow_id=fid,
            direction="ingest-docs",
            phase="completion",
            doc_rel=doc_rel,
            status="frozen",
            destination_version=doc_version,
            note=parsed.code,
        )
        return Ok({
            "flow_id": fid,
            "status": "frozen",
            "reason": parsed.code,
            "doc": Path(doc_rel).as_posix(),
            "quoted_passages": [],
            "skipped_regions": [],
            "external_edits": [],
        })

    regions = parsed.value
    lines = text.split("\n")
    covered: set[int] = set()
    skipped_regions: list[str] = []
    external_edits: list[dict] = []

    for region in regions:
        for ln in range(region.start_line, region.end_line + 1):
            covered.add(ln)
        actual_hash = _sha256_text(region.body)
        if region.recorded_hash and actual_hash == region.recorded_hash:
            skipped_regions.append(region.region_id)
        else:
            external_edits.append({
                "region_id": region.region_id,
                "facts": list(region.fact_refs),
                "authorship": "unknown",
                "recorded_hash": region.recorded_hash,
                "actual_hash": actual_hash,
                "preserved_text": region.body,
            })

    quoted_passages: list[dict] = []
    buf: list[str] = []
    start_ln: int | None = None
    for idx, line in enumerate(lines):
        if idx in covered or not line.strip():
            if buf and start_ln is not None:
                quoted_passages.append({
                    "start_line": start_ln + 1,
                    "end_line": idx,
                    "quote": "\n".join(buf),
                })
                buf = []
                start_ln = None
            continue
        if start_ln is None:
            start_ln = idx
        buf.append(line)
    if buf and start_ln is not None:
        quoted_passages.append({
            "start_line": start_ln + 1,
            "end_line": len(lines),
            "quote": "\n".join(buf),
        })

    status = "frozen_external_edit" if external_edits else "completed"
    _append_flow_event(
        store_root,
        flow_id=fid,
        direction="ingest-docs",
        phase="completion",
        doc_rel=doc_rel,
        status=status,
        mapping_digest=_mapping_digest(regions),
        destination_version=doc_version,
        note=f"quoted={len(quoted_passages)} skipped={len(skipped_regions)} external_edits={len(external_edits)}",
    )
    return Ok({
        "flow_id": fid,
        "status": status,
        "doc": Path(doc_rel).as_posix(),
        "destination_version": doc_version,
        "quoted_passages": quoted_passages,
        "skipped_regions": skipped_regions,
        "external_edits": external_edits,
    })


def publish_docs(project: Path, store_root: Path, doc_rel: str, *, flow_id: str | None = None) -> Result[dict]:
    """Produce a checked patch bound to active fact revisions, mapping digest, and doc version."""
    path_res = _validate_doc_path(project, doc_rel)
    if isinstance(path_res, Err):
        return path_res
    doc_path = path_res.value
    if not doc_path.is_file():
        return Err("doc_not_found", f"Document {doc_rel!r} does not exist.")

    fid = flow_id or f"publish-{uuid.uuid4().hex[:12]}"
    text = doc_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    doc_version = _sha256_text(text)

    parsed = _parse_regions(text)
    if isinstance(parsed, Err):
        return Ok({
            "flow_id": fid,
            "status": "frozen",
            "reason": parsed.code,
            "doc": Path(doc_rel).as_posix(),
            "patch": None,
        })

    regions = parsed.value
    if not regions:
        return Err("no_regions", f"Document {doc_rel!r} has no explicit maks:region markers.")

    external_edits: list[dict] = []
    for region in regions:
        if region.recorded_hash and _sha256_text(region.body) != region.recorded_hash:
            external_edits.append({
                "region_id": region.region_id,
                "authorship": "unknown",
                "preserved_text": region.body,
            })
    if external_edits:
        _append_flow_event(
            store_root,
            flow_id=fid,
            direction="publish-docs",
            phase="completion",
            doc_rel=doc_rel,
            status="frozen_external_edit",
            mapping_digest=_mapping_digest(regions),
            destination_version=doc_version,
            note="External edit detected; automatic overwrite frozen.",
        )
        return Ok({
            "flow_id": fid,
            "status": "frozen_external_edit",
            "doc": Path(doc_rel).as_posix(),
            "external_edits": external_edits,
            "patch": None,
        })

    all_refs = tuple(dict.fromkeys(ref for r in regions for ref in r.fact_refs))
    resolved = _resolve_active_facts(store_root, all_refs)
    if isinstance(resolved, Err):
        return Ok({
            "flow_id": fid,
            "status": "frozen",
            "reason": resolved.code,
            "doc": Path(doc_rel).as_posix(),
            "patch": None,
        })
    fact_revisions, fact_texts = resolved.value

    lines = text.split("\n")
    out_lines: list[str] = []
    cursor = 0
    for region in regions:
        out_lines.extend(lines[cursor : region.start_line])
        new_body = _render_region_body(region.fact_refs, fact_texts)
        new_hash = _sha256_text(new_body)
        facts_attr = ",".join(region.fact_refs)
        out_lines.append(f'<!-- maks:region id="{region.region_id}" facts="{facts_attr}" hash="{new_hash}" -->')
        out_lines.append(new_body)
        out_lines.append("<!-- /maks:region -->")
        cursor = region.end_line + 1
    out_lines.extend(lines[cursor:])
    proposed_content = "\n".join(out_lines)
    after_version = _sha256_text(proposed_content)
    m_digest = _mapping_digest(regions)

    existing = _read_flow_log(store_root)
    if not any(e.get("flow_id") == fid and e.get("phase") == "intent" for e in existing):
        _append_flow_event(
            store_root,
            flow_id=fid,
            direction="publish-docs",
            phase="intent",
            doc_rel=doc_rel,
            status="patch_prepared",
            mapping_digest=m_digest,
            destination_version=doc_version,
            after_version=after_version,
        )

    patch = {
        "flow_id": fid,
        "doc": Path(doc_rel).as_posix(),
        "destination_version": doc_version,
        "after_version": after_version,
        "mapping_digest": m_digest,
        "fact_revisions": fact_revisions,
        "proposed_content": proposed_content,
    }
    return Ok({
        "flow_id": fid,
        "status": "patch_ready",
        "doc": Path(doc_rel).as_posix(),
        "patch": patch,
    })


def apply_doc_patch(
    project: Path,
    store_root: Path,
    patch: dict,
    *,
    qualified_destination: bool = False,
) -> Result[dict]:
    """Revalidate fact revisions, mapping digest, and destination version before writing."""
    if not qualified_destination:
        return Err(
            "unqualified_destination",
            "Automatic document writes require a qualified destination (--qualified-destination).",
        )

    doc_rel = str(patch.get("doc", ""))
    fid = str(patch.get("flow_id", ""))
    if not doc_rel or not fid:
        return Err("invalid_patch", "Patch must include 'doc' and 'flow_id'.")

    path_res = _validate_doc_path(project, doc_rel)
    if isinstance(path_res, Err):
        return path_res
    doc_path = path_res.value
    if not doc_path.is_file():
        return Err("doc_not_found", f"Document {doc_rel!r} does not exist.")

    current_text = doc_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    current_version = _sha256_text(current_text)

    existing = _read_flow_log(store_root)
    completed = [e for e in existing if e.get("flow_id") == fid and e.get("phase") == "completion" and e.get("status") == "applied"]
    if completed and current_version == patch.get("after_version"):
        return Ok({
            "flow_id": fid,
            "status": "already_completed",
            "doc": doc_rel,
            "after_version": current_version,
        })

    # If the target write already succeeded before a crash (prior to completion log), reconcile without rewriting.
    if current_version == patch.get("after_version"):
        _append_flow_event(
            store_root,
            flow_id=fid,
            direction="publish-docs",
            phase="completion",
            doc_rel=doc_rel,
            status="applied",
            mapping_digest=str(patch.get("mapping_digest", "")),
            destination_version=str(patch.get("destination_version", "")),
            after_version=current_version,
            note="Recovered completion after target write.",
        )
        return Ok({
            "flow_id": fid,
            "status": "recovered_after_write",
            "doc": doc_rel,
            "after_version": current_version,
        })

    if current_version != patch.get("destination_version"):
        return Err(
            "destination_version_mismatch",
            "Destination document changed since the patch was prepared; external edit preserved.",
        )

    parsed = _parse_regions(current_text)
    if isinstance(parsed, Err):
        return parsed
    if _mapping_digest(parsed.value) != patch.get("mapping_digest"):
        return Err("mapping_digest_mismatch", "Document region mapping changed since the patch was prepared.")

    expected_revs = patch.get("fact_revisions", {})
    resolved = _resolve_active_facts(store_root, tuple(expected_revs.keys()))
    if isinstance(resolved, Err):
        return resolved
    live_revs, _ = resolved.value
    if live_revs != expected_revs:
        return Err("fact_revision_mismatch", "One or more referenced facts changed revision since the patch was prepared.")

    proposed = str(patch.get("proposed_content", ""))
    if _sha256_text(proposed) != patch.get("after_version"):
        return Err("patch_integrity_error", "Patch content does not match its declared after_version.")

    tmp_path = doc_path.with_name(f".{doc_path.name}.maks-tmp")
    tmp_path.write_text(proposed, encoding="utf-8", newline="\n")
    os.replace(tmp_path, doc_path)

    _append_flow_event(
        store_root,
        flow_id=fid,
        direction="publish-docs",
        phase="completion",
        doc_rel=doc_rel,
        status="applied",
        mapping_digest=str(patch["mapping_digest"]),
        destination_version=str(patch["destination_version"]),
        after_version=str(patch["after_version"]),
    )
    return Ok({
        "flow_id": fid,
        "status": "applied",
        "doc": doc_rel,
        "after_version": str(patch["after_version"]),
    })
