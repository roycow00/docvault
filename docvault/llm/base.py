"""LLM provider abstraction."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Protocol, TypedDict

from docvault.config import Config


class MetadataDraft(TypedDict, total=False):
    title: str
    intro: str
    tags: list[str]


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str

    def extract_metadata(
        self,
        *,
        text: str,
        mime: str,
        filename: str,
        note: str | None = None,
        images: list[tuple[str, bytes]] | None = None,
        existing_tags: list[str] | None = None,
    ) -> MetadataDraft: ...


def get_provider(cfg: Config) -> LLMProvider:
    if cfg.llm.provider == "claude":
        from docvault.llm.claude import ClaudeProvider
        return ClaudeProvider(cfg)
    if cfg.llm.provider == "openai_compat":
        from docvault.llm.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(cfg)
    raise LLMError(f"unknown llm.provider: {cfg.llm.provider}")


def collect_existing_tags(vault_root: Path, max_tags: int = 60) -> list[str]:
    """Return distinct tags from existing meta records, ranked by frequency.

    Used to bias the LLM toward reusing the user's actual vocabulary instead
    of inventing near-synonyms. Capped to keep prompt size predictable. Tag
    casing is preserved from the most common spelling — `iter_all` already
    skips unparseable records.
    """
    from docvault import metadata as M  # local import to avoid cycle

    casing: dict[str, str] = {}   # lower -> first-seen original casing
    counts: Counter[str] = Counter()
    for m in M.iter_all(vault_root):
        for t in m.tags:
            t = (t or "").strip()
            if not t:
                continue
            key = t.lower()
            counts[key] += 1
            casing.setdefault(key, t)
    return [casing[k] for k, _ in counts.most_common(max_tags)]
