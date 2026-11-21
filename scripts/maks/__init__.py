"""Monolithic Agent Knowledge Store — stdlib Python 3.12+ core package."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Generic, TypeVar

T = TypeVar("T")

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_ENGINE_PATH = REPO_ROOT / "vendor" / "review-knowledge" / "adapters" / "knowledge" / "knowledge_store.py"


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T
    ok: bool = True


@dataclass(frozen=True)
class Err:
    code: str
    message: str
    detail: dict | None = None
    ok: bool = False


Result = Ok[T] | Err


@lru_cache(maxsize=1)
def load_engine() -> ModuleType:
    """Load the unchanged vendored knowledge_store module without requiring PYTHONPATH."""
    spec = importlib.util.spec_from_file_location("maks_vendored_knowledge_store", VENDOR_ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Vendored knowledge_store.py not found at {VENDOR_ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
