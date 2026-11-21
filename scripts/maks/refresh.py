"""Default-branch refresh handoff (observed/pending/completed) and non-Git manual fingerprint refresh."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from . import Err, Ok, Result
from .curation import NON_FILE_SOURCE_PREFIXES, normalize_sources
from .retrieval import SUPPORT_UNIT_IDS, open_store


def default_handoff_path(project_root: Path) -> Path:
    key = hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()[:24]
    base = Path(tempfile.gettempdir()) / "maks-refresh"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{key}.json"


def _normalize_path(raw: str) -> str:
    return raw.strip().replace("\\", "/").lstrip("./")


def _read_handoff(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "schemaVersion": 1,
            "completed_revision": None,
            "completed_order": -1,
            "observed_event_ids": [],
            "pending": [],
            "completed": [],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {
            "schemaVersion": 1,
            "completed_revision": None,
            "completed_order": -1,
            "observed_event_ids": [],
            "pending": [],
            "completed": [],
        }


def _write_handoff(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def _match_affected_units(store_root: Path, changed_paths: list[str]) -> tuple[list[str], list[str]]:
    store = open_store(store_root)
    norm_changed = [_normalize_path(p) for p in changed_paths if _normalize_path(p)]
    affected_units: list[str] = []
    matched_sources: set[str] = set()

    for unit_id, unit in sorted(store.units.items()):
        if unit_id in SUPPORT_UNIT_IDS:
            continue
        sources = [
            _normalize_path(s)
            for s in normalize_sources(list(unit.fields.get("sources") or []))
            if not s.lower().startswith(NON_FILE_SOURCE_PREFIXES)
        ]
        hit = False
        for src in sources:
            for ch in norm_changed:
                if ch == src or ch.startswith(f"{src}/") or src.startswith(f"{ch}/"):
                    hit = True
                    matched_sources.add(src)
        if hit:
            affected_units.append(unit_id)
    return affected_units, sorted(matched_sources)


def observe_change(
    store_root: Path,
    handoff_path: Path,
    *,
    event_id: str,
    revision: str,
    changed_paths: list[str],
    order: int = 0,
    catch_up: bool = False,
) -> Result[dict[str, Any]]:
    """Observe a default-branch change; queue bounded pending refresh only for affected unit sources."""
    if not event_id.strip() or not revision.strip():
        return Err("invalid_event", "event_id and revision must be non-empty.")

    state = _read_handoff(handoff_path)
    observed_ids = list(state.get("observed_event_ids") or [])
    if event_id in observed_ids:
        return Ok({
            "status": "duplicate_ignored",
            "event_id": event_id,
            "revision": revision,
            "pending_count": len(state.get("pending") or []),
        })

    completed_order = int(state.get("completed_order", -1))
    if order < completed_order and not catch_up:
        observed_ids.append(event_id)
        state["observed_event_ids"] = observed_ids[-200:]
        _write_handoff(handoff_path, state)
        return Ok({
            "status": "stale_event_ignored",
            "event_id": event_id,
            "revision": revision,
            "completed_revision": state.get("completed_revision"),
            "pending_count": len(state.get("pending") or []),
        })

    affected_units, matched_sources = _match_affected_units(store_root, changed_paths)
    observed_ids.append(event_id)
    state["observed_event_ids"] = observed_ids[-200:]

    if not affected_units:
        if order >= completed_order:
            state["completed_revision"] = revision
            state["completed_order"] = order
        _write_handoff(handoff_path, state)
        return Ok({
            "status": "noop",
            "event_id": event_id,
            "revision": revision,
            "affected_units": [],
            "pending_count": len(state.get("pending") or []),
        })

    pending = list(state.get("pending") or [])
    pending.append({
        "event_id": event_id,
        "revision": revision,
        "order": order,
        "catch_up": catch_up,
        "affected_units": affected_units,
        "affected_sources": matched_sources,
        "observed_at": round(time.time(), 3),
    })
    pending.sort(key=lambda item: (int(item.get("order", 0)), str(item.get("event_id", ""))))
    state["pending"] = pending[-50:]
    _write_handoff(handoff_path, state)
    return Ok({
        "status": "pending",
        "event_id": event_id,
        "revision": revision,
        "affected_units": affected_units,
        "affected_sources": matched_sources,
        "pending_count": len(state["pending"]),
    })


def refresh_status(handoff_path: Path) -> Result[dict[str, Any]]:
    state = _read_handoff(handoff_path)
    return Ok({
        "handoff": str(handoff_path),
        "completed_revision": state.get("completed_revision"),
        "completed_order": state.get("completed_order", -1),
        "observed_count": len(state.get("observed_event_ids") or []),
        "pending": state.get("pending") or [],
        "completed": state.get("completed") or [],
    })


def complete_refresh(handoff_path: Path, *, event_id: str, revision: str, order: int = 0) -> Result[dict[str, Any]]:
    """Mark a pending refresh event completed without moving completed_revision backwards."""
    state = _read_handoff(handoff_path)
    pending = list(state.get("pending") or [])
    remaining = [item for item in pending if item.get("event_id") != event_id]
    if len(remaining) == len(pending):
        return Err("event_not_pending", f"Refresh event {event_id!r} is not in pending state.")

    state["pending"] = remaining
    completed = list(state.get("completed") or [])
    completed.append({"event_id": event_id, "revision": revision, "order": order, "completed_at": round(time.time(), 3)})
    state["completed"] = completed[-100:]

    if order >= int(state.get("completed_order", -1)):
        state["completed_revision"] = revision
        state["completed_order"] = order

    _write_handoff(handoff_path, state)
    return Ok({
        "status": "completed",
        "event_id": event_id,
        "completed_revision": state["completed_revision"],
        "pending_count": len(remaining),
    })


def _fingerprint_source(project_root: Path, rel_source: str) -> str | None:
    target = (project_root / rel_source).resolve()
    if not target.is_relative_to(project_root.resolve()) or not target.exists():
        return None
    if target.is_file():
        return hashlib.sha256(target.read_bytes()).hexdigest()
    if target.is_dir():
        h = hashlib.sha256()
        for child in sorted(target.rglob("*")):
            if child.is_file():
                h.update(child.relative_to(target).as_posix().encode("utf-8"))
                h.update(hashlib.sha256(child.read_bytes()).digest())
        return h.hexdigest()
    return None


def manual_refresh(
    project_root: Path,
    store_root: Path,
    *,
    snapshot_path: Path | None = None,
) -> Result[dict[str, Any]]:
    """Non-Git & working-tree refresh using live source SHA-256 fingerprints; flags missing sources unverified."""
    root = project_root.resolve()
    snap_file = snapshot_path or (default_handoff_path(root).with_suffix(".fingerprints.json"))
    previous: dict[str, str] = {}
    if snap_file.is_file():
        try:
            raw = json.loads(snap_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                previous = {str(k): str(v) for k, v in raw.items()}
        except (OSError, json.JSONDecodeError):
            previous = {}

    store = open_store(store_root)
    current_fps: dict[str, str] = {}
    stale_units: list[dict[str, Any]] = []
    unverified_units: list[dict[str, Any]] = []
    current_units: list[str] = []

    for unit_id, unit in sorted(store.units.items()):
        if unit_id in SUPPORT_UNIT_IDS:
            continue
        sources = [
            _normalize_path(s)
            for s in normalize_sources(list(unit.fields.get("sources") or []))
            if not s.lower().startswith(NON_FILE_SOURCE_PREFIXES)
        ]
        missing: list[str] = []
        changed: list[str] = []
        for src in sources:
            fp = _fingerprint_source(root, src)
            if fp is None:
                missing.append(src)
                continue
            current_fps[src] = fp
            if src in previous and previous[src] != fp:
                changed.append(src)
        if missing:
            unverified_units.append({
                "unit_id": unit_id,
                "missing_sources": missing,
                "auto_publish_allowed": False,
            })
        elif changed:
            stale_units.append({"unit_id": unit_id, "changed_sources": changed})
        else:
            current_units.append(unit_id)

    snap_file.parent.mkdir(parents=True, exist_ok=True)
    snap_file.write_text(json.dumps(current_fps, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return Ok({
        "store": str(store_root),
        "snapshot": str(snap_file),
        "stale_units": stale_units,
        "unverified_units": unverified_units,
        "current_units": current_units,
    })
