"""Pure path containment, visible-ancestor checks, and single-locator resolution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import Err, Ok, Result

DEFAULT_STORE_DIR = "Project_Knowledge"
LOCATOR_FILE = "project-knowledge.json"
LEGACY_LOCATOR_FILE = ".project-knowledge.json"
REVIEW_SOURCES_FILE = ".monolithic-code-review/sources.json"

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:")


@dataclass(frozen=True)
class LocatorState:
    project_root: Path
    active_rel: str | None
    active_path: Path | None
    locator_source: str | None
    legacy_candidates: tuple[str, ...]
    language: str
    tracked: bool


def _normalize_rel(raw: str) -> str:
    return raw.strip().replace("\\", "/").strip("/")


def validate_visible_store_path(project_root: Path, raw_rel: str) -> Result[tuple[str, Path]]:
    """Validate an in-project visible relative path; reject escapes, symlinks out, and hidden segments."""
    cleaned = _normalize_rel(raw_rel)
    if not cleaned:
        return Err("invalid_path", "Store path must be a non-empty relative path inside the project.")
    if raw_rel.strip().startswith(("/", "\\")) or _WIN_DRIVE_RE.match(raw_rel.strip()):
        return Err("invalid_path", f"Store path {raw_rel!r} must be project-relative, not absolute.")

    parts = tuple(p for p in PurePosixPath(cleaned).parts if p not in ("", "."))
    if not parts:
        return Err("invalid_path", "Store path must name a folder inside the project root.")
    if any(part == ".." for part in parts):
        return Err("path_escape", f"Store path {raw_rel!r} must not traverse above the project root.")
    if any(part.startswith(".") for part in parts):
        return Err("hidden_ancestor", f"Store path {raw_rel!r} contains a hidden folder segment; use visible folders only.")
    if PureWindowsPath(raw_rel).is_absolute():
        return Err("invalid_path", f"Store path {raw_rel!r} must be project-relative.")

    root_resolved = project_root.resolve()
    candidate = root_resolved.joinpath(*parts)

    # Check every existing ancestor and the target for symlinks resolving outside project_root.
    current = root_resolved
    for part in parts:
        current = current / part
        if current.is_symlink():
            resolved_step = current.resolve()
            if not resolved_step.is_relative_to(root_resolved):
                return Err("symlink_escape", f"Store path {raw_rel!r} traverses a symlink escaping the project root.")
            rel_step = resolved_step.relative_to(root_resolved)
            if any(seg.startswith(".") for seg in rel_step.parts):
                return Err("hidden_ancestor", f"Store path {raw_rel!r} resolves through a symlink into a hidden folder.")

    resolved = candidate.resolve()
    if not resolved.is_relative_to(root_resolved) or resolved == root_resolved:
        return Err("path_escape", f"Store path {raw_rel!r} must resolve to a subdirectory inside the project root.")
    return Ok(("/".join(parts), resolved))


def _read_json_file(path: Path) -> Result[dict | None]:
    if not path.exists():
        return Ok(None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Err("invalid_json", f"Could not parse {path.name}: {exc}")
    if not isinstance(data, dict):
        return Err("invalid_json", f"{path.name} must contain a JSON object.")
    return Ok(data)


def inspect_locators(project_root: Path) -> Result[LocatorState]:
    """Read the visible locator and refuse conflicting store paths across consumers."""
    root = project_root.resolve()
    primary_res = _read_json_file(root / LOCATOR_FILE)
    if isinstance(primary_res, Err):
        return primary_res
    legacy_res = _read_json_file(root / LEGACY_LOCATOR_FILE)
    if isinstance(legacy_res, Err):
        return legacy_res
    review_res = _read_json_file(root / REVIEW_SOURCES_FILE)
    if isinstance(review_res, Err):
        return review_res

    primary_data = primary_res.value
    legacy_data = legacy_res.value
    review_data = review_res.value

    configured: list[tuple[str, str]] = []
    if primary_data and isinstance(primary_data.get("knowledgeRoot"), str):
        configured.append((LOCATOR_FILE, _normalize_rel(primary_data["knowledgeRoot"])))
    if legacy_data and isinstance(legacy_data.get("knowledgeRoot"), str):
        configured.append((LEGACY_LOCATOR_FILE, _normalize_rel(legacy_data["knowledgeRoot"])))
    if review_data and isinstance(review_data.get("knowledge"), dict):
        rev_root = review_data["knowledge"].get("root")
        if isinstance(rev_root, str) and rev_root.strip():
            configured.append((REVIEW_SOURCES_FILE, _normalize_rel(rev_root)))

    # If visible primary locator is present, compare against review consumer to prevent split stores.
    # Legacy .project-knowledge.json is treated as a migration candidate when primary is absent,
    # or a conflict if both point to different active paths without a migration marker.
    migrated_from = primary_data.get("migratedFrom") if primary_data else None
    effective = [
        (src, path)
        for src, path in configured
        if not (src == LEGACY_LOCATOR_FILE and migrated_from == path)
    ]
    distinct_paths = sorted({path for _, path in effective if path})
    if len(distinct_paths) > 1:
        detail = {src: path for src, path in effective}
        return Err(
            "locator_conflict",
            f"Conflicting project knowledge store locations configured: {detail}. "
            "Choose one store and reconcile before continuing; no second store will be created.",
            detail=detail,
        )

    legacy_candidates = tuple(
        sorted({path for src, path in configured if src == LEGACY_LOCATOR_FILE and path})
    )

    if primary_data and isinstance(primary_data.get("knowledgeRoot"), str):
        checked = validate_visible_store_path(root, primary_data["knowledgeRoot"])
        if isinstance(checked, Err):
            return checked
        rel, resolved = checked.value
        return Ok(
            LocatorState(
                project_root=root,
                active_rel=rel,
                active_path=resolved,
                locator_source=LOCATOR_FILE,
                legacy_candidates=legacy_candidates,
                language=str(primary_data.get("language") or "en"),
                tracked=bool(primary_data.get("tracked", True)),
            )
        )

    if distinct_paths:
        rel = distinct_paths[0]
        resolved = (root / rel).resolve()
        if not resolved.is_relative_to(root):
            return Err("path_escape", f"Configured store path {rel!r} escapes the project root.")
        return Ok(
            LocatorState(
                project_root=root,
                active_rel=rel,
                active_path=resolved,
                locator_source=effective[0][0],
                legacy_candidates=legacy_candidates,
                language="en",
                tracked=False,
            )
        )

    return Ok(
        LocatorState(
            project_root=root,
            active_rel=None,
            active_path=None,
            locator_source=None,
            legacy_candidates=(),
            language="en",
            tracked=True,
        )
    )
