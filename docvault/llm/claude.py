"""Claude provider: structured metadata via tool-use, with prompt caching."""

from __future__ import annotations

from docvault.config import Config, resolve_claude_api_key
from docvault.llm.base import LLMError, MetadataDraft
from docvault.llm.prompts import (
    METADATA_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    TAXONOMY_HINT,
    user_message,
)


class ClaudeProvider:
    name = "claude"

    def __init__(self, cfg: Config) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMError("anthropic SDK not installed") from e
        api_key = resolve_claude_api_key(cfg.llm.claude)
        if not api_key:
            raise LLMError(
                f"missing ANTHROPIC_API_KEY (env var {cfg.llm.claude.api_key_env} not set, "
                "and no api_key in config)"
            )
        self._client = Anthropic(api_key=api_key)
        self._model = cfg.llm.claude.model
        self._cache = cfg.llm.claude.use_prompt_cache

    def extract_metadata(
        self,
        *,
        text: str,
        mime: str,
        filename: str,
        note: str | None = None,
    ) -> MetadataDraft:
        # System prompt is split so the taxonomy hint can be cached separately
        # (it's repeated across every ingest call).
        system_blocks = [
            {"type": "text", "text": SYSTEM_PROMPT},
            {
                "type": "text",
                "text": TAXONOMY_HINT,
                **({"cache_control": {"type": "ephemeral"}} if self._cache else {}),
            },
        ]
        tool = {
            "name": "emit_metadata",
            "description": "Emit the proposed metadata for the document.",
            "input_schema": METADATA_TOOL_SCHEMA,
        }
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system_blocks,
                tools=[tool],
                tool_choice={"type": "tool", "name": "emit_metadata"},
                messages=[
                    {
                        "role": "user",
                        "content": user_message(filename, mime, text, note),
                    }
                ],
            )
        except Exception as e:
            raise LLMError(f"Claude call failed: {e}") from e

        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "emit_metadata":
                payload = block.input  # type: ignore[attr-defined]
                return _normalize(payload)
        raise LLMError("Claude did not return tool_use output")


def _normalize(payload: dict) -> MetadataDraft:
    return {
        "title": str(payload.get("title", "")).strip(),
        "intro": str(payload.get("intro", "")).strip(),
        "tags": [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()],
    }
