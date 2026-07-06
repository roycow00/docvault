"""Ingest pipeline tests. The most important ones verify the no-loss invariant
under fault injection at every step of the move pipeline."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from docvault import ingest
from docvault import metadata as M
from docvault.hashing import sha256_file


@pytest.fixture
def src_file(tmp_path: Path) -> Path:
    p = tmp_path / "incoming" / "report.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = b"%PDF-1.4\n" + b"some bytes here\n" * 100
    p.write_bytes(payload)
    return p


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ingest_move_happy_path(vault: Path, src_file: Path) -> None:
    pre_hash = _hash(src_file)
    res = ingest.ingest_manual(
        src_file, {"title": "Report", "tags": ["Finance"]}, mode="move", vault_root=vault
    )

    assert res.duplicate_of is None
    assert res.metadata.location.type == "vault"
    assert res.target_path.is_file()
    assert sha256_file(res.target_path) == pre_hash
    assert not src_file.exists(), "source must be moved out of original location"

    # File now lives in .pending-cleanup/, not lost
    pending = list((vault / ".pending-cleanup").rglob(f"*_{src_file.name}"))
    assert len(pending) == 1
    assert _hash(pending[0]) == pre_hash

    # Sidecar present
    sidecars = list((vault / ".pending-cleanup").rglob("*.json"))
    assert len(sidecars) == 1


def test_ingest_reference_does_not_touch_source(vault: Path, src_file: Path) -> None:
    pre_hash = _hash(src_file)
    res = ingest.ingest_manual(
        src_file, {"title": "Ref"}, mode="reference", vault_root=vault
    )
    assert res.metadata.location.type == "external"
    assert res.metadata.location.path == str(src_file)
    assert src_file.is_file()
    assert _hash(src_file) == pre_hash
    # No vault copy in any archive folder
    assert not list(vault.glob("#Archived-*/*"))


def test_ingest_move_lands_in_archive_folder(vault: Path, src_file: Path) -> None:
    """Move-mode ingests put the file in <vault>/#Archived-YYYY-MM-DD/."""
    res = ingest.ingest_manual(
        src_file, {"title": "X"}, mode="move", vault_root=vault
    )
    assert res.target_path.is_file()
    parent = res.target_path.parent
    assert parent.parent == vault
    assert parent.name.startswith("#Archived-")
    # Date suffix is YYYY-MM-DD (10 chars)
    suffix = parent.name[len("#Archived-"):]
    assert len(suffix) == 10 and suffix[4] == "-" and suffix[7] == "-"


def test_dedupe_returns_existing(vault: Path, src_file: Path, tmp_path: Path) -> None:
    payload = src_file.read_bytes()  # capture before ingest moves the file
    ingest.ingest_manual(src_file, {"title": "First"}, mode="move", vault_root=vault)

    # Second copy with same content, different name, different dir
    second = tmp_path / "other" / "duplicate.pdf"
    second.parent.mkdir(parents=True)
    second.write_bytes(payload)

    res = ingest.ingest_manual(second, {"title": "Second"}, mode="move", vault_root=vault)
    assert res.duplicate_of is not None
    assert res.metadata.title == "First"  # returns the existing record
    # Duplicate source still on disk — we never touch dupes automatically
    assert second.is_file()


@pytest.mark.parametrize("step", ["copy", "verify", "meta", "orphan"])
def test_fault_injection_preserves_source_content(
    vault: Path, src_file: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """After a fault at any step, the file content must still be recoverable
    in at least one location. For copy/verify/meta the source is intact.
    For orphan the source has just been moved to .pending-cleanup and the
    vault copy is also present — both are accessible."""
    pre_hash = _hash(src_file)
    monkeypatch.setenv("DOCVAULT_FAULT_INJECT", step)

    with pytest.raises(ingest.IngestFault):
        ingest.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)

    if step in ("copy", "verify", "meta"):
        assert src_file.is_file(), f"source disappeared after fault at step={step}"
        assert _hash(src_file) == pre_hash
    elif step == "orphan":
        # Source has been moved into pending-cleanup at this point
        assert not src_file.exists()
        pending = list((vault / ".pending-cleanup").rglob(f"*_{src_file.name}"))
        assert len(pending) == 1
        assert _hash(pending[0]) == pre_hash
        # And the vault copy exists too (under the per-day archive folder)
        vault_copy = [
            p for d in vault.glob("#Archived-*") if d.is_dir()
            for p in d.rglob(f"*_{src_file.name}")
        ]
        assert len(vault_copy) == 1
        assert _hash(vault_copy[0]) == pre_hash


