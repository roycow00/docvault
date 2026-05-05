"""FastAPI app factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from docvault import drafts as DRAFTS
from docvault.config import Config
from docvault.maintenance import purge_pending_cleanup, purge_trash, verify
from docvault.server.routes import build_router


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="docvault", version="0.1.0", openapi_url=None, docs_url=None, redoc_url=None)
    app.state.config = cfg

    # Opportunistic startup maintenance: sweep stale drafts, retire old
    # pending-cleanup and trash entries, and clean any *.partial debris.
    try:
        DRAFTS.sweep_expired(cfg.vault_root)
        purge_pending_cleanup(cfg)
        purge_trash(cfg)
        verify(cfg, dry_run=False)
    except Exception:
        # Maintenance failures must not block server startup.
        pass

    app.include_router(build_router(cfg))

    static_dir = Path(__file__).resolve().parent.parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static")

    @app.get("/")
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/static/index.html")

    @app.get("/health")
    def _health() -> dict:
        return {"ok": True, "vault": str(cfg.vault_root)}

    return app
