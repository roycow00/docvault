"""OpenAI-compatible provider for LAN endpoints (Ollama, LM Studio, llama.cpp).

Uses free-form text mode with an explicit JSON-shape instruction in the prompt.
We tried structured-output (response_format=json_schema strict) but found that
LM Studio's GBNF grammar adds enough invisible context-length overhead to break
on moderately-sized documents — the runtime errors with "tokens to keep is
greater than the context length" even when the prompt itself fits. Free-form
mode plus _extract_json_object() handles the parsing reliably.

When `local_multimodal=True` and the caller passes images, those images are
sent as base64 data-URL `image_url` content blocks in the user message — the
standard OpenAI vision format that LM Studio, Ollama (with vision-capable
models), and vLLM all support.
"""

from __future__ import annotations

import base64
import json

from docvault.config import Config
from docvault.llm.base import LLMError, MetadataDraft
from docvault.llm.prompts import SYSTEM_PROMPT, TAXONOMY_HINT, user_message


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
        self._multimodal = oc.local_multimodal

    def extract_metadata(
        self,
        *,
        text: str,
        mime: str,
        filename: str,
        note: str | None = None,
        images: list[tuple[str, bytes]] | None = None,
    ) -> MetadataDraft:
        has_images = bool(self._multimodal and images)
        user_text = user_message(filename, mime, text, note, images_attached=has_images)
        if has_images:
            content: list[dict] = [{"type": "text", "text": user_text}]
            for img_mime, img_bytes in images:
                b64 = base64.b64encode(img_bytes).decode("ascii")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img_mime};base64,{b64}"},
                })
            user_msg: dict = {"role": "user", "content": content}
        else:
            user_msg = {"role": "user", "content": user_text}
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + TAXONOMY_HINT},
            user_msg,
        ]

        # Always use free-form text mode + a JSON-shape nudge in the prompt.
        # We tried response_format=json_schema strict, but LM Studio's GBNF
        # grammar adds enough invisible n_keep overhead that on documents
        # ~5k tokens or larger it can push past the model's loaded context
        # window with the runtime reporting "tokens to keep > context length".
        # Free-form mode does not have this overhead, and _extract_json_object
        # below reliably pulls the JSON out of the reply (handles code fences,
        # preambles, trailing commentary). Cap output at 768 tokens — the JSON
        # we want is ≤ ~400 — to prevent runaway narration that would blow
        # context from the output side.
        max_tokens = 768
        nudge = (
            "Output ONLY a single-line JSON object — no narration, no thinking, "
            "no code fences, no leading text. Begin your reply with `{` and end "
            'with `}`. Schema: {"title": "...", "intro": "...", "tags": ["...", "..."]}.'
        )
        if isinstance(user_msg["content"], list):
            user_msg["content"].insert(0, {"type": "text", "text": nudge})
        else:
            user_msg["content"] = nudge + "\n\n" + user_msg["content"]

        last_err: Exception | None = None
        for _ in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=msgs,
                    temperature=0.2,
                    max_tokens=max_tokens,
                )
                raw = resp.choices[0].message.content or ""
                return _parse(_extract_json_object(raw))
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


def _extract_json_object(raw: str) -> str:
    """Pull the first balanced {...} out of a model reply.

    Handles the common decorations VL models emit: ```json fences, leading
    prose, trailing commentary. If no balanced object is found, returns the
    raw text and lets _parse fail with a useful error.
    """
    if not raw:
        return "{}"
    # Strip code fences if the whole reply is wrapped in one.
    s = raw.strip()
    if s.startswith("```"):
        s = s.lstrip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    # Find the first balanced object, respecting strings.
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return s[start : i + 1]
    return raw
