"""Transient AI-draft store. JSON files in <vault>/drafts/<uuid>.json with a 24h TTL."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

DRAFT_TTL_SECONDS = 24 * 3600


@dataclass
class Draft:
    draft_id: str
    src_path: str
    sha256: str
    suggested_mode: str  # "move" | "reference"
    title: str
    intro: str
    tags: list[str] = field(default_factory=list)
    note: str | None = None      # e.g. "pdf has no extractable text"
    error: str | None = None     # if LLM call failed
    created_at: float = field(default_factory=time.time)


def _drafts_dir(vault_root: Path) -> Path:
    d = vault_root / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    return uuid.uuid4().hex


def save(vault_root: Path, draft: Draft) -> Path:
    p = _drafts_dir(vault_root) / f"{draft.draft_id}.json"
    p.write_text(json.dumps(asdict(draft), indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def load(vault_root: Path, draft_id: str) -> Draft | None:
    p = _drafts_dir(vault_root) / f"{draft_id}.json"
    if not p.is_file():
        return None
    raw = json.loads(p.read_text(encoding="utf-8"))
    return Draft(**raw)


def delete(vault_root: Path, draft_id: str) -> None:
    p = _drafts_dir(vault_root) / f"{draft_id}.json"
    p.unlink(missing_ok=True)


def sweep_expired(vault_root: Path) -> int:
    """Delete drafts older than DRAFT_TTL_SECONDS. Returns count removed."""
    n = 0
    cutoff = time.time() - DRAFT_TTL_SECONDS
    for p in _drafts_dir(vault_root).glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n


__all__ = ["Draft", "DRAFT_TTL_SECONDS", "delete", "load", "new_id", "save", "sweep_expired"]
