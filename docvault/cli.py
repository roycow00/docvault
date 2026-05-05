"""docvault CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command("init-vault")
def init_vault(
    path: Path = typer.Argument(..., help="Where the vault data dir should live."),
    force: bool = typer.Option(False, "--force", help="Allow non-empty target."),
) -> None:
    """Create a fresh vault directory tree + a starter config.toml."""
    target = path.expanduser().resolve()
    if target.exists() and any(target.iterdir()) and not force:
        typer.echo(f"refusing to init non-empty {target} (use --force)", err=True)
        raise typer.Exit(code=2)

    for sub in ("files", "meta", "drafts", "trash", ".pending-cleanup", "index", "logs"):
        (target / sub).mkdir(parents=True, exist_ok=True)

    cfg_path = target / "config.toml"
    if not cfg_path.exists():
        from docvault import __version__
        template = _CONFIG_TEMPLATE.format(
            vault_root=str(target).replace("\\", "\\\\"), version=__version__
        )
        cfg_path.write_text(template, encoding="utf-8")

    typer.echo(f"vault initialized at {target}")
    typer.echo(f"config: {cfg_path}")


@app.command()
def serve(
    config: Path | None = typer.Option(None, "--config", help="Explicit config path."),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int | None = typer.Option(None, "--port", help="Override config server_port."),
) -> None:
    """Start the local HTTP server (loopback only)."""
    import uvicorn

    from docvault.config import load
    from docvault.server.app import create_app
    from docvault.server.lifecycle import _is_port_listening, existing_instance, lockfile

    cfg = load(config)
    bound_port = port or cfg.server_port

    existing = existing_instance(cfg.vault_root, bound_port)
    if existing is not None:
        typer.echo(f"docvault already running (pid={existing[0]}, port={existing[1]})")
        return

    # Lockfile may be missing or corrupt while another process is bound to the
    # port. Refuse to enter the lockfile context (and stomp on the running
    # owner's lock) if we can't bind anyway.
    if _is_port_listening(bound_port, host):
        typer.echo(
            f"port {bound_port} is already in use; another process is bound to it.",
            err=True,
        )
        raise typer.Exit(code=1)

    fastapi_app = create_app(cfg)
    typer.echo(f"docvault serving at http://{host}:{bound_port}/  (vault: {cfg.vault_root})")

    with lockfile(cfg.vault_root, bound_port):
        uvicorn.run(fastapi_app, host=host, port=bound_port, log_level="info")


@app.command()
def ingest(
    src: Path = typer.Argument(..., help="File to ingest."),
    title: str = typer.Option("", "--title"),
    intro: str = typer.Option("", "--intro"),
    tag: list[str] = typer.Option([], "--tag", help="Repeatable."),
    reference: bool = typer.Option(
        False, "--reference", help="Reference in place instead of moving into vault."
    ),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Ingest a single file. Runs in-process — does not require `docvault serve`."""
    from docvault import ingest as ING
    from docvault.config import load
    from docvault.hashing import FileInaccessibleError

    cfg = load(config)
    mode = "reference" if reference else "move"
    src_resolved = src.expanduser().resolve()
    if not src_resolved.is_file():
        typer.echo(f"not a file: {src_resolved}", err=True)
        raise typer.Exit(code=2)

    try:
        res = ING.ingest_manual(
            src_resolved,
            {"title": title or "", "intro": intro or "", "tags": list(tag)},
            mode=mode,
            vault_root=cfg.vault_root,
        )
    except FileInaccessibleError as e:
        typer.echo(f"cannot access source: {e}", err=True)
        raise typer.Exit(code=3)

    if res.duplicate_of is not None:
        typer.echo(f"duplicate: existing record sha256={res.metadata.sha256}")
        typer.echo(f"           title: {res.metadata.title}")
        typer.echo(f"           located at: {res.target_path}")
        return

    typer.echo(f"ingested sha256={res.metadata.sha256}")
    typer.echo(f"  meta:   {res.meta_path}")
    typer.echo(f"  file:   {res.target_path}")
    if res.pending_cleanup_id:
        typer.echo(f"  pending-cleanup id: {res.pending_cleanup_id}  (use `docvault undo {res.pending_cleanup_id}` to revert)")


