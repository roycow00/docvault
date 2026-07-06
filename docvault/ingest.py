"""Six-step safe-copy ingest pipeline.

Hard guarantee: at no moment may the file's only on-disk copy disappear.

Order for mode="move":
  1. hash source
  2. dedupe scan
  3. copy source → vault target (`.partial` then atomic rename, fsync)
  4. verify by re-hashing target
  5. write metadata (atomic temp+rename+fsync, then read-back parse)
  6. orphan source to .pending-cleanup/  (the only step that touches the original)

Order for mode="reference":
  1. hash source (read-only)
  2. dedupe scan
  3. write metadata pointing at the absolute external path
  Source is never touched.

Fault injection (testing only): set DOCVAULT_FAULT_INJECT to one of
  {copy, verify, meta, orphan} to raise IngestFault *after* that step. Used by
  tests to confirm the no-loss invariant under interruption.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict

from docvault import fsops
from docvault import metadata as M
from docvault import paths as P
from docvault.hashing import FileInaccessibleError, sha256_file


class IngestError(Exception):
    pass


class DuplicateError(IngestError):
    """Raised when sha256 already exists in the vault. Carries the existing record."""

    def __init__(self, existing: M.Metadata):
        super().__init__(f"duplicate sha256: {existing.sha256}")
        self.existing = existing


class IngestVerifyError(IngestError):
    """Raised when the post-copy hash check fails."""


class IngestFault(IngestError):
    """Synthetic error from DOCVAULT_FAULT_INJECT. Test-only."""


Mode = Literal["move", "reference"]


class MetadataDraft(TypedDict, total=False):
    title: str
    intro: str
    tags: list[str]


@dataclass
class IngestResult:
    metadata: M.Metadata
    meta_path: Path
    target_path: Path  # for managed: vault path; for external: src path
    pending_cleanup_id: str | None = None  # uuid for managed, None for reference
    duplicate_of: M.Metadata | None = None


def _fault(step: str) -> None:
    if os.environ.get("DOCVAULT_FAULT_INJECT") == step:
        raise IngestFault(f"fault injected after step={step}")


def _file_created_iso(src: Path) -> str:
    st = src.stat()
    ts = getattr(st, "st_birthtime", None) or st.st_mtime
    return M.iso_from_timestamp(ts)


def _guess_mime(src: Path) -> str:
    mime, _ = mimetypes.guess_type(src.name)
    return mime or "application/octet-stream"


def _find_duplicate(vault_root: Path, sha256: str) -> M.Metadata | None:
    for m in M.iter_all(vault_root):
        if m.sha256 == sha256:
            return m
    return None


def _claim_paths(
    vault_root: Path, sha256: str, original_name: str, dt: datetime
) -> tuple[Path, Path]:
    """Pick (target, meta) paths that don't clobber an existing record.

    The default 6-char sha prefix can collide across different documents that
    share a filename; silently overwriting the earlier document would be data
    loss. On collision, lengthen the prefix until both paths are free."""
    for n in (6, 12, len(sha256)):
        target = P.vault_path_for(vault_root, sha256, original_name, dt, prefix_len=n)
        meta = P.meta_path_for(vault_root, sha256, original_name, dt, prefix_len=n)
        if not target.exists() and not meta.exists():
            return target, meta
    raise IngestError(
        f"cannot claim a vault path for sha256={sha256} name={original_name!r}: "
        f"even the full-sha path is occupied; refusing to overwrite"
    )


def _claim_meta_path(
    vault_root: Path, sha256: str, original_name: str, dt: datetime
) -> Path:
    for n in (6, 12, len(sha256)):
        meta = P.meta_path_for(vault_root, sha256, original_name, dt, prefix_len=n)
        if not meta.exists():
            return meta
    raise IngestError(
        f"cannot claim a metadata path for sha256={sha256}; refusing to overwrite"
    )


def _orphan_source(src: Path, sha256: str, vault_root: Path, dt: datetime) -> str:
    """Move the source to .pending-cleanup/ with a sidecar JSON. Returns the uuid.

    The sidecar is written *before* the move so the entry (original path, sha)
    is always discoverable even if we crash mid-move."""
    cleanup_id = uuid.uuid4().hex
    cleanup_dir = P.pending_cleanup_dir(vault_root, dt)
    cleanup_dir.mkdir(parents=True, exist_ok=True)
    target = cleanup_dir / f"{cleanup_id}_{P.safe_name(src.name)}"
    sidecar = cleanup_dir / f"{cleanup_id}.json"

    sidecar.write_text(
        json.dumps(
            {
                "uuid": cleanup_id,
                "original_path": str(src),
                "moved_to": str(target),
                "sha256": sha256,
                "ingested_at": M.iso_now(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # safe_move: atomic rename same-volume; copy + hash-verify + delete otherwise.
    fsops.safe_move(src, target)
    return cleanup_id


def _verified_meta_write(meta_path: Path, m: M.Metadata) -> None:
    M.dump(meta_path, m)
    parsed = M.load(meta_path)
    if parsed != m:
        raise IngestVerifyError(f"metadata round-trip mismatch at {meta_path}")


def _build_metadata(
    *,
    src: Path,
    sha256: str,
    draft: MetadataDraft,
    location: M.Location,
    dt_ingested: datetime,
) -> M.Metadata:
    title = draft.get("title") or Path(src.name).stem
    intro = draft.get("intro") or ""
    tags = list(draft.get("tags") or [])
    return M.Metadata(
        title=title,
        intro=intro,
        tags=tags,
        file_created=_file_created_iso(src),
        ingested=dt_ingested.replace(microsecond=0).isoformat(),
        sha256=sha256,
        original_filename=src.name,
        location=location,
        mime=_guess_mime(src),
        size=src.stat().st_size,
    )


def ingest_manual(
    src: Path,
    draft: MetadataDraft,
    *,
    mode: Mode,
    vault_root: Path,
) -> IngestResult:
    src = src.resolve()
    if not src.is_file():
        raise FileInaccessibleError(f"not a file: {src}")

    # Step 1 — hash source
    sha = sha256_file(src)

    # Step 2 — dedupe
    existing = _find_duplicate(vault_root, sha)
    if existing is not None:
        return IngestResult(
            metadata=existing,
            meta_path=Path(),  # caller looks up via sha if needed
            target_path=P.resolve(existing.location, vault_root),
            duplicate_of=existing,
        )

    dt_ingested = datetime.now()

    if mode == "reference":
        location = M.Location(
            type="external",
            path=str(src),
            source=P.is_protected_source(src),
        )
        meta = _build_metadata(src=src, sha256=sha, draft=draft, location=location, dt_ingested=dt_ingested)
        meta_path = _claim_meta_path(vault_root, sha, src.name, dt_ingested)
        _verified_meta_write(meta_path, meta)
        return IngestResult(metadata=meta, meta_path=meta_path, target_path=src)

    # mode == "move"
    target, meta_path = _claim_paths(vault_root, sha, src.name, dt_ingested)

    # Step 3 — copy
    fsops.atomic_copy(src, target)
    _fault("copy")

    # Step 4 — verify
    sha_target = sha256_file(target)
    if sha_target != sha or target.stat().st_size != src.stat().st_size:
        try:
            target.unlink(missing_ok=True)
        finally:
            raise IngestVerifyError(
                f"copy hash mismatch: src={sha} dst={sha_target} (target removed; source untouched)"
            )
    _fault("verify")

    # Step 5 — metadata
    rel = P.to_relative_posix(target, vault_root)
    location = M.Location(type="vault", path=rel)
    meta = _build_metadata(src=src, sha256=sha, draft=draft, location=location, dt_ingested=dt_ingested)
    _verified_meta_write(meta_path, meta)
    _fault("meta")

    # Step 6 — orphan source
    cleanup_id = _orphan_source(src, sha, vault_root, dt_ingested)
    _fault("orphan")

    return IngestResult(
        metadata=meta,
        meta_path=meta_path,
        target_path=target,
        pending_cleanup_id=cleanup_id,
    )


def convert_to_managed(sha: str, *, vault_root: Path) -> IngestResult:
    """Promote an external record to a managed (in-vault) record."""
    existing: M.Metadata | None = None
    existing_meta_path: Path | None = None
    for md in (vault_root / "meta").rglob("*.md"):
        m = M.load(md)
        if m.sha256 == sha:
            existing = m
            existing_meta_path = md
            break
    if existing is None or existing_meta_path is None:
        raise IngestError(f"no record with sha256={sha}")
    if existing.location.type == "vault":
        raise IngestError(f"already managed: {sha}")

    src = Path(existing.location.path)
    if not src.is_file():
        raise FileInaccessibleError(f"external file not found: {src}")

    dt_ingested = datetime.now()
    # _claim_paths never returns an occupied path, so the old meta file (still
    # on disk) can't be clobbered; it is deleted only after the new one is safe.
    target, new_meta_path = _claim_paths(vault_root, sha, src.name, dt_ingested)
    fsops.atomic_copy(src, target)
    sha_target = sha256_file(target)
    if sha_target != sha:
        target.unlink(missing_ok=True)
        raise IngestVerifyError(f"copy hash mismatch promoting {sha}")

    rel = P.to_relative_posix(target, vault_root)
    promoted = replace(existing, location=M.Location(type="vault", path=rel))
    _verified_meta_write(new_meta_path, promoted)
    if new_meta_path != existing_meta_path:
        existing_meta_path.unlink(missing_ok=True)
    cleanup_id = _orphan_source(src, sha, vault_root, dt_ingested)
    return IngestResult(
        metadata=promoted,
        meta_path=new_meta_path,
        target_path=target,
        pending_cleanup_id=cleanup_id,
    )


def undo_ingest(cleanup_id: str, *, vault_root: Path) -> Path:
    """Restore an orphaned source from .pending-cleanup/ back to its original
    path, then retire the vault copy and its metadata to trash/ (recoverable
    for the trash retention window) so the ingest is fully reverted.

    If the original path is now occupied, the file is left in pending-cleanup
    and a `.collision.json` marker is written (which also shields the entry
    from the retention purge); the function still returns the pending-cleanup
    path so the caller can show a banner. The vault record is kept in that case."""
    cleanup_root = vault_root / ".pending-cleanup"
    sidecar = None
    for j in cleanup_root.rglob(f"{cleanup_id}.json"):
        sidecar = j
        break
    if sidecar is None:
        raise IngestError(f"no pending-cleanup entry: {cleanup_id}")
    info = json.loads(sidecar.read_text(encoding="utf-8"))
    moved_to = Path(info["moved_to"])
    original = Path(info["original_path"])
    if not moved_to.is_file():
        raise IngestError(f"orphaned file missing: {moved_to}")
    if original.exists():
        marker = sidecar.with_suffix(".collision.json")
        marker.write_text(
            json.dumps({"reason": "original path occupied", "checked_at": M.iso_now()}, indent=2),
            encoding="utf-8",
        )
        return moved_to
    original.parent.mkdir(parents=True, exist_ok=True)
    fsops.safe_move(moved_to, original)
    sidecar.unlink(missing_ok=True)

    # Source is safely back — now retire the vault record. Failures here leave
    # a harmless duplicate (source + vault copy), never a loss.
    sha = info.get("sha256")
    if sha:
        try:
            _retire_vault_record(vault_root, sha)
        except OSError:
            pass
    return original


def _retire_vault_record(vault_root: Path, sha256: str) -> None:
    """Move the managed file + metadata for `sha256` to trash/, if present."""
    for md in (vault_root / "meta").rglob("*.md"):
        try:
            m = M.load(md)
        except Exception:
            continue
        if m.sha256 != sha256 or m.location.type != "vault":
            continue
        target = P.resolve(m.location, vault_root)
        if target.is_file():
            fsops.trash_file(vault_root, target, sha256=sha256, original_path=str(target))
        fsops.trash_file(vault_root, md, sha256=sha256, original_path=str(md))
        return


__all__ = [
    "DuplicateError",
    "IngestError",
    "IngestFault",
    "IngestResult",
    "IngestVerifyError",
    "MetadataDraft",
    "Mode",
    "convert_to_managed",
    "ingest_manual",
    "undo_ingest",
]
