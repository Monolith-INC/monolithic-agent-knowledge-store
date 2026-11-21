"""Setup, localized guide/glossary generation, and verified legacy migration."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from . import Err, Ok, Result
from .curation import validate_unit_lineage
from .paths import DEFAULT_STORE_DIR, LOCATOR_FILE, inspect_locators, validate_visible_store_path
from .retrieval import GLOSSARY_NAME, SUPPORT_UNIT_IDS, open_store

GUIDE_NAME = "QUERY_GUIDE.md"
MANIFEST_NAME = "manifest.md"

_LOCALIZED_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "guide_title": "Project Knowledge Query Guide",
        "guide_intro": "Use `query.py` with Python 3.12+ (stdlib only) to inspect current project facts before broad file reads.",
        "glossary_title": "Project Glossary",
        "glossary_intro": "Sourced project terms and aliases. Every entry cites its authoritative source.",
        "col_term": "Term",
        "col_aliases": "Aliases",
        "col_def": "Definition",
        "col_source": "Source",
    },
    "pt": {
        "guide_title": "Guia de Consulta do Conhecimento do Projeto",
        "guide_intro": "Use `query.py` com Python 3.12+ (apenas stdlib) para consultar fatos atuais do projeto antes de leituras amplas.",
        "glossary_title": "Glossário do Projeto",
        "glossary_intro": "Termos e sinônimos com fonte verificada. Cada entrada cita sua fonte autoritativa.",
        "col_term": "Termo",
        "col_aliases": "Sinônimos",
        "col_def": "Definição",
        "col_source": "Fonte",
    },
    "es": {
        "guide_title": "Guía de Consulta de Conocimiento del Proyecto",
        "guide_intro": "Usa `query.py` con Python 3.12+ (solo stdlib) para consultar hechos actuales del proyecto antes de lecturas amplias.",
        "glossary_title": "Glosario del Proyecto",
        "glossary_intro": "Términos y alias con fuente verificada. Cada entrada cita su fuente autoritativa.",
        "col_term": "Término",
        "col_aliases": "Alias",
        "col_def": "Definición",
        "col_source": "Fuente",
    },
}


def _locale(language: str) -> dict[str, str]:
    key = (language or "en").strip().lower().split("-")[0]
    return _LOCALIZED_TEXT.get(key, _LOCALIZED_TEXT["en"])


def _render_query_guide(language: str, rel_root: str) -> str:
    loc = _locale(language)
    return (
        f"# {loc['guide_title']}\n\n"
        f"{loc['guide_intro']}\n\n"
        f"- Store root: `{rel_root}`\n"
        f"- Locator: `{LOCATOR_FILE}`\n"
        f"- Commands: `catalog`, `find`, `fetch` (`--history`), `glossary`, `links`, `rebuild-catalog`, `curate`, `validate-lineage`\n"
    )


def _render_glossary(language: str) -> str:
    loc = _locale(language)
    return (
        f"# {loc['glossary_title']}\n\n"
        f"{loc['glossary_intro']}\n\n"
        f"| {loc['col_term']} | {loc['col_aliases']} | {loc['col_def']} | {loc['col_source']} |\n"
        f"| --- | --- | --- | --- |\n"
    )


def _render_manifest(rel_root: str, language: str) -> str:
    return (
        "---\n"
        "schema_version: 1\n"
        f"store_root: {rel_root}\n"
        f"language: {language}\n"
        "---\n\n"
        "# Project Knowledge Store\n\n"
        "Five-tier Markdown knowledge store (`identity`, `structure`, `mechanics`, `rules`, `evolution`).\n"
    )


def _write_locator(
    project_root: Path,
    *,
    rel_root: str,
    language: str,
    tracked: bool,
    migrated_from: str | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "knowledgeRoot": rel_root,
        "language": language,
        "tracked": tracked,
    }
    if migrated_from:
        payload["migratedFrom"] = migrated_from
    path = project_root / LOCATOR_FILE
    tmp = project_root / f".{LOCATOR_FILE}.tmp"
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def _ensure_gitignore_rule(project_root: Path, rel_root: str) -> None:
    if not (project_root / ".git").exists():
        return
    gitignore = project_root / ".gitignore"
    rule = f"/{rel_root}/"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = existing.splitlines()
    if rule not in lines:
        sep = "\n" if existing and not existing.endswith("\n") else ""
        gitignore.write_text(f"{existing}{sep}{rule}\n", encoding="utf-8", newline="\n")


def setup_store(
    project_root: Path,
    *,
    rel_root: str = DEFAULT_STORE_DIR,
    language: str = "en",
    local_only: bool = False,
) -> Result[dict[str, Any]]:
    """Create a visible knowledge store, single locator, localized guide/glossary, and catalog."""
    root = project_root.resolve()
    checked = validate_visible_store_path(root, rel_root)
    if isinstance(checked, Err):
        return checked
    norm_rel, store_dir = checked.value

    loc_state = inspect_locators(root)
    if isinstance(loc_state, Err):
        return loc_state
    if loc_state.value.active_rel and loc_state.value.active_rel != norm_rel:
        return Err(
            "locator_conflict",
            f"Project already uses store {loc_state.value.active_rel!r} (via {loc_state.value.locator_source}). "
            f"Use migrate to move to {norm_rel!r} rather than creating a second store.",
        )

    store_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in (
        (MANIFEST_NAME, _render_manifest(norm_rel, language)),
        (GUIDE_NAME, _render_query_guide(language, norm_rel)),
        (GLOSSARY_NAME, _render_glossary(language)),
    ):
        target = store_dir / filename
        if not target.exists():
            target.write_text(content, encoding="utf-8", newline="\n")

    store = open_store(store_dir)
    store.write_catalog()
    unit_count = len([row for row in store.catalog() if row["id"] not in SUPPORT_UNIT_IDS])

    tracked = not local_only
    locator_path = _write_locator(root, rel_root=norm_rel, language=language, tracked=tracked)
    if local_only:
        _ensure_gitignore_rule(root, norm_rel)

    return Ok({
        "store": str(store_dir),
        "knowledgeRoot": norm_rel,
        "locator": str(locator_path),
        "language": language,
        "tracked": tracked,
        "unit_count": unit_count,
        "needs_population": unit_count == 0,
    })


def _sha256_tree(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".md", ".tsv"} and path.name != "catalog.tsv":
            rel = path.relative_to(root).as_posix()
            digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def migrate_store(
    project_root: Path,
    *,
    legacy_rel: str,
    target_rel: str = DEFAULT_STORE_DIR,
    language: str = "en",
    local_only: bool = False,
    simulate_interrupt: bool = False,
) -> Result[dict[str, Any]]:
    """Copy a legacy store to a visible path, verify bytes & lineage, rebuild catalog, keep recovery copy."""
    root = project_root.resolve()
    checked = validate_visible_store_path(root, target_rel)
    if isinstance(checked, Err):
        return checked
    norm_target, target_dir = checked.value

    norm_legacy = legacy_rel.strip().replace("\\", "/").strip("/")
    legacy_dir = (root / norm_legacy).resolve()
    if not legacy_dir.is_relative_to(root) or not legacy_dir.is_dir():
        return Err("legacy_missing", f"Legacy store directory {legacy_rel!r} does not exist inside the project.")
    if target_dir.exists() and any(target_dir.iterdir()):
        return Err("target_occupied", f"Target store {norm_target!r} already exists and is not empty; refusing to merge.")

    source_digests = _sha256_tree(legacy_dir)
    with tempfile.TemporaryDirectory(prefix="maks-migrate-", dir=str(root)) as staging_raw:
        staging = Path(staging_raw) / "staged"
        shutil.copytree(legacy_dir, staging, ignore=shutil.ignore_patterns(".locks", "knowledge-write.lock", "*.tmp"))

        if simulate_interrupt:
            return Err(
                "migration_interrupted",
                "Migration interrupted before switching locator; legacy store and previous locator remain intact.",
            )

        staged_digests = _sha256_tree(staging)
        if staged_digests != source_digests:
            return Err("verification_failed", "Copied store digests do not match legacy source; migration aborted.")

        # Validate lineage & rebuild catalog before publishing
        staged_store = open_store(staging)
        issues = [
            issue
            for uid, unit in sorted(staged_store.units.items())
            if unit.fmt == "md"
            for issue in validate_unit_lineage(uid, unit.body)
        ]
        if issues:
            return Err("lineage_invalid", "Legacy store has lineage issues; migration pending.", detail={"issues": issues})

        for filename, content in (
            (MANIFEST_NAME, _render_manifest(norm_target, language)),
            (GUIDE_NAME, _render_query_guide(language, norm_target)),
            (GLOSSARY_NAME, _render_glossary(language)),
        ):
            if not (staging / filename).exists():
                (staging / filename).write_text(content, encoding="utf-8", newline="\n")

        staged_store.write_catalog()
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(target_dir))

    tracked = not local_only
    locator_path = _write_locator(
        root,
        rel_root=norm_target,
        language=language,
        tracked=tracked,
        migrated_from=norm_legacy,
    )
    if local_only:
        _ensure_gitignore_rule(root, norm_target)

    return Ok({
        "migrated_from": norm_legacy,
        "recovery_copy_preserved": str(legacy_dir),
        "knowledgeRoot": norm_target,
        "store": str(target_dir),
        "locator": str(locator_path),
        "verified_files": len(source_digests),
        "tracked": tracked,
    })
