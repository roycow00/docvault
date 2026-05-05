"""Text extraction for the AI-ingest path.

We extract a *truncated* representation of the document for the LLM. The goal
is metadata drafting, not document understanding: a few thousand chars from the
start, plus a few hundred from the end (to catch signature blocks, dates), is
plenty for tag inference.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

# Lazy imports so the module loads cheaply when the AI path isn't used.


@dataclass
class ExtractResult:
    text: str
    mime: str
    truncated: bool
    note: str | None = None  # e.g. "scan, no extractable text"


_TEXT_PREFIXES = ("text/", "application/json", "application/xml")


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    head = int(max_chars * 0.8)
    tail = max_chars - head - 40
    if tail < 200:
        return text[:max_chars], True
    return text[:head] + "\n\n[…truncated…]\n\n" + text[-tail:], True


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("pypdf not installed") from e
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(p for p in parts if p.strip())


def _extract_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError as e:
        raise RuntimeError("python-docx not installed") from e
    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def extract_text(path: Path, *, max_chars: int = 120_000) -> ExtractResult:
    mime = _guess_mime(path)

    if mime.startswith(_TEXT_PREFIXES):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return ExtractResult(text="", mime=mime, truncated=False, note=f"read error: {e}")
        out, truncated = _truncate(text, max_chars)
        return ExtractResult(text=out, mime=mime, truncated=truncated)

    if mime == "application/pdf":
        try:
            text = _extract_pdf(path)
        except Exception as e:
            return ExtractResult(text="", mime=mime, truncated=False, note=f"pdf extract failed: {e}")
        if not text.strip():
            return ExtractResult(
                text="",
                mime=mime,
                truncated=False,
                note="pdf has no extractable text (likely scanned; needs OCR or a vision model)",
            )
        out, truncated = _truncate(text, max_chars)
        return ExtractResult(text=out, mime=mime, truncated=truncated)

    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    ):
        try:
            text = _extract_docx(path)
        except Exception as e:
            return ExtractResult(text="", mime=mime, truncated=False, note=f"docx extract failed: {e}")
        out, truncated = _truncate(text, max_chars)
        return ExtractResult(text=out, mime=mime, truncated=truncated)

    if mime.startswith("image/"):
        return ExtractResult(
            text="",
            mime=mime,
            truncated=False,
            note="image — needs a vision-capable model",
        )

    return ExtractResult(
        text="",
        mime=mime,
        truncated=False,
        note=f"no extractor for mime={mime}",
    )


__all__ = ["ExtractResult", "extract_text"]
