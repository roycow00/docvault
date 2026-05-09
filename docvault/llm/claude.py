"""Claude provider: structured metadata via tool-use, with prompt caching."""

from __future__ import annotations

from docvault.config import Config, resolve_claude_api_key
from docvault.llm.base import LLMError, MetadataDraft
from docvault.llm.prompts import (
    METADATA_TOOL_SCHEMA,
    resolved_system_prompt,
    resolved_taxonomy_hint,
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
        self._prompt_cfg = cfg.llm.prompt

    def extract_metadata(
        self,
        *,
        text: str,
        mime: str,
        filename: str,
        note: str | None = None,
        images: list[tuple[str, bytes]] | None = None,  # ignored; Claude path is text-only for now
        existing_tags: list[str] | None = None,
    ) -> MetadataDraft:
        # System prompt is split so the taxonomy hint can be cached separately
        # (it's repeated across every ingest call). Both halves can be
        # overridden via [llm.prompt] in config.toml.
        system_text = resolved_system_prompt(self._prompt_cfg)
        taxonomy_text = resolved_taxonomy_hint(self._prompt_cfg)
        system_blocks = [{"type": "text", "text": system_text}]
        if taxonomy_text:
            system_blocks.append({
                "type": "text",
                "text": taxonomy_text,
                **({"cache_control": {"type": "ephemeral"}} if self._cache else {}),
            })
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
                        "content": user_message(
                            filename, mime, text, note,
                            existing_tags=existing_tags,
                            user_prefix=self._prompt_cfg.user_prefix if self._prompt_cfg else None,
                        ),
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
