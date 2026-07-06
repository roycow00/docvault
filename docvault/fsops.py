"""Crash-safe filesystem primitives shared by ingest, trash, and undo.

Invariant: at no instant may the only on-disk copy of a document be partial
or clobbered. Concretely:

  - copies go to a `.partial` sibling, fsync, then atomic rename
  - moves never overwrite an existing destination
  - moves that cross a volume boundary are copy -> hash-verify -> delete-source
    (plain shutil.move would delete the source after an unverified copy)
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from docvault.hashing import sha256_file


class DestinationExistsError(OSError):
    """Refused to move/copy because the destination already exists."""


def fsync_dir(path: Path) -> None:
    """Flush a directory entry to disk so a rename survives power loss.

    No-op on Windows: directory handles cannot be fsynced there; NTFS
    journals metadata itself."""
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_copy(src: Path, dst: Path) -> None:
    """Copy via .partial sibling, fsync, then atomic rename. Never overwrites
    an existing dst. Removes the .partial on failure."""
    if dst.exists():
        raise DestinationExistsError(f"refusing to overwrite {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    partial = dst.with_suffix(dst.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    try:
        # copy2 preserves mtime; we re-open to fsync.
        shutil.copy2(src, partial)
        with partial.open("rb+") as f:
            f.flush()
            os.fsync(f.fileno())
        partial.replace(dst)
        fsync_dir(dst.parent)
    except BaseException:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def safe_move(src: Path, dst: Path) -> None:
    """Move src -> dst without clobbering and without an unverified-copy window.

    Same volume: atomic rename. Cross volume (or rename failure): copy with
    atomic_copy, hash-verify the copy against the source, only then delete
    the source."""
    if dst.exists():
        raise DestinationExistsError(f"refusing to overwrite {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
        fsync_dir(dst.parent)
        return
    except OSError:
        pass  # cross-volume (EXDEV) or similar — fall through to copy+verify
    src_sha = sha256_file(src)
    atomic_copy(src, dst)
    if sha256_file(dst) != src_sha:
        dst.unlink(missing_ok=True)
        raise OSError(f"verified copy failed moving {src} -> {dst}; source untouched")
    os.unlink(src)


def trash_file(
    vault_root: Path,
    file_path: Path,
    *,
    sha256: str,
    original_path: str | None = None,
    dt: datetime | None = None,
) -> Path:
    """Move a file into <vault>/trash/YYYY-MM/ with a sidecar JSON.

    The sidecar is written first so the entry is always discoverable, then
    the file is moved with safe_move (verified if cross-volume)."""
    from docvault import metadata as M
    from docvault import paths as P

    dt = dt or datetime.now()
    trash_root = P.trash_dir(vault_root, dt)
    trash_root.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex
    dest = trash_root / f"{uid}_{P.safe_name(file_path.name)}"
    sidecar = trash_root / f"{uid}.deleted.json"
    sidecar.write_text(
        json.dumps(
            {
                "uuid": uid,
                "sha256": sha256,
                "original_path": original_path or str(file_path),
                "moved_to": str(dest),
                "deleted_at": M.iso_now(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    safe_move(file_path, dest)
    return dest


__all__ = [
    "DestinationExistsError",
    "atomic_copy",
    "fsync_dir",
    "safe_move",
    "trash_file",
]
