from __future__ import annotations

from datetime import datetime
from pathlib import Path

from docvault import metadata as M
from docvault import paths as P


def _make_managed(vault: Path) -> M.Metadata:
    return M.Metadata(
        title="2025 Federal Tax Return",
        intro="Federal 1040 filed via TurboTax. Includes W-2s and Schedule B.",
        tags=["Tax", "Finance", "2025"],
        file_created="2025-04-12T10:30:00",
        ingested="2026-05-04T14:20:00",
        sha256="3f9ac1deadbeef",
        original_filename="tax_2025.pdf",
        location=M.Location(
            type="vault",
            path="files/2026-05/3f9ac1_tax_2025.pdf",
        ),
        mime="application/pdf",
        size=184213,
    )


def _make_external() -> M.Metadata:
    return M.Metadata(
        title="Passport scan",
        intro="Identity document.",
        tags=["Immigration", "Identity"],
        file_created="2024-09-02T14:11:00",
        ingested="2026-05-04T14:20:00",
        sha256="71bcd3cafef00d",
        original_filename="passport.pdf",
        location=M.Location(
            type="external",
            path=r"C:\Users\rcow\OneDrive\Personal Vault\passport.pdf",
            source="onedrive_personal_vault",
        ),
        mime="application/pdf",
        size=942110,
    )


def test_round_trip_managed(vault: Path) -> None:
    m = _make_managed(vault)
    dt = datetime.fromisoformat(m.ingested)
    meta_path = P.meta_path_for(vault, m.sha256, m.original_filename, dt)

    M.dump(meta_path, m)
    loaded = M.load(meta_path)

    assert loaded == m
    assert loaded.location.type == "vault"
    assert loaded.location.source is None


def test_round_trip_external(vault: Path) -> None:
    m = _make_external()
    dt = datetime.fromisoformat(m.ingested)
    meta_path = P.meta_path_for(vault, m.sha256, m.original_filename, dt)

    M.dump(meta_path, m)
    loaded = M.load(meta_path)

    assert loaded == m
    assert loaded.location.type == "external"
    assert loaded.location.source == "onedrive_personal_vault"
    assert "Personal Vault" in loaded.location.path


def test_iter_all_finds_both(vault: Path) -> None:
    managed = _make_managed(vault)
    external = _make_external()
    for m in (managed, external):
        dt = datetime.fromisoformat(m.ingested)
        M.dump(P.meta_path_for(vault, m.sha256, m.original_filename, dt), m)

    found = sorted(M.iter_all(vault), key=lambda x: x.sha256)
    assert [x.sha256 for x in found] == sorted([managed.sha256, external.sha256])


def test_yaml_is_diff_friendly(vault: Path) -> None:
    """Datetimes must be plain strings, not YAML !!timestamp tags."""
    m = _make_managed(vault)
    dt = datetime.fromisoformat(m.ingested)
    meta_path = P.meta_path_for(vault, m.sha256, m.original_filename, dt)
    M.dump(meta_path, m)

    raw = meta_path.read_text(encoding="utf-8")
    assert "!!timestamp" not in raw
    assert "!!python" not in raw
    assert m.file_created in raw
    assert m.ingested in raw


def test_safe_name_strips_windows_illegal() -> None:
    assert P.safe_name("a:b/c?d.pdf") == "a_b_c_d.pdf"
    assert P.safe_name("   spaces   ok.pdf") == "spaces ok.pdf"
    long = "x" * 200 + ".pdf"
    out = P.safe_name(long)
    assert out.endswith(".pdf")
    assert len(Path(out).stem) <= 80


def test_is_protected_source_onedrive_english() -> None:
    p = r"C:\Users\rcow\OneDrive\Personal Vault\passport.pdf"
    assert P.is_protected_source(p) == "onedrive_personal_vault"


def test_is_protected_source_onedrive_chinese() -> None:
    p = r"C:\Users\rcow\OneDrive\个人保管库\passport.pdf"
    assert P.is_protected_source(p) == "onedrive_personal_vault"


def test_is_protected_source_normal_path_returns_none() -> None:
    assert P.is_protected_source(r"C:\Users\rcow\Documents\foo.pdf") is None


def test_paths_round_trip(vault: Path) -> None:
    sha = "3f9ac1deadbeef"
    name = "tax 2025.pdf"
    dt = datetime(2026, 5, 4, 14, 20, 0)

    abs_path = P.vault_path_for(vault, sha, name, dt)
    rel = P.to_relative_posix(abs_path.parent, vault)
    assert rel == "files/2026-05"

    loc = M.Location(type="vault", path=P.to_relative_posix(abs_path, vault))
    assert P.resolve(loc, vault) == abs_path.resolve() or P.resolve(loc, vault) == abs_path


def test_resolve_external_uses_path_verbatim(vault: Path) -> None:
    # External paths are stored verbatim. We pick a path appropriate to the
    # current platform so that Path() round-trips without separator munging.
    import os
    abs_external = r"C:\some\absolute\path\foo.pdf" if os.name == "nt" else "/some/absolute/path/foo.pdf"
    loc = M.Location(type="external", path=abs_external)
    assert str(P.resolve(loc, vault)) == abs_external