def test_partial_files_cleaned_after_copy_fault(
    vault: Path, src_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fault after copy should not leave any .partial files in the vault."""
    monkeypatch.setenv("DOCVAULT_FAULT_INJECT", "copy")
    with pytest.raises(ingest.IngestFault):
        ingest.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    leftover = [
        p for d in (
            *vault.glob("#Archived-*"),
            vault / "files",
        ) if d.is_dir()
        for p in d.rglob("*.partial")
    ]
    assert leftover == []


def test_prefix_collision_never_overwrites_existing_vault_file(
    vault: Path, src_file: Path
) -> None:
    """Two different documents whose sha256 shares the first 6 chars and whose
    filenames match must not clobber each other — and the ingest must still
    succeed (longer prefix), not fail."""
    import hashlib as H
    from datetime import datetime

    from docvault import paths as P

    sha = H.sha256(src_file.read_bytes()).hexdigest()
    dt = datetime.now()
    # Pre-occupy the 6-char-prefix target with *different* content
    occupied = P.vault_path_for(vault, sha, src_file.name, dt)
    occupied.parent.mkdir(parents=True, exist_ok=True)
    occupied.write_bytes(b"a different document that happens to collide")
    pre = occupied.read_bytes()

    res = ingest.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    assert res.target_path != occupied
    assert occupied.read_bytes() == pre, "existing vault file must be untouched"
    assert res.target_path.is_file()
    assert _hash(res.target_path) == sha


def test_undo_ingest_retires_vault_record(vault: Path, src_file: Path) -> None:
    """Undo restores the source AND removes the vault record (to trash)."""
    res = ingest.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    vault_file = res.target_path
    meta_file = res.meta_path
    assert vault_file.is_file() and meta_file.is_file()

    restored = ingest.undo_ingest(res.pending_cleanup_id, vault_root=vault)
    assert restored.is_file()
    # Vault copy + metadata retired to trash (recoverable), not deleted
    assert not vault_file.exists()
    assert not meta_file.exists()
    trash_files = [p for p in (vault / "trash").rglob("*") if p.is_file()]
    assert any(p.name.endswith(src_file.name) for p in trash_files)


def test_undo_ingest_restores_source(vault: Path, src_file: Path) -> None:
    pre_hash = _hash(src_file)
    res = ingest.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    assert res.pending_cleanup_id is not None
    assert not src_file.exists()

    restored = ingest.undo_ingest(res.pending_cleanup_id, vault_root=vault)
    assert restored == src_file.resolve() or restored == src_file
    assert src_file.is_file() or restored.is_file()
    target = restored if restored.is_file() else src_file
    assert _hash(target) == pre_hash


def test_undo_ingest_collision_keeps_file_in_pending(
    vault: Path, src_file: Path
) -> None:
    res = ingest.ingest_manual(src_file, {"title": "x"}, mode="move", vault_root=vault)
    # Recreate something at the original path
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_bytes(b"squatter")
    restored = ingest.undo_ingest(res.pending_cleanup_id, vault_root=vault)
    assert "pending-cleanup" in str(restored)
    assert restored.is_file()


def test_metadata_written_after_move(vault: Path, src_file: Path) -> None:
    res = ingest.ingest_manual(
        src_file, {"title": "T", "tags": ["A", "B"], "intro": "hello"},
        mode="move", vault_root=vault,
    )
    assert res.meta_path.is_file()
    loaded = M.load(res.meta_path)
    assert loaded.title == "T"
    assert loaded.tags == ["A", "B"]
    assert loaded.intro == "hello"
    assert loaded.sha256 == _hash(src_file_after := res.target_path)
    assert loaded.location.type == "vault"


def test_external_path_protected_source_detected(
    vault: Path, tmp_path: Path
) -> None:
    """When the src path matches a protected pattern, location.source is set."""
    fake_onedrive = tmp_path / "OneDrive" / "Personal Vault"
    fake_onedrive.mkdir(parents=True)
    src = fake_onedrive / "passport.pdf"
    src.write_bytes(b"id-doc")
    res = ingest.ingest_manual(src, {"title": "P"}, mode="reference", vault_root=vault)
    assert res.metadata.location.type == "external"
    assert res.metadata.location.source == "onedrive_personal_vault"
    assert src.is_file()
