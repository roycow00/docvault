"""Tests for text extraction and the AI-draft store."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from docvault import drafts as D
from docvault import extract as E


def test_extract_text_file(tmp_path: Path) -> None:
    p = tmp_path / "notes.txt"
    p.write_text("hello world\nthis is a tax document for 2025")
    res = E.extract_text(p)
    assert "tax document" in res.text
    assert res.mime == "text/plain"
    assert res.truncated is False
    assert res.note is None


def test_extract_truncates_large_text(tmp_path: Path) -> None:
    p = tmp_path / "big.txt"
    body = ("a" * 1000 + "\n") * 200  # ~200 KB
    p.write_text(body)
    res = E.extract_text(p, max_chars=10_000)
    assert res.truncated is True
    assert len(res.text) <= 10_000 + 30  # tolerance for truncation marker


def test_extract_unknown_mime(tmp_path: Path) -> None:
    p = tmp_path / "thing.xyz"
    p.write_bytes(b"\x00\x01\x02")
    res = E.extract_text(p)
    assert res.text == ""
    assert res.note is not None
    assert "no extractor" in res.note


def test_extract_image_returns_note(tmp_path: Path) -> None:
    p = tmp_path / "pic.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = E.extract_text(p)
    assert res.mime == "image/png"
    assert res.text == ""
    assert "vision" in (res.note or "")


def test_extract_pdf_with_no_text_flagged(tmp_path: Path) -> None:
    """Tiny PDF with no text content (just header) — should produce note."""
    pytest.importorskip("pypdf")
    # Minimal valid PDF skeleton
    p = tmp_path / "blank.pdf"
    p.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
        b"xref\n0 3\n"
        b"0000000000 65535 f\n"
        b"0000000009 00000 n\n"
        b"0000000054 00000 n\n"
        b"trailer<</Size 3/Root 1 0 R>>startxref\n98\n%%EOF\n"
    )
    res = E.extract_text(p)
    assert res.mime == "application/pdf"
    # Either no extractable text (note set) or extraction error (note set) — both acceptable.
    assert res.text == ""
    assert res.note is not None


def test_drafts_round_trip(vault: Path) -> None:
    d = D.Draft(
        draft_id=D.new_id(),
        src_path="/tmp/x.pdf",
        sha256="abc",
        suggested_mode="move",
        title="T",
        intro="I",
        tags=["A", "B"],
        note="n",
    )
    D.save(vault, d)
    loaded = D.load(vault, d.draft_id)
    assert loaded is not None
    assert loaded.draft_id == d.draft_id
    assert loaded.tags == ["A", "B"]


def test_drafts_load_missing_returns_none(vault: Path) -> None:
    assert D.load(vault, "nonexistent") is None


def test_drafts_delete(vault: Path) -> None:
    d = D.Draft(draft_id=D.new_id(), src_path="/x", sha256="a", suggested_mode="move", title="t", intro="")
    D.save(vault, d)
    assert D.load(vault, d.draft_id) is not None
    D.delete(vault, d.draft_id)
    assert D.load(vault, d.draft_id) is None


def test_drafts_sweep_expired(vault: Path) -> None:
    fresh = D.Draft(draft_id="fresh", src_path="/x", sha256="a", suggested_mode="move", title="t", intro="")
    old = D.Draft(draft_id="old", src_path="/x", sha256="a", suggested_mode="move", title="t", intro="")
    D.save(vault, fresh)
    D.save(vault, old)
    # Backdate the old one well past TTL
    import os
    p = (vault / "drafts" / "old.json")
    past = time.time() - D.DRAFT_TTL_SECONDS - 100
    os.utime(p, (past, past))

    n = D.sweep_expired(vault)
    assert n == 1
    assert D.load(vault, "fresh") is not None
    assert D.load(vault, "old") is None
