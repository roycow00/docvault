"""FastAPI app factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from docvault import drafts as DRAFTS
from docvault.config import Config
from docvault.maintenance import clean_stale_partials, purge_pending_cleanup, purge_trash
from docvault.server.routes import build_router

# 127.0.0.1 is not a security boundary against malicious websites — the
# browser will happily POST to localhost from any origin (CORS only hides
# the response, side effects already happened). The middleware below
# rejects requests whose Host header isn't loopback (DNS-rebinding defense)
# and, for state-changing methods or anything under /api/, requires either
# Sec-Fetch-Site: same-origin|none or a matching Origin. Headless tools
# (curl, Python clients, the test client without explicit headers) send
# neither header and fall through, so they're unaffected.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class NoCacheStatic(StaticFiles):
    """Serve static assets with `Cache-Control: no-cache` so the browser always
    revalidates against ETag/Last-Modified. Without this, edits to the bundled
    JS/CSS may not show up until a hard-refresh."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="docvault", version="0.1.0", openapi_url=None, docs_url=None, redoc_url=None)
    app.state.config = cfg

    allowed_origins = frozenset({
        f"http://127.0.0.1:{cfg.server_port}",
        f"http://localhost:{cfg.server_port}",
    })

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):
        host_only = request.headers.get("host", "").split(":")[0]
        if host_only not in _LOOPBACK_HOSTS:
            return PlainTextResponse("forbidden host", status_code=403)

        # Protect anything that mutates state OR reads filesystem paths the
        # client controls (everything under /api/ falls in one of those two
        # buckets). /static/, /, and /health are safe to fetch cross-origin
        # — they don't take client input.
        is_protected = request.method != "GET" or request.url.path.startswith("/api/")
        if is_protected:
            site = request.headers.get("sec-fetch-site")
            if site is not None and site not in ("same-origin", "none"):
                return PlainTextResponse("cross-origin blocked", status_code=403)
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                return PlainTextResponse("bad origin", status_code=403)
        return await call_next(request)

    # Opportunistic startup maintenance: sweep stale drafts, retire old
    # pending-cleanup and trash entries, and clean stale *.partial debris.
    # (A full hash `verify` is intentionally NOT run here — it re-reads every
    # byte in the vault and would stall startup; run `docvault verify` instead.)
    try:
        DRAFTS.sweep_expired(cfg.vault_root)
        purge_pending_cleanup(cfg)
        purge_trash(cfg)
        clean_stale_partials(cfg)
    except Exception:
        # Maintenance failures must not block server startup.
        pass

    app.include_router(build_router(cfg))

    static_dir = Path(__file__).resolve().parent.parent / "static"
    app.mount("/static", NoCacheStatic(directory=str(static_dir), html=False), name="static")

    @app.get("/")
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/static/index.html")

    @app.get("/health")
    def _health() -> dict:
        return {"ok": True, "vault": str(cfg.vault_root)}

    return app
