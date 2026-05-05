"""HTTP routes. Loopback-only — no auth, no CORS."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from docvault import drafts as DRAFTS
from docvault import extract as EXT
from docvault import ingest as ING
from docvault import metadata as M
from docvault import paths as P
from docvault.config import Config
from docvault.hashing import sha256_file
from docvault.llm.base import LLMError, get_provider
from docvault.server import shell


# ---------- Pydantic models (API surface) ----------


class LocationOut(BaseModel):
    type: Literal["vault", "external"]
    path: str
    source: str | None = None
    resolved: str  # absolute path the file would be opened from


class DocOut(BaseModel):
    sha256: str
    title: str
    intro: str
    tags: list[str]
    file_created: str
    ingested: str
    original_filename: str
    mime: str
    size: int
    location: LocationOut
    accessible: bool
    meta_path: str


class DraftIn(BaseModel):
    title: str = ""
    intro: str = ""
    tags: list[str] = Field(default_factory=list)


class IngestManualIn(BaseModel):
    src_path: str
    metadata: DraftIn
    mode: Literal["move", "reference"]


class IngestManualOut(BaseModel):
    sha256: str
    duplicate: bool = False
    duplicate_of_sha256: str | None = None
    meta_path: str
    target_path: str


class UpdateIn(BaseModel):
    title: str
    intro: str
    tags: list[str]


class DeleteIn(BaseModel):
    action: Literal["entry_only", "entry_and_file", "entry_and_reveal"]


class ShellIn(BaseModel):
    sha256: str


class IngestAIIn(BaseModel):
    src_path: str


class DraftOut(BaseModel):
    draft_id: str
    src_path: str
    sha256: str
    suggested_mode: Literal["move", "reference"]
    title: str
    intro: str
    tags: list[str]
    note: str | None = None
    error: str | None = None


class FinalizeIn(BaseModel):
    draft_id: str
    metadata: DraftIn
    mode: Literal["move", "reference"]


class OkOut(BaseModel):
    ok: bool = True
    note: str | None = None


# ---------- helpers ----------


def _to_out(m: M.Metadata, vault_root: Path, meta_path: Path) -> DocOut:
    resolved = P.resolve(m.location, vault_root)
    accessible = resolved.is_file()
    return DocOut(
        sha256=m.sha256,
        title=m.title,
        intro=m.intro,
        tags=m.tags,
        file_created=m.file_created,
        ingested=m.ingested,
        original_filename=m.original_filename,
        mime=m.mime,
        size=m.size,
        location=LocationOut(
            type=m.location.type,
            path=m.location.path,
            source=m.location.source,
            resolved=str(resolved),
        ),
        accessible=accessible,
        meta_path=str(meta_path),
    )


def _draft_to_out(d: "DRAFTS.Draft") -> "DraftOut":
    return DraftOut(
        draft_id=d.draft_id,
        src_path=d.src_path,
        sha256=d.sha256,
        suggested_mode=d.suggested_mode,  # type: ignore[arg-type]
        title=d.title,
        intro=d.intro,
        tags=list(d.tags),
        note=d.note,
        error=d.error,
    )


def _find(vault_root: Path, sha256: str) -> tuple[M.Metadata, Path]:
    for md in (vault_root / "meta").rglob("*.md"):
        try:
            m = M.load(md)
        except Exception:
            continue
        if m.sha256 == sha256:
            return m, md
    raise HTTPException(status_code=404, detail=f"no record with sha256={sha256}")


def _trash_file(vault_root: Path, file_path: Path, *, sha256: str, original_path: str | None = None) -> Path:
    """Move a file into <vault>/trash/YYYY-MM/ with a sidecar JSON. Returns the destination."""
    dt = datetime.now()
    trash_root = P.trash_dir(vault_root, dt)
    trash_root.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex
    dest = trash_root / f"{uid}_{P.safe_name(file_path.name)}"
    sidecar = trash_root / f"{uid}.deleted.json"
    shutil.move(str(file_path), str(dest))
    sidecar.write_text(
        json.dumps(
            {
                "uuid": uid,
                "sha256": sha256,
                "original_path": original_path or str(file_path),
                "deleted_at": M.iso_now(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return dest


# ---------- router ----------


def build_router(cfg: Config) -> APIRouter:
    router = APIRouter(prefix="/api")
    vault_root = cfg.vault_root

    @router.get("/docs", response_model=list[DocOut])
    def list_docs() -> list[DocOut]:
        out: list[DocOut] = []
        for md in sorted((vault_root / "meta").rglob("*.md")):
            try:
                m = M.load(md)
            except Exception:
                continue
            out.append(_to_out(m, vault_root, md))
        return out

    @router.get("/docs/{sha256}", response_model=DocOut)
    def get_doc(sha256: str) -> DocOut:
        m, md = _find(vault_root, sha256)
        return _to_out(m, vault_root, md)

    @router.put("/docs/{sha256}", response_model=DocOut)
    def update_doc(sha256: str, body: UpdateIn) -> DocOut:
        m, md = _find(vault_root, sha256)
        updated = replace(m, title=body.title, intro=body.intro, tags=list(body.tags))
        M.dump(md, updated)
        return _to_out(updated, vault_root, md)

    @router.delete("/docs/{sha256}", response_model=OkOut)
    def delete_doc(sha256: str, body: DeleteIn) -> OkOut:
        m, md = _find(vault_root, sha256)
        file_path = P.resolve(m.location, vault_root)

        # Always move the .md to trash (with a sidecar that records the original path)
        _trash_file(vault_root, md, sha256=sha256, original_path=str(md))

        if body.action == "entry_only":
            return OkOut(ok=True, note="entry deleted; file untouched")

        if body.action == "entry_and_file":
            if file_path.is_file():
                _trash_file(vault_root, file_path, sha256=sha256, original_path=str(file_path))
                return OkOut(ok=True, note="entry and file moved to trash")
            return OkOut(ok=True, note="entry deleted; file was already missing")

        if body.action == "entry_and_reveal":
            if file_path.is_file():
                shell.reveal(file_path)
                return OkOut(ok=True, note="entry deleted; file revealed in explorer")
            return OkOut(ok=True, note="entry deleted; file was missing — could not reveal")

        raise HTTPException(status_code=400, detail=f"unknown action: {body.action}")

    @router.post("/ingest/manual", response_model=IngestManualOut)
    def ingest_manual(body: IngestManualIn) -> IngestManualOut:
        src = Path(body.src_path).expanduser()
        if not src.is_file():
            raise HTTPException(status_code=400, detail=f"src_path is not a file: {src}")
        try:
            res = ING.ingest_manual(
                src,
                {"title": body.metadata.title, "intro": body.metadata.intro, "tags": body.metadata.tags},
                mode=body.mode,
                vault_root=vault_root,
            )
        except ING.FileInaccessibleError as e:
            raise HTTPException(status_code=423, detail=str(e))  # 423 Locked
        except ING.IngestVerifyError as e:
            raise HTTPException(status_code=500, detail=str(e))

        if res.duplicate_of is not None:
            return IngestManualOut(
                sha256=res.metadata.sha256,
                duplicate=True,
                duplicate_of_sha256=res.metadata.sha256,
                meta_path="",
                target_path=str(P.resolve(res.metadata.location, vault_root)),
            )
        return IngestManualOut(
            sha256=res.metadata.sha256,
            duplicate=False,
            duplicate_of_sha256=None,
            meta_path=str(res.meta_path),
            target_path=str(res.target_path),
        )

    @router.post("/ingest/ai", response_model=DraftOut)
    def ingest_ai(body: IngestAIIn) -> DraftOut:
        src = Path(body.src_path).expanduser()
        if not src.is_file():
            raise HTTPException(status_code=400, detail=f"src_path is not a file: {src}")

        # Hash source up-front so dedupe and finalize agree.
        try:
            sha = sha256_file(src)
        except ING.FileInaccessibleError as e:
            raise HTTPException(status_code=423, detail=str(e))

        # Dedupe — bail early if we already have this content.
        for md in (vault_root / "meta").rglob("*.md"):
            try:
                m = M.load(md)
            except Exception:
                continue
            if m.sha256 == sha:
                # Return a draft pre-populated from the existing record so the
                # edit page lands on a "merge" view.
                draft = DRAFTS.Draft(
                    draft_id=DRAFTS.new_id(),
                    src_path=str(src),
                    sha256=sha,
                    suggested_mode="reference",  # don't move dupes
                    title=m.title,
                    intro=m.intro,
                    tags=list(m.tags),
                    note=f"duplicate of existing record sha256={sha}",
                )
                DRAFTS.save(vault_root, draft)
                return _draft_to_out(draft)

        # Extract text for the LLM.
        ext = EXT.extract_text(src, max_chars=cfg.llm.max_input_chars)

        # Call LLM.
        ai_title = ai_intro = ""
        ai_tags: list[str] = []
        err: str | None = None
        try:
            provider = get_provider(cfg)
            draft_md = provider.extract_metadata(
                text=ext.text, mime=ext.mime, filename=src.name, note=ext.note
            )
            ai_title = draft_md.get("title", "")
            ai_intro = draft_md.get("intro", "")
            ai_tags = list(draft_md.get("tags") or [])
        except LLMError as e:
            err = str(e)

        suggested_mode: Literal["move", "reference"] = (
            "reference" if P.is_protected_source(src) else "move"
        )
        draft = DRAFTS.Draft(
            draft_id=DRAFTS.new_id(),
            src_path=str(src),
            sha256=sha,
            suggested_mode=suggested_mode,
            title=ai_title or Path(src.name).stem,
            intro=ai_intro,
            tags=ai_tags,
            note=ext.note,
            error=err,
        )
        DRAFTS.save(vault_root, draft)
        return _draft_to_out(draft)

    @router.get("/draft/{draft_id}", response_model=DraftOut)
    def get_draft(draft_id: str) -> DraftOut:
        draft = DRAFTS.load(vault_root, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"no draft: {draft_id}")
        return _draft_to_out(draft)

    @router.post("/ingest/finalize", response_model=IngestManualOut)
    def finalize(body: FinalizeIn) -> IngestManualOut:
        draft = DRAFTS.load(vault_root, body.draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail=f"no draft: {body.draft_id}")
        src = Path(draft.src_path)
        if not src.is_file():
            raise HTTPException(status_code=410, detail=f"source missing: {src}")
        try:
            res = ING.ingest_manual(
                src,
                {
                    "title": body.metadata.title,
                    "intro": body.metadata.intro,
                    "tags": body.metadata.tags,
                },
                mode=body.mode,
                vault_root=vault_root,
            )
        except ING.FileInaccessibleError as e:
            raise HTTPException(status_code=423, detail=str(e))
        DRAFTS.delete(vault_root, body.draft_id)
        if res.duplicate_of is not None:
            return IngestManualOut(
                sha256=res.metadata.sha256,
                duplicate=True,
                duplicate_of_sha256=res.metadata.sha256,
                meta_path="",
                target_path=str(P.resolve(res.metadata.location, vault_root)),
            )
        return IngestManualOut(
            sha256=res.metadata.sha256,
            duplicate=False,
            duplicate_of_sha256=None,
            meta_path=str(res.meta_path),
            target_path=str(res.target_path),
        )

    @router.post("/docs/{sha256}/move-to-vault", response_model=DocOut)
    def move_to_vault(sha256: str) -> DocOut:
        try:
            res = ING.convert_to_managed(sha256, vault_root=vault_root)
        except ING.FileInaccessibleError as e:
            raise HTTPException(status_code=423, detail=str(e))
        return _to_out(res.metadata, vault_root, res.meta_path)

    @router.post("/show", response_model=OkOut)
    def show(body: ShellIn) -> OkOut:
        m, _ = _find(vault_root, body.sha256)
        path = P.resolve(m.location, vault_root)
        try:
            shell.reveal(path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return OkOut(ok=True)

    @router.post("/open", response_model=OkOut)
    def open_(body: ShellIn) -> OkOut:
        m, _ = _find(vault_root, body.sha256)
        path = P.resolve(m.location, vault_root)
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"file not accessible: {path}")
        try:
            shell.open_default(path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return OkOut(ok=True)

    return router