@app.command()
def undo(
    cleanup_id: str = typer.Argument(..., help="UUID from `docvault ingest` output."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Restore a source file from .pending-cleanup/ back to its original path."""
    from docvault import ingest as ING
    from docvault.config import load

    cfg = load(config)
    try:
        restored = ING.undo_ingest(cleanup_id, vault_root=cfg.vault_root)
    except ING.IngestError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2)
    typer.echo(f"restored to {restored}")


@app.command()
def cleanup(
    dry_run: bool = typer.Option(False, "--dry-run"),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Purge .pending-cleanup/ entries older than cleanup.retention_days."""
    from docvault.config import load
    from docvault.maintenance import purge_pending_cleanup

    cfg = load(config)
    res = purge_pending_cleanup(cfg, dry_run=dry_run)
    typer.echo(f"{'would remove' if dry_run else 'removed'}: {len(res.removed)} entries")
    typer.echo(f"kept (within retention): {len(res.kept)} entries")
    if res.errors:
        for p, msg in res.errors:
            typer.echo(f"  error: {p}: {msg}", err=True)


@app.command("empty-trash")
def empty_trash(
    dry_run: bool = typer.Option(False, "--dry-run"),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Purge trash/ entries older than trash.retention_days."""
    from docvault.config import load
    from docvault.maintenance import purge_trash

    cfg = load(config)
    res = purge_trash(cfg, dry_run=dry_run)
    typer.echo(f"{'would remove' if dry_run else 'removed'}: {len(res.removed)} entries")
    typer.echo(f"kept (within retention): {len(res.kept)} entries")
    if res.errors:
        for p, msg in res.errors:
            typer.echo(f"  error: {p}: {msg}", err=True)


@app.command()
def verify(
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't clean .partial debris."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Walk meta/, hash managed files, report issues."""
    from docvault.config import load
    from docvault.maintenance import verify as do_verify

    cfg = load(config)
    res = do_verify(cfg, dry_run=dry_run)
    typer.echo(f"checked: {res.checked} records")
    typer.echo(f"{'would clean' if dry_run else 'cleaned'} partial files: {len(res.cleaned_partials)}")
    if not res.issues:
        typer.echo("OK — no issues")
        return
    typer.echo(f"issues: {len(res.issues)}", err=True)
    for i in res.issues:
        typer.echo(f"  [{i.kind}] {i.sha256[:8]} {i.meta_path}: {i.detail}", err=True)
    raise typer.Exit(code=1)


@app.command("ingest-ai")
def ingest_ai(
    src: Path = typer.Argument(...),
    config: Path | None = typer.Option(None, "--config"),
    print_draft: bool = typer.Option(
        True, "--print-draft/--no-print-draft", help="Print the AI-drafted metadata to stdout."
    ),
) -> None:
    """AI-assisted ingest. Calls the configured LLM, then prints the draft id.
    Use the printed draft id to finalize from the web UI, or via `docvault finalize`."""
    from docvault import drafts as DRAFTS
    from docvault import extract as EXT
    from docvault import paths as P
    from docvault.config import load
    from docvault.hashing import FileInaccessibleError, sha256_file
    from docvault.llm.base import LLMError, get_provider

    cfg = load(config)
    src_resolved = src.expanduser().resolve()
    if not src_resolved.is_file():
        typer.echo(f"not a file: {src_resolved}", err=True)
        raise typer.Exit(code=2)

    try:
        sha = sha256_file(src_resolved)
    except FileInaccessibleError as e:
        typer.echo(f"cannot read source: {e}", err=True)
        raise typer.Exit(code=3)

    ext = EXT.extract_text(src_resolved, max_chars=cfg.llm.max_input_chars)

    err: str | None = None
    title = src_resolved.stem
    intro = ""
    tags: list[str] = []
    try:
        provider = get_provider(cfg)
        out = provider.extract_metadata(
            text=ext.text, mime=ext.mime, filename=src_resolved.name, note=ext.note
        )
        title = out.get("title") or title
        intro = out.get("intro") or ""
        tags = list(out.get("tags") or [])
    except LLMError as e:
        err = str(e)

    suggested_mode = "reference" if P.is_protected_source(src_resolved) else "move"
    draft = DRAFTS.Draft(
        draft_id=DRAFTS.new_id(),
        src_path=str(src_resolved),
        sha256=sha,
        suggested_mode=suggested_mode,
        title=title,
        intro=intro,
        tags=tags,
        note=ext.note,
        error=err,
    )
    DRAFTS.save(cfg.vault_root, draft)

    typer.echo(f"draft_id: {draft.draft_id}")
    typer.echo(f"  sha256: {sha}")
    typer.echo(f"  suggested_mode: {suggested_mode}")
    if print_draft:
        typer.echo(f"  title: {draft.title}")
        typer.echo(f"  tags:  {draft.tags}")
        if draft.intro:
            typer.echo(f"  intro: {draft.intro}")
        if draft.note:
            typer.echo(f"  note:  {draft.note}")
        if draft.error:
            typer.echo(f"  error: {draft.error}", err=True)
    typer.echo(f"finalize via web UI: http://127.0.0.1:{cfg.server_port}/static/edit.html?draft={draft.draft_id}")


@app.command("install-windows")
def install_windows() -> None:
    """Print install instructions for the Windows context-menu hooks."""
    typer.echo("install-windows: see windows/install-context-menu.ps1 (Phase 4)")


_CONFIG_TEMPLATE = """\
# docvault {version} — generated by `docvault init-vault`

vault_root  = "{vault_root}"
server_port = 7777

[llm]
provider        = "claude"
max_input_chars = 120000

[llm.claude]
api_key_env      = "ANTHROPIC_API_KEY"
model            = "claude-haiku-4-5-20251001"
use_prompt_cache = true

[llm.openai_compat]
base_url         = "http://localhost:11434/v1"
model            = "qwen3:14b"
api_key          = "ollama"
local_multimodal = false

[ingest]
on_duplicate   = "open_existing"
suggested_tags = ["Immigration", "House", "Shopping", "School", "Finance", "Tax"]

[cleanup]
retention_days = 30

[trash]
retention_days = 90
"""


if __name__ == "__main__":
    app()
