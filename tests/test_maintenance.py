"""Tests for maintenance routines."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from docvault import ingest as ING
from docvault import metadata as M
from docvault import paths as P
from docvault.config import (
    CleanupCfg,
    Config,
    IngestCfg,
    LLMCfg,
    TrashCfg,
)
from docvault.maintenance import purge_pending_cleanup, purge_trash, verify


def _cfg(vault: Path, *, cleanup_days: int = 30, trash_days: int = 90) -> Config:
    return Config(
        vault_root=vault,
        llm=LLMCfg(),
        ingest=IngestCfg(),
        cleanup=CleanupCfg(retention_days=cleanup_days),
        trash=TrashCfg(retention_days=trash_days),
    )


@pytest.fixture
def src_file(tmp_path: Path) -> Path:
    p = tmp_path / "src" / "doc.txt"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"content here\n" * 50)
    return p


def test_purge_pending_keeps_recent(vault: Path, src_file: Path) -> None:
    ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    cfg = _cfg(vault, cleanup_days=30)
    res = purge_pending_cleanup(cfg)
    assert len(res.kept) == 1
    assert len(res.removed) == 0


def test_purge_pending_removes_old(vault: Path, src_file: Path) -> None:
    res = ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    sidecars = list((vault / ".pending-cleanup").rglob("*.json"))
    files = [p for p in (vault / ".pending-cleanup").rglob("*") if p.is_file() and not p.name.endswith(".json")]
    assert len(sidecars) == 1 and len(files) == 1

    # Backdate
    old = time.time() - 100 * 86400
    for p in sidecars + files:
        os.utime(p, (old, old))

    cfg = _cfg(vault, cleanup_days=30)
    out = purge_pending_cleanup(cfg)
    assert len(out.removed) == 1
    assert len(list((vault / ".pending-cleanup").rglob("*.json"))) == 0


def test_purge_pending_dry_run_does_not_delete(vault: Path, src_file: Path) -> None:
    ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    files = list((vault / ".pending-cleanup").rglob("*"))
    old = time.time() - 100 * 86400
    for p in files:
        if p.is_file():
            os.utime(p, (old, old))

    cfg = _cfg(vault, cleanup_days=30)
    out = purge_pending_cleanup(cfg, dry_run=True)
    assert len(out.removed) >= 1
    # Files still on disk
    assert list((vault / ".pending-cleanup").rglob("*.json"))


def test_verify_happy_path(vault: Path, src_file: Path) -> None:
    ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    cfg = _cfg(vault)
    res = verify(cfg)
    assert res.checked == 1
    assert res.issues == []


def test_verify_detects_missing_managed_file(vault: Path, src_file: Path) -> None:
    res = ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    res.target_path.unlink()
    cfg = _cfg(vault)
    out = verify(cfg)
    assert out.checked == 1
    kinds = [i.kind for i in out.issues]
    assert "missing_file" in kinds


def test_verify_detects_hash_mismatch(vault: Path, src_file: Path) -> None:
    res = ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    res.target_path.write_bytes(b"tampered")
    cfg = _cfg(vault)
    out = verify(cfg)
    assert any(i.kind == "hash_mismatch" for i in out.issues)


def test_verify_cleans_stale_partial_debris(vault: Path) -> None:
    files_dir = vault / "files" / "2026-05"
    files_dir.mkdir(parents=True)
    junk = files_dir / "abc_doc.pdf.partial"
    junk.write_bytes(b"junk")
    old = time.time() - 7200  # older than PARTIAL_MIN_AGE_SECONDS
    os.utime(junk, (old, old))
    cfg = _cfg(vault)
    out = verify(cfg)
    assert junk in out.cleaned_partials
    assert not junk.exists()


def test_verify_keeps_fresh_partials(vault: Path) -> None:
    """A fresh .partial may belong to an in-flight ingest and must survive."""
    files_dir = vault / "#Archived-2026-05-01"
    files_dir.mkdir(parents=True)
    junk = files_dir / "abc_doc.pdf.partial"
    junk.write_bytes(b"live ingest in another process")
    cfg = _cfg(vault)
    out = verify(cfg)
    assert junk not in out.cleaned_partials
    assert junk.exists()


def test_purge_pending_keeps_last_copy_when_vault_copy_lost(
    vault: Path, src_file: Path
) -> None:
    """If the vault copy has vanished, the expired pending entry is the last
    copy of the document and must never be purged."""
    res = ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    res.target_path.unlink()  # simulate vault copy loss (sync conflict, bit rot…)

    old = time.time() - 100 * 86400
    for p in (vault / ".pending-cleanup").rglob("*"):
        if p.is_file():
            os.utime(p, (old, old))

    cfg = _cfg(vault, cleanup_days=30)
    out = purge_pending_cleanup(cfg)
    assert len(out.removed) == 0
    assert len(out.kept) == 1
    assert out.errors and "last copy" in out.errors[0][1]
    pending = [
        p for p in (vault / ".pending-cleanup").rglob("*")
        if p.is_file() and p.suffix != ".json"
    ]
    assert len(pending) == 1


def test_purge_pending_keeps_collision_marked_entries(
    vault: Path, src_file: Path
) -> None:
    """Entries a failed undo flagged for manual attention are never purged."""
    res = ING.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    # Occupy the original path so undo collides
    src_file.write_bytes(b"squatter")
    ING.undo_ingest(res.pending_cleanup_id, vault_root=vault)

    old = time.time() - 100 * 86400
    for p in (vault / ".pending-cleanup").rglob("*"):
        if p.is_file():
            os.utime(p, (old, old))

    cfg = _cfg(vault, cleanup_days=30)
    out = purge_pending_cleanup(cfg)
    assert len(out.removed) == 0
    pending = [
        p for p in (vault / ".pending-cleanup").rglob("*")
        if p.is_file() and not p.name.endswith(".json")
    ]
    assert len(pending) == 1


def test_verify_external_unreachable(vault: Path, tmp_path: Path) -> None:
    p = tmp_path / "ext.txt"
    p.write_bytes(b"hi")
    ING.ingest_manual(p, {"title": "x"}, mode="reference", vault_root=vault)
    p.unlink()  # remove the external source
    cfg = _cfg(vault)
    out = verify(cfg)
    assert any(i.kind == "external_unreachable" for i in out.issues)


def test_purge_trash_obeys_retention(vault: Path) -> None:
    """Synthesize a trash entry directly."""
    trash = vault / "trash" / "2026-05"
    trash.mkdir(parents=True)
    f = trash / "uuid_doc.pdf"
    s = trash / "uuid.deleted.json"
    f.write_bytes(b"trashed")
    s.write_text(json.dumps({"uuid": "uuid", "sha256": "x", "deleted_at": "now"}))

    # Recent — keep
    cfg = _cfg(vault, trash_days=90)
    out = purge_trash(cfg)
    assert len(out.removed) == 0
    assert f.is_file()

    # Backdate — purge
    old = time.time() - 200 * 86400
    os.utime(f, (old, old))
    os.utime(s, (old, old))
    out = purge_trash(cfg)
    assert len(out.removed) == 1
    assert not f.exists()
