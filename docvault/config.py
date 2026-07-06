"""Configuration loader.

Resolution order:
  1. explicit path passed to load()
  2. <vault_root>/config.toml (if vault_root is set via env DOCVAULT_VAULT)
  3. ~/.config/docvault/config.toml
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class ClaudeCfg:
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_key: str | None = None
    model: str = "claude-haiku-4-5-20251001"
    use_prompt_cache: bool = True


@dataclass
class OpenAICompatCfg:
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen3:14b"
    api_key: str = "ollama"
    local_multimodal: bool = False


@dataclass
class LLMCfg:
    provider: str = "claude"
    max_input_chars: int = 120_000
    claude: ClaudeCfg = field(default_factory=ClaudeCfg)
    openai_compat: OpenAICompatCfg = field(default_factory=OpenAICompatCfg)


@dataclass
class IngestCfg:
    on_duplicate: str = "open_existing"
    suggested_tags: list[str] = field(
        default_factory=lambda: ["Immigration", "House", "Shopping", "School", "Finance", "Tax"]
    )


@dataclass
class CleanupCfg:
    retention_days: int = 30


@dataclass
class TrashCfg:
    retention_days: int = 90


@dataclass
class Config:
    vault_root: Path
    server_port: int = 7777
    llm: LLMCfg = field(default_factory=LLMCfg)
    ingest: IngestCfg = field(default_factory=IngestCfg)
    cleanup: CleanupCfg = field(default_factory=CleanupCfg)
    trash: TrashCfg = field(default_factory=TrashCfg)
    source_path: Path | None = None


def _candidate_paths(explicit: Path | None) -> list[Path]:
    paths: list[Path] = []
    if explicit:
        paths.append(explicit)
    env_vault = os.environ.get("DOCVAULT_VAULT")
    if env_vault:
        paths.append(Path(env_vault) / "config.toml")
    paths.append(Path.home() / ".config" / "docvault" / "config.toml")
    return paths


def load(explicit: Path | None = None) -> Config:
    for p in _candidate_paths(explicit):
        if p.is_file():
            # Pointer redirect: ~/.config/docvault/config.toml may be a minimal
            # file that ONLY names the vault (written by windows/setup.ps1). In
            # that case the vault's own config.toml is authoritative — it
            # travels with the data. A config with any other settings is used
            # as-is, so existing installations keep their exact behavior.
            if explicit is None:
                target = _pointer_target(p)
                if target is not None:
                    return _from_file(target)
            return _from_file(p)
    raise ConfigError(
        "no config.toml found; tried: "
        + ", ".join(str(p) for p in _candidate_paths(explicit))
    )


def _pointer_target(p: Path) -> Path | None:
    """If `p` is a pure pointer config ({vault_root} only) and the vault has
    its own config.toml elsewhere, return that path."""
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if set(raw) != {"vault_root"} or not raw["vault_root"]:
        return None
    vault_cfg = Path(str(raw["vault_root"])).expanduser() / "config.toml"
    try:
        if vault_cfg.is_file() and vault_cfg.resolve() != p.resolve():
            return vault_cfg
    except OSError:
        return None
    return None


def _from_file(path: Path) -> Config:
    # utf-8-sig: tolerate a BOM from Windows editors / PowerShell Out-File.
    raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    vault_root = raw.get("vault_root")
    if not vault_root:
        raise ConfigError(f"{path}: missing vault_root")

    llm_raw = raw.get("llm", {})
    claude_raw = llm_raw.get("claude", {})
    openai_raw = llm_raw.get("openai_compat", {})
    ingest_raw = raw.get("ingest", {})
    cleanup_raw = raw.get("cleanup", {})
    trash_raw = raw.get("trash", {})

    return Config(
        vault_root=Path(vault_root).expanduser(),
        server_port=raw.get("server_port", 7777),
        llm=LLMCfg(
            provider=llm_raw.get("provider", "claude"),
            max_input_chars=llm_raw.get("max_input_chars", 120_000),
            claude=ClaudeCfg(
                api_key_env=claude_raw.get("api_key_env", "ANTHROPIC_API_KEY"),
                api_key=claude_raw.get("api_key"),
                model=claude_raw.get("model", "claude-haiku-4-5-20251001"),
                use_prompt_cache=claude_raw.get("use_prompt_cache", True),
            ),
            openai_compat=OpenAICompatCfg(
                base_url=openai_raw.get("base_url", "http://localhost:11434/v1"),
                model=openai_raw.get("model", "qwen3:14b"),
                api_key=openai_raw.get("api_key", "ollama"),
                local_multimodal=openai_raw.get("local_multimodal", False),
            ),
        ),
        ingest=IngestCfg(
            on_duplicate=ingest_raw.get("on_duplicate", "open_existing"),
            suggested_tags=ingest_raw.get(
                "suggested_tags",
                ["Immigration", "House", "Shopping", "School", "Finance", "Tax"],
            ),
        ),
        cleanup=CleanupCfg(retention_days=cleanup_raw.get("retention_days", 30)),
        trash=TrashCfg(retention_days=trash_raw.get("retention_days", 90)),
        source_path=path,
    )


def resolve_claude_api_key(cfg: ClaudeCfg) -> str | None:
    if cfg.api_key:
        return cfg.api_key
    return os.environ.get(cfg.api_key_env)
