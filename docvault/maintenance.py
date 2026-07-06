"""Maintenance routines: pending-cleanup purge, trash purge, vault verify.

These are run by the `cleanup`, `empty-trash`, and `verify` CLI commands.
A lightweight subset (`startup_maintenance`) runs opportunistically when the
server starts.

Safety rules encoded here:
  - A .pending-cleanup entry is only ever purged after re-verifying that the
    vault still holds a healthy copy of that content (record exists, file
    present, hash matches). If the vault copy is gone or corrupt, the pending
    file may be the last good copy — it is kept and reported instead.
  - Entries with a `.collision.json` marker (a failed undo) are never purged
    automatically; the user asked for that file back.
  - `*.partial` debris is only removed once it is old enough that no live
    ingest can still be writing it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from docvault import metadata as M
from docvault import paths as P
from docvault.config import Config
from docvault.hashing import FileInaccessibleError, sha256_file

# A .partial younger than this may belong to an in-flight ingest (possibly in
# another process); never delete those.
PARTIAL_MIN_AGE_SECONDS = 3600.0


@dataclass
class PurgeResult:
    removed: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


@dataclass
class VerifyIssue:
    sha256: str
    meta_path: Path
    kind: str  # "missing_file" | "hash_mismatch" | "external_unreachable" | "parse_error"
    detail: str


@dataclass
class VerifyResult:
    checked: int = 0
    issues: list[VerifyIssue] = field(default_factory=list)
    cleaned_partials: list[Path] = field(default_factory=list)


def _iter_sidecars(root: Path) -> Iterator[tuple[Path, Path, dict]]:
    """Yield (sidecar.json, file_path, info) triples under root."""
    if not root.is_dir():
        return
    for sidecar in root.rglob("*.json"):
        if sidecar.name.endswith(".collision.json"):
            continue  # undo-collision marker, not a real sidecar
        try:
            info = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "moved_to" in info:
            target = Path(info["moved_to"])
        else:
            uid = info.get("uuid") or sidecar.stem.split(".")[0]
            # find a sibling file starting with this uuid
            target = next(
                (p for p in sidecar.parent.iterdir() if p.name.startswith(uid + "_") and p.is_file()),
                None,  # type: ignore[assignment]
            )
            if target is None:
                continue
        yield sidecar, target, info


def _age_seconds(p: Path) -> float:
    try:
        return (datetime.now().timestamp() - p.stat().st_mtime)
    except OSError:
        return 0.0


def _vault_records_by_sha(vault_root: Path) -> dict[str, M.Metadata]:
    return {m.sha256: m for m in M.iter_all(vault_root)}


def _vault_copy_is_healthy(vault_root: Path, sha256: str, records: dict[str, M.Metadata]) -> tuple[bool, str]:
    """True iff the vault still has a verified copy of this content."""
    m = records.get(sha256)
    if m is None:
        return False, "no vault record for this sha256"
    target = P.resolve(m.location, vault_root)
    if not target.is_file():
        return False, f"vault file missing: {target}"
    try:
        actual = sha256_file(target)
    except FileInaccessibleError as e:
        return False, f"vault file unreadable: {e}"
    if actual != sha256:
        return False, f"vault file hash mismatch: {target}"
    return True, ""


def purge_pending_cleanup(cfg: Config, *, dry_run: bool = False) -> PurgeResult:
    """Remove .pending-cleanup/ entries older than cleanup.retention_days.

    An entry is only removed if the vault provably still holds that content;
    otherwise it is kept and reported (the pending file may be the last copy)."""
    res = PurgeResult()
    cutoff = timedelta(days=cfg.cleanup.retention_days).total_seconds()
    root = cfg.vault_root / ".pending-cleanup"
    records: dict[str, M.Metadata] | None = None  # built lazily, only if something expired
    for sidecar, file_path, info in _iter_sidecars(root):
        age = _age_seconds(sidecar)
        if age < cutoff:
            res.kept.append(file_path)
            continue
        if sidecar.with_suffix(".collision.json").exists():
            res.kept.append(file_path)
            res.errors.append((file_path, "kept: a failed undo marked this entry for manual attention"))
            continue
        sha = info.get("sha256")
        if file_path.is_file() and sha:
            if records is None:
                records = _vault_records_by_sha(cfg.vault_root)
            healthy, why = _vault_copy_is_healthy(cfg.vault_root, sha, records)
            if not healthy:
                res.kept.append(file_path)
                res.errors.append((file_path, f"kept: possibly the last copy — {why}"))
                continue
        if dry_run:
            res.removed.append(file_path)
            continue
        try:
            if file_path.is_file():
                file_path.unlink()
            sidecar.unlink(missing_ok=True)
            res.removed.append(file_path)
        except OSError as e:
            res.errors.append((file_path, str(e)))
    return res


def purge_trash(cfg: Config, *, dry_run: bool = False) -> PurgeResult:
    """Remove trash/ entries older than trash.retention_days."""
    res = PurgeResult()
    cutoff = timedelta(days=cfg.trash.retention_days).total_seconds()
    root = cfg.vault_root / "trash"
    for sidecar, file_path, _info in _iter_sidecars(root):
        age = _age_seconds(sidecar)
        if age < cutoff:
            res.kept.append(file_path)
            continue
        if dry_run:
            res.removed.append(file_path)
            continue
        try:
            if file_path.is_file():
                file_path.unlink()
            sidecar.unlink(missing_ok=True)
            res.removed.append(file_path)
        except OSError as e:
            res.errors.append((file_path, str(e)))
    return res


def clean_stale_partials(
    cfg: Config, *, dry_run: bool = False, min_age_seconds: float = PARTIAL_MIN_AGE_SECONDS
) -> list[Path]:
    """Remove *.partial debris in files/ and meta/ older than min_age_seconds.

    Fresh partials are left alone: they may belong to an ingest that is
    happening right now in another process."""
    cleaned: list[Path] = []
    for sub in ("files", "meta"):
        root = cfg.vault_root / sub
        if not root.is_dir():
            continue
        for partial in root.rglob("*.partial"):
            if _age_seconds(partial) < min_age_seconds:
                continue
            if dry_run:
                cleaned.append(partial)
                continue
            try:
                partial.unlink()
                cleaned.append(partial)
            except OSError:
                pass
    return cleaned


def verify(cfg: Config, *, dry_run: bool = False) -> VerifyResult:
    """Walk meta/, validate every record. Optionally clean stale *.partial debris.

    For managed files we re-hash and compare against the sha256 field.
    For external files we only check existence (we don't trust we still have read access).
    """
    res = VerifyResult()
    vault = cfg.vault_root

    res.cleaned_partials = clean_stale_partials(cfg, dry_run=dry_run)

    meta_root = vault / "meta"
    if not meta_root.is_dir():
        return res

    for md in sorted(meta_root.rglob("*.md")):
        try:
            m = M.load(md)
        except Exception as e:
            res.issues.append(VerifyIssue(sha256="?", meta_path=md, kind="parse_error", detail=str(e)))
            continue
        res.checked += 1
        target = P.resolve(m.location, vault)
        if m.location.type == "vault":
            if not target.is_file():
                res.issues.append(
                    VerifyIssue(m.sha256, md, "missing_file", f"vault file not found: {target}")
                )
                continue
            actual = sha256_file(target)
            if actual != m.sha256:
                res.issues.append(
                    VerifyIssue(m.sha256, md, "hash_mismatch", f"target={target} actual_sha={actual}")
                )
        else:  # external
            if not target.exists():
                res.issues.append(
                    VerifyIssue(m.sha256, md, "external_unreachable", f"path not present: {target}")
                )
    return res


__all__ = [
    "PARTIAL_MIN_AGE_SECONDS",
    "PurgeResult",
    "VerifyIssue",
    "VerifyResult",
    "clean_stale_partials",
    "purge_pending_cleanup",
    "purge_trash",
    "verify",
]
