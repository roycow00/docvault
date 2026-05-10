"""Vault path conventions and protected-source detection.

Paths in metadata for managed files are stored as POSIX strings relative to the
vault root. External paths are absolute and stored verbatim. The Location
dataclass lives in metadata.py; this module is path-string only to avoid an
import cycle.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docvault.metadata import Location


_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_MAX_NAME = 80

# Substrings (case-insensitive) that mark a path as "protected source".
# Matching one of these triggers the "Reference in place" default at ingest.
# Patterns are stored with forward slashes; the input path is normalized
# (lowercased, backslashes → forward slashes) before matching.
PROTECTED_PATTERNS: dict[str, tuple[str, ...]] = {
    "onedrive_personal_vault": (
        "/onedrive/personal vault/",            # English / many European locales
        "/onedrive/个人保管库/",                  # Simplified Chinese
        "/onedrive/個人保存庫/",                  # Traditional Chinese
        "/onedrive/個人用 vault/",                # Japanese
        "/onedrive/persönlicher tresor/",       # German
        "/onedrive/coffre-fort personnel/",     # French
        "/onedrive/almacén personal/",          # Spanish
    ),
}


def safe_name(name: str) -> str:
    """Sanitize a filename. Replaces Windows-illegal chars with `_`, collapses
    whitespace, truncates the stem to MAX_NAME chars, preserves the extension."""
    cleaned_full = _ILLEGAL.sub("_", name)
    p = Path(cleaned_full)
    stem = _WHITESPACE.sub(" ", p.stem).strip()
    if not stem:
        stem = "untitled"
    if len(stem) > _MAX_NAME:
        stem = stem[:_MAX_NAME].rstrip()
    return stem + p.suffix


def _yyyymm(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def vault_files_dir(vault_root: Path, dt: datetime) -> Path:
    # Files moved into the vault land in a per-day archive folder named
    # `#Archived-YYYY-MM-DD` directly under the vault root. The leading `#`
    # sorts these grouping folders together and keeps them visually distinct
    # from `meta/`, `trash/`, etc. Records ingested under the older
    # `files/YYYY-MM/` layout keep their existing relative paths in metadata
    # — `vault_path_for` is only consulted for new copies.
    return vault_root / f"#Archived-{_yyyymmdd(dt)}"


def vault_important_dir(vault_root: Path) -> Path:
    # Files marked `important` bypass the date-archive layout and live in a
    # single flat folder so the user can scan them at a glance. Toggling
    # the flag on an existing record relocates the file between this folder
    # and the date-archive folder (see ingest.relocate_for_important).
    return vault_root / "Important"


def vault_meta_dir(vault_root: Path, dt: datetime) -> Path:
    return vault_root / "meta" / _yyyymm(dt)


def pending_cleanup_dir(vault_root: Path, dt: datetime) -> Path:
    return vault_root / ".pending-cleanup" / _yyyymmdd(dt)


def trash_dir(vault_root: Path, dt: datetime) -> Path:
    return vault_root / "trash" / _yyyymm(dt)


def stem_for(sha256: str, original_name: str) -> str:
    return f"{sha256[:6]}_{safe_name(original_name)}"


def vault_path_for(
    vault_root: Path,
    sha256: str,
    original_name: str,
    dt: datetime,
    *,
    important: bool = False,
) -> Path:
    parent = vault_important_dir(vault_root) if important else vault_files_dir(vault_root, dt)
    return parent / stem_for(sha256, original_name)


def meta_path_for(vault_root: Path, sha256: str, original_name: str, dt: datetime) -> Path:
    safe = safe_name(original_name)
    base = f"{sha256[:6]}_{Path(safe).stem}.md"
    return vault_meta_dir(vault_root, dt) / base


def to_relative_posix(absolute: Path, vault_root: Path) -> str:
    rel = absolute.resolve().relative_to(vault_root.resolve())
    return PurePosixPath(*rel.parts).as_posix()


def from_relative_posix(rel: str, vault_root: Path) -> Path:
    parts = PurePosixPath(rel).parts
    return vault_root.joinpath(*parts)


def resolve(location: "Location", vault_root: Path) -> Path:
    if location.type == "vault":
        return from_relative_posix(location.path, vault_root)
    return Path(location.path)


def is_protected_source(path: Path | str) -> str | None:
    s = str(path).lower().replace("\\", "/")
    for label, patterns in PROTECTED_PATTERNS.items():
        for pat in patterns:
            if pat in s:
                return label
    return None
