"""LLM provider abstraction."""

from __future__ import annotations

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
    ) -> MetadataDraft: ...


def get_provider(cfg: Config) -> LLMProvider:
    if cfg.llm.provider == "claude":
        from docvault.llm.claude import ClaudeProvider
        return ClaudeProvider(cfg)
    if cfg.llm.provider == "openai_compat":
        from docvault.llm.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(cfg)
    raise LLMError(f"unknown llm.provider: {cfg.llm.provider}")
