"""OpenAI-compatible provider for LAN endpoints (Ollama, LM Studio, llama.cpp).

Tries `response_format=json_schema` first; falls back to `json_object` with a
parse-and-retry loop if the server doesn't support schema mode.
"""

from __future__ import annotations

import json

from docvault.config import Config
from docvault.llm.base import LLMError, MetadataDraft
from docvault.llm.prompts import (
    METADATA_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    TAXONOMY_HINT,
    user_message,
)


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, cfg: Config) -> None:
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError("openai SDK not installed") from e
        oc = cfg.llm.openai_compat
        self._client = OpenAI(base_url=oc.base_url, api_key=oc.api_key or "ollama")
        self._model = oc.model

    def extract_metadata(
        self,
        *,
        text: str,
        mime: str,
        filename: str,
        note: str | None = None,
    ) -> MetadataDraft:
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + TAXONOMY_HINT},
            {"role": "user", "content": user_message(filename, mime, text, note)},
        ]

        # Attempt 1: json_schema.
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=msgs,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "metadata_draft",
                        "schema": METADATA_TOOL_SCHEMA,
                        "strict": True,
                    },
                },
                temperature=0.2,
            )
            return _parse(resp.choices[0].message.content or "{}")
        except Exception:
            pass  # fall through to json_object

        # Attempt 2: json_object with up to two retries.
        last_err: Exception | None = None
        for _ in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=msgs,
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                return _parse(resp.choices[0].message.content or "{}")
            except Exception as e:
                last_err = e
        raise LLMError(f"openai_compat call failed: {last_err}")


def _parse(s: str) -> MetadataDraft:
    try:
        d = json.loads(s)
    except json.JSONDecodeError as e:
        raise LLMError(f"non-JSON response: {e}: {s[:200]}") from e
    return {
        "title": str(d.get("title", "")).strip(),
        "intro": str(d.get("intro", "")).strip(),
        "tags": [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()],
    }
