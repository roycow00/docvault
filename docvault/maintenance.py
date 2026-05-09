"""Maintenance routines: pending-cleanup purge, trash purge, vault verify.

These are run by the `cleanup`, `empty-trash`, and `verify` CLI commands.
They can also be invoked opportunistically on `serve` startup.
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
from docvault.hashing import sha256_file


@dataclass
class PurgeResult:
    removed: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


@dataclass
class VerifyIssue:
    sha256: str
    meta_path: Path
    kind: str  # "missing_file" | "hash_mismatch" | "external_unreachable" | "stale_partial"
    detail: str


@dataclass
class VerifyResult:
    checked: int = 0
    issues: list[VerifyIssue] = field(default_factory=list)
    cleaned_partials: list[Path] = field(default_factory=list)


def _iter_sidecars(root: Path) -> Iterator[tuple[Path, Path]]:
    """Yield (sidecar.json, file_path) pairs under root."""
    if not root.is_dir():
        return
    for sidecar in root.rglob("*.json"):
        try:
            info = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # pending-cleanup uses "moved_to", trash uses the file living next to the sidecar
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
        yield sidecar, target


def _age_seconds(p: Path) -> float:
    try:
        return (datetime.now().timestamp() - p.stat().st_mtime)
    except OSError:
        return 0.0


def purge_pending_cleanup(cfg: Config, *, dry_run: bool = False) -> PurgeResult:
    """Remove .pending-cleanup/ entries older than cleanup.retention_days."""
    res = PurgeResult()
    cutoff = timedelta(days=cfg.cleanup.retention_days).total_seconds()
    root = cfg.vault_root / ".pending-cleanup"
    for sidecar, file_path in _iter_sidecars(root):
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


def purge_trash(cfg: Config, *, dry_run: bool = False) -> PurgeResult:
    """Remove trash/ entries older than trash.retention_days."""
    res = PurgeResult()
    cutoff = timedelta(days=cfg.trash.retention_days).total_seconds()
    root = cfg.vault_root / "trash"
    for sidecar, file_path in _iter_sidecars(root):
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


def verify(cfg: Config, *, dry_run: bool = False) -> VerifyResult:
    """Walk meta/, validate every record. Optionally clean *.partial debris.

    For managed files we re-hash and compare against the sha256 field.
    For external files we only check existence (we don't trust we still have read access).
    """
    res = VerifyResult()
    vault = cfg.vault_root

    # Clean any leftover *.partial files in the per-day archive folders
    # (and the legacy files/ tree for vaults migrated from the older layout).
    partial_roots: list[Path] = [vault / "files"]
    partial_roots.extend(d for d in vault.glob("#Archived-*") if d.is_dir())
    for files_root in partial_roots:
        if not files_root.is_dir():
            continue
        for partial in files_root.rglob("*.partial"):
            if dry_run:
                res.cleaned_partials.append(partial)
                continue
            try:
                partial.unlink()
                res.cleaned_partials.append(partial)
            except OSError:
                pass

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
    "PurgeResult",
    "VerifyIssue",
    "VerifyResult",
    "purge_pending_cleanup",
    "purge_trash",
    "verify",
]
