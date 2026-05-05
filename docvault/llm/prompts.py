"""Shared prompt content for both LLM providers."""

from __future__ import annotations

SYSTEM_PROMPT = """You are a metadata-extraction assistant for a personal document vault.

Given the contents (or a truncated excerpt) of a document, propose:
  - title:  a concise, human-readable title (max ~80 chars). Prefer the document's own title or subject line over a generic one.
  - intro:  one to three sentences describing what this document is, its purpose, and any key dates or parties involved. Plain text, no markdown.
  - tags:   1-5 relevant tags chosen from the user's taxonomy when applicable, plus any natural keywords (e.g. years, jurisdictions). Prefer existing taxonomy entries.

Be conservative: if you can't determine a field with reasonable confidence, leave the title as the filename and the intro empty. Don't invent facts."""


TAXONOMY_HINT = """The user's tag taxonomy includes (but is not limited to): Immigration, House, Shopping, School, Finance, Tax, Medical, Travel, Identity, Insurance, Legal, Receipt, Statement, Contract, Manual, Warranty.

Use these when they clearly apply. Add specific tags (e.g. \"2025\", \"IRS\", a vendor name) only when they appear in the document content."""


def user_message(filename: str, mime: str, body_text: str, note: str | None) -> str:
    parts = [f"Filename: {filename}", f"MIME: {mime}"]
    if note:
        parts.append(f"Note: {note}")
    parts.append("")
    if body_text.strip():
        parts.append("Document text follows (may be truncated):")
        parts.append("---")
        parts.append(body_text)
        parts.append("---")
    else:
        parts.append("(No extractable text — base your suggestion on the filename only.)")
    return "\n".join(parts)


METADATA_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Concise human-readable title."},
        "intro": {"type": "string", "description": "1-3 sentence summary of the document."},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-5 tags. Prefer the user's taxonomy.",
        },
    },
    "required": ["title", "intro", "tags"],
    "additionalProperties": False,
}
