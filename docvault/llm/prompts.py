"""Shared prompt content for both LLM providers.

The defaults below ship with docvault. Both can be overridden in config.toml
under `[llm.prompt]` (see config.py:PromptCfg) — the providers call
`resolved_system_prompt` / `resolved_taxonomy_hint` rather than the constants
directly so config overrides take effect without restarting anything new.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docvault.config import PromptCfg

SYSTEM_PROMPT = """You are a metadata-extraction assistant for a personal document vault.

Given the contents (or a truncated excerpt) of a document, propose:
  - title:  a concise, human-readable title (max ~80 chars). Prefer the document's own title or subject line over a generic one.
  - intro:  one to three sentences describing what this document is, its purpose, and any key dates or parties involved. Plain text, no markdown.
  - tags:   1-5 tags. Reuse the user's existing tags when they fit cleanly; if nothing in the existing set is a good fit, propose a new short tag (1-3 words, Title Case) that names the document's actual topic. A poorly-fitting existing tag is worse than a clean new one. Also include natural keywords like years or jurisdictions when they appear in the document.

Be conservative about title and intro: if you can't determine them with reasonable confidence, leave the title as the filename and the intro empty. Tags should still reflect the document's topic — don't return zero tags just because nothing in the existing set fits."""


TAXONOMY_HINT = """The user's tag taxonomy includes (but is not limited to): Immigration, House, Shopping, School, Finance, Tax, Medical, Travel, Identity, Insurance, Legal, Receipt, Statement, Contract, Manual, Warranty.

Use these when they clearly apply. Add specific tags (e.g. \"2025\", \"IRS\", a vendor name) only when they appear in the document content."""


def resolved_system_prompt(prompt_cfg: "PromptCfg | None") -> str:
    if prompt_cfg and prompt_cfg.system:
        return prompt_cfg.system
    return SYSTEM_PROMPT


def resolved_taxonomy_hint(prompt_cfg: "PromptCfg | None") -> str:
    if prompt_cfg and prompt_cfg.taxonomy_hint is not None:
        return prompt_cfg.taxonomy_hint
    return TAXONOMY_HINT


def user_message(
    filename: str,
    mime: str,
    body_text: str,
    note: str | None,
    *,
    images_attached: bool = False,
    existing_tags: list[str] | None = None,
    user_prefix: str | None = None,
) -> str:
    parts: list[str] = []
    if user_prefix:
        parts.append(user_prefix)
        parts.append("")
    parts.extend([f"Filename: {filename}", f"MIME: {mime}"])
    if note:
        parts.append(f"Note: {note}")
    if existing_tags:
        # Listed before the body so the model sees the vocabulary while it's
        # still attending to instructions. Ordered by user's frequency of use.
        parts.append("")
        parts.append(
            "User's existing tags (reuse these verbatim when one fits the "
            "document cleanly; if none fit well, propose a new short tag "
            "instead of forcing a poor match; ordered by frequency): "
            + ", ".join(existing_tags)
        )
    parts.append("")
    if body_text.strip():
        parts.append("Document text follows (may be truncated):")
        parts.append("---")
        parts.append(body_text)
        parts.append("---")
        if images_attached:
            parts.append("")
            parts.append("Page images are also attached — use them to confirm or fill gaps.")
    elif images_attached:
        parts.append("Page images are attached — read them to extract the title, summary, and tags. Don't fall back to the filename if the images contain readable content.")
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
            "description": "1-5 tags. Reuse the user's existing tags when one fits cleanly; otherwise propose a new short tag rather than force a poor match.",
        },
    },
    "required": ["title", "intro", "tags"],
    "additionalProperties": False,
}
