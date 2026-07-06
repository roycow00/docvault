"""HTTP routes. Loopback-only — no auth, no CORS."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from docvault import drafts as DRAFTS
from docvault import extract as EXT
from docvault import fsops
from docvault import ingest as ING
from docvault import metadata as M
from docvault import paths as P
from docvault.config import Config, resolve_claude_api_key
from docvault.hashing import sha256_file
from docvault.llm.base import LLMError, collect_existing_tags, get_provider
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
    important: bool = False


class DraftIn(BaseModel):
    title: str = ""
    intro: str = ""
    tags: list[str] = Field(default_factory=list)
    important: bool = False


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
    important: bool = False


class DeleteIn(BaseModel):
    action: Literal[
        "entry_only",
        "entry_and_file",
        "entry_and_file_hard",
        "entry_and_reveal",
    ]


class ShellIn(BaseModel):
    sha256: str


class IngestAIIn(BaseModel):
    src_path: str


class SourcePathIn(BaseModel):
    # Used by the ingest progress page's "Open file" / "Delete instead"
    # actions to act on the raw source path before any vault record exists.
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
    duplicate_of_sha256: str | None = None
    important: bool = False


class FinalizeIn(BaseModel):
    draft_id: str
    metadata: DraftIn
    mode: Literal["move", "reference"]


class OkOut(BaseModel):
    ok: bool = True
    note: str | None = None


class ExtractMetadataIn(BaseModel):
    src_path: str


class ExtractMetadataOut(BaseModel):
    title: str
    intro: str
    tags: list[str]
    note: str | None = None
    error: str | None = None


class FolderScanIn(BaseModel):
    root: str


class FolderFile(BaseModel):
    rel: str        # forward-slash path relative to scan root
    abs: str        # absolute path
    size: int
    mime: str


class FolderScanOut(BaseModel):
    root: str
    files: list[FolderFile]
    skipped: list[str]          # paths skipped (e.g. inaccessible, hidden)
    truncated: bool             # true if MAX_SCAN_FILES was hit


class FolderIngestIn(BaseModel):
    root: str
    rel_paths: list[str]                # selected files, relative to root
    mode: Literal["move", "reference"] = "reference"
    use_ai: bool = True


class LLMStatusOut(BaseModel):
    provider: str               # "claude" | "openai_compat"
    model: str                  # configured model name
    base_url: str | None = None # only set for openai_compat
    connected: bool             # True if we can reach / authenticate
    detail: str                 # short human-readable status line


class SuggestedTagsOut(BaseModel):
    # Ranked list, capped. Frontend renders these as one-click chips on the
    # edit form so the user can extend their existing taxonomy without
    # retyping.
    suggested: list[str]


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
        important=m.important,
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
        duplicate_of_sha256=d.duplicate_of_sha256,
        important=d.important,
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


# ---------- router ----------


def build_router(cfg: Config) -> APIRouter:
    router = APIRouter(prefix="/api")
    vault_root = cfg.vault_root

    @router.get("/docs", response_model=list[DocOut])
    def list_docs() -> list[DocOut]:
        out: list[DocOut] = []
        for md in (vault_root / "meta").rglob("*.md"):
            try:
                m = M.load(md)
            except Exception:
                continue
            out.append(_to_out(m, vault_root, md))
        # Newest-first by ingestion timestamp. The previous default was
        # alphabetical by meta-path, which effectively grouped by YYYY-MM
        # then filename and buried recently-ingested records.
        out.sort(key=lambda d: d.ingested, reverse=True)
        return out

    @router.get("/docs/{sha256}", response_model=DocOut)
    def get_doc(sha256: str) -> DocOut:
        m, md = _find(vault_root, sha256)
        return _to_out(m, vault_root, md)

    @router.put("/docs/{sha256}", response_model=DocOut)
    def update_doc(sha256: str, body: UpdateIn) -> DocOut:
        m, md = _find(vault_root, sha256)
        updated = replace(
            m,
            title=body.title,
            intro=body.intro,
            tags=list(body.tags),
            important=bool(body.important),
        )
        # If the important flag changed on a managed (in-vault) record,
        # physically move the file between Important/ and the date-archive
        # folder. External references just record the flag; the source file
        # stays where it is.
        if updated.important != m.important and updated.location.type == "vault":
            try:
                updated = ING.relocate_for_important(updated, vault_root=vault_root)
            except ING.IngestError as e:
                raise HTTPException(status_code=500, detail=f"could not relocate: {e}")
        M.dump(md, updated)
        return _to_out(updated, vault_root, md)

    @router.delete("/docs/{sha256}", response_model=OkOut)
    def delete_doc(sha256: str, body: DeleteIn) -> OkOut:
        m, md = _find(vault_root, sha256)
        file_path = P.resolve(m.location, vault_root)

        # Handle the file first, the metadata entry last: as long as the
        # entry exists, the file is discoverable. If the file operation
        # fails, the record stays intact and the error surfaces.
        note = "entry deleted; file untouched"
        if body.action == "entry_and_file":
            if file_path.is_file():
                try:
                    fsops.trash_file(vault_root, file_path, sha256=sha256, original_path=str(file_path))
                except OSError as e:
                    raise HTTPException(status_code=423, detail=f"could not move file to trash: {e}")
                note = "entry and file moved to trash"
            else:
                note = "entry deleted; file was already missing"
        elif body.action == "entry_and_file_hard":
            # Permanent deletion — no trash buffer for the data file. The .md
            # still goes to trash below. Front-end is responsible for the
            # extra confirmation; the server just honours the request.
            if file_path.is_file():
                try:
                    file_path.unlink()
                except OSError as e:
                    raise HTTPException(status_code=500, detail=f"could not delete file: {e}")
                note = "entry trashed; file permanently deleted"
            else:
                note = "entry trashed; file was already missing"

        fsops.trash_file(vault_root, md, sha256=sha256, original_path=str(md))

        if body.action == "entry_and_reveal":
            if file_path.is_file():
                shell.reveal(file_path)
                note = "entry deleted; file revealed in explorer"
            else:
                note = "entry deleted; file was missing — could not reveal"

        return OkOut(ok=True, note=note)

    @router.post("/ingest/manual", response_model=IngestManualOut)
    def ingest_manual(body: IngestManualIn) -> IngestManualOut:
        src = Path(body.src_path).expanduser()
        if not src.is_file():
            raise HTTPException(status_code=400, detail=f"src_path is not a file: {src}")
        try:
            res = ING.ingest_manual(
                src,
                {
                    "title": body.metadata.title,
                    "intro": body.metadata.intro,
                    "tags": body.metadata.tags,
                    "important": bool(body.metadata.important),
                },
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
                # Return a draft flagged as a duplicate. The front end uses
                # `duplicate_of_sha256` to redirect straight to the existing
                # record's edit page (no AI call, no draft form).
                draft = DRAFTS.Draft(
                    draft_id=DRAFTS.new_id(),
                    src_path=str(src),
                    sha256=sha,
                    suggested_mode="reference",  # don't move dupes
                    title=m.title,
                    intro=m.intro,
                    tags=list(m.tags),
                    note=f"duplicate of existing record sha256={sha}",
                    duplicate_of_sha256=sha,
                )
                DRAFTS.save(vault_root, draft)
                return _draft_to_out(draft)

        # Extract text for the LLM.
        ext = EXT.extract_text(src, max_chars=cfg.llm.max_input_chars)

        # If vision is on and we got NO usable text from the document
        # (scanned PDF, image file, OCR-less office doc), rasterize and let
        # the model read the pixels. When text *is* available, skip vision —
        # it adds thousands of vision tokens, slows the call, and on
        # multi-page born-digital docs frequently overflows the model's
        # context window or crashes the runtime.
        images: list[tuple[str, bytes]] = []
        oc = cfg.llm.openai_compat
        if (
            cfg.llm.provider == "openai_compat"
            and oc.local_multimodal
            and len(ext.text.strip()) < oc.vision_text_threshold
        ):
            images = EXT.extract_images(
                src, max_pages=oc.max_image_pages, max_dim=oc.max_image_dim
            )

        # Call LLM.
        ai_title = ai_intro = ""
        ai_tags: list[str] = []
        err: str | None = None
        try:
            provider = get_provider(cfg)
            draft_md = provider.extract_metadata(
                text=ext.text, mime=ext.mime, filename=src.name, note=ext.note,
                images=images or None,
                existing_tags=collect_existing_tags(vault_root),
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

    @router.post("/ingest/ai/stream")
    def ingest_ai_stream(body: IngestAIIn):
        """NDJSON-streamed version of /ingest/ai.

        Emits one JSON object per phase so a progress page can show live
        status, elapsed time, the extracted-text preview, and the LLM's
        final response. Each event has at least `event` and `t` (seconds
        since the request started). Final event is `event=done` (with a
        `draft_id`) or `event=duplicate` (with the existing record's sha)
        or `event=fatal` (with a detail message).
        """
        src = Path(body.src_path).expanduser()

        def emit(start: float, event: str, **fields) -> str:
            return json.dumps({
                "event": event,
                "t": round(time.time() - start, 2),
                **fields,
            }, ensure_ascii=False) + "\n"

        def gen() -> Iterator[str]:
            t0 = time.time()
            yield emit(t0, "start", filename=src.name)

            if not src.is_file():
                yield emit(t0, "fatal", detail=f"src_path is not a file: {src}")
                return

            # Hash
            yield emit(t0, "phase", phase="hash", message=f"hashing {src.name}")
            try:
                sha = sha256_file(src)
            except ING.FileInaccessibleError as e:
                yield emit(t0, "fatal", detail=f"locked/inaccessible: {e}")
                return
            yield emit(t0, "hash_done", sha256=sha)

            # Dedupe scan
            yield emit(t0, "phase", phase="dedupe", message="checking for duplicates")
            for md in (vault_root / "meta").rglob("*.md"):
                try:
                    m = M.load(md)
                except Exception:
                    continue
                if m.sha256 == sha:
                    draft = DRAFTS.Draft(
                        draft_id=DRAFTS.new_id(),
                        src_path=str(src),
                        sha256=sha,
                        suggested_mode="reference",
                        title=m.title,
                        intro=m.intro,
                        tags=list(m.tags),
                        note=f"duplicate of existing record sha256={sha}",
                        duplicate_of_sha256=sha,
                    )
                    DRAFTS.save(vault_root, draft)
                    yield emit(t0, "duplicate",
                               existing_sha256=sha,
                               existing_title=m.title,
                               draft_id=draft.draft_id)
                    return

            # Extract text
            yield emit(t0, "phase", phase="extract_text",
                       message=f"extracting text from {src.name}")
            ext = EXT.extract_text(src, max_chars=cfg.llm.max_input_chars)
            yield emit(t0, "extract_text_done",
                       chars=len(ext.text),
                       mime=ext.mime,
                       truncated=ext.truncated,
                       note=ext.note,
                       preview=ext.text[:600])

            # Maybe rasterize for vision
            images: list[tuple[str, bytes]] = []
            oc = cfg.llm.openai_compat
            text_chars = len(ext.text.strip())
            rasterizable = ext.mime == "application/pdf" or ext.mime.startswith("image/")
            will_vision = (
                cfg.llm.provider == "openai_compat"
                and oc.local_multimodal
                and text_chars < oc.vision_text_threshold
                and rasterizable
            )
            if will_vision:
                yield emit(t0, "phase", phase="rasterize",
                           message=f"rendering up to {oc.max_image_pages} pages "
                                   f"@ longest-edge {oc.max_image_dim}px",
                           max_pages=oc.max_image_pages,
                           max_dim=oc.max_image_dim,
                           text_chars=text_chars,
                           threshold=oc.vision_text_threshold)
                # Defensive: extract_images can raise (e.g., missing Pillow,
                # corrupt PDF). Without this, the exception propagates out of
                # the generator, FastAPI terminates the stream mid-flight, and
                # the front end silently hangs on the rasterize phase forever.
                try:
                    images = EXT.extract_images(
                        src, max_pages=oc.max_image_pages, max_dim=oc.max_image_dim
                    )
                except Exception as e:
                    yield emit(t0, "fatal",
                               detail=f"rasterize failed: {type(e).__name__}: {e}")
                    return
                yield emit(t0, "rasterize_done",
                           page_count=len(images),
                           bytes_total=sum(len(b) for _, b in images))
                if not images:
                    yield emit(t0, "fatal",
                               detail="rasterize produced zero pages — "
                                      "cannot send to vision model")
                    return
            else:
                if cfg.llm.provider == "claude":
                    reason = "provider is claude (text-only)"
                elif not oc.local_multimodal:
                    reason = "vision disabled (local_multimodal=false)"
                elif (text_chars < oc.vision_text_threshold) and not rasterizable:
                    reason = (f"text is {text_chars} chars but no rasterizer for "
                              f"{ext.mime} — sending text-only")
                else:
                    reason = (f"extracted text is {text_chars} chars "
                              f"(threshold {oc.vision_text_threshold}) — text alone is enough")
                yield emit(t0, "decision", sending="text", reason=reason)

            # LLM call
            model_name = (
                cfg.llm.claude.model if cfg.llm.provider == "claude"
                else oc.model
            )
            base_url = oc.base_url if cfg.llm.provider == "openai_compat" else None
            yield emit(t0, "phase", phase="llm_call",
                       message=f"calling {cfg.llm.provider} ({model_name})"
                               + (f" with {len(images)} image(s)" if images else " with text"),
                       provider=cfg.llm.provider,
                       model=model_name,
                       base_url=base_url,
                       image_count=len(images))

            ai_title = ai_intro = ""
            ai_tags: list[str] = []
            err: str | None = None
            try:
                provider = get_provider(cfg)
                draft_md = provider.extract_metadata(
                    text=ext.text, mime=ext.mime, filename=src.name, note=ext.note,
                    images=images or None,
                    existing_tags=collect_existing_tags(vault_root),
                )
                ai_title = draft_md.get("title", "")
                ai_intro = draft_md.get("intro", "")
                ai_tags = list(draft_md.get("tags") or [])
                yield emit(t0, "llm_call_done",
                           title=ai_title, intro=ai_intro, tags=ai_tags)
            except LLMError as e:
                err = str(e)
                yield emit(t0, "llm_error", error=err)

            # Persist draft
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
            yield emit(t0, "done",
                       draft_id=draft.draft_id,
                       suggested_mode=suggested_mode,
                       title=draft.title,
                       intro=draft.intro,
                       tags=draft.tags)

        return StreamingResponse(gen(), media_type="application/x-ndjson")

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
                    "important": bool(body.metadata.important),
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

    @router.post("/folder/scan", response_model=FolderScanOut)
    def folder_scan(body: FolderScanIn) -> FolderScanOut:
        """Walk a folder and return a flat list of files for the picker UI.

        We return a flat list rather than a nested tree — the front end builds
        the tree for display but submitting back is just a list of rel paths.
        """
        import mimetypes

        MAX_SCAN_FILES = 5000

        root = Path(body.root).expanduser().resolve()
        if not root.is_dir():
            raise HTTPException(status_code=400, detail=f"not a directory: {root}")
        # Refuse to scan the vault itself or anything beneath it: a recursive
        # rglob would surface every meta/, trash/, and #Archived-* file and
        # tempt the user into ingesting the vault back into itself.
        try:
            root.relative_to(vault_root.resolve())
            raise HTTPException(
                status_code=400,
                detail=f"refusing to scan inside the vault: {root}",
            )
        except ValueError:
            pass  # not under vault_root — fine

        files: list[FolderFile] = []
        skipped: list[str] = []
        truncated = False
        for p in root.rglob("*"):
            if len(files) >= MAX_SCAN_FILES:
                truncated = True
                break
            try:
                if p.is_dir():
                    continue
                # Skip hidden files (Unix convention) and Windows system markers.
                if any(part.startswith(".") for part in p.relative_to(root).parts):
                    continue
                if p.name.lower() in ("desktop.ini", "thumbs.db"):
                    continue
                stat = p.stat()
            except OSError as e:
                skipped.append(f"{p}: {e}")
                continue
            mime, _ = mimetypes.guess_type(p.name)
            files.append(FolderFile(
                rel=str(p.relative_to(root)).replace("\\", "/"),
                abs=str(p),
                size=stat.st_size,
                mime=mime or "application/octet-stream",
            ))
        files.sort(key=lambda f: f.rel.lower())
        return FolderScanOut(root=str(root), files=files, skipped=skipped, truncated=truncated)

    @router.post("/folder/ingest")
    def folder_ingest(body: FolderIngestIn):
        """Stream NDJSON results, one line per file.

        Each line is a JSON object: {"rel": ..., "status": "ok"|"duplicate"|"error",
        "sha256": ..., "title": ..., "error": ..., "done": false}. The final
        line carries done=true and a summary count.
        """
        root = Path(body.root).expanduser().resolve()
        if not root.is_dir():
            raise HTTPException(status_code=400, detail=f"not a directory: {root}")

        # Snapshot existing-tag vocabulary once for the whole batch — pulling
        # it per-file would be O(n²) on the meta tree and the vocabulary won't
        # change meaningfully over a single batch.
        existing_tags = collect_existing_tags(vault_root) if body.use_ai else None

        def gen():
            ok = 0
            dup = 0
            err = 0
            for rel in body.rel_paths:
                src = (root / rel).resolve()
                # Path traversal guard: enforce that src lives under the root.
                try:
                    src.relative_to(root)
                except ValueError:
                    err += 1
                    yield json.dumps({"rel": rel, "status": "error",
                                      "error": "path escapes scan root"}) + "\n"
                    continue
                if not src.is_file():
                    err += 1
                    yield json.dumps({"rel": rel, "status": "error",
                                      "error": "not a file"}) + "\n"
                    continue

                draft: dict = {"title": "", "intro": "", "tags": []}
                draft_err: str | None = None

                if body.use_ai:
                    try:
                        ext = EXT.extract_text(src, max_chars=cfg.llm.max_input_chars)
                        images: list[tuple[str, bytes]] = []
                        oc = cfg.llm.openai_compat
                        if (
                            cfg.llm.provider == "openai_compat"
                            and oc.local_multimodal
                            and len(ext.text.strip()) < oc.vision_text_threshold
                        ):
                            images = EXT.extract_images(
                                src, max_pages=oc.max_image_pages, max_dim=oc.max_image_dim
                            )
                        provider = get_provider(cfg)
                        out = provider.extract_metadata(
                            text=ext.text, mime=ext.mime, filename=src.name, note=ext.note,
                            images=images or None,
                            existing_tags=existing_tags,
                        )
                        draft = {
                            "title": out.get("title") or src.stem,
                            "intro": out.get("intro") or "",
                            "tags": list(out.get("tags") or []),
                        }
                    except LLMError as e:
                        draft_err = str(e)
                        draft = {"title": src.stem, "intro": "", "tags": []}

                try:
                    res = ING.ingest_manual(src, draft, mode=body.mode, vault_root=vault_root)
                except ING.FileInaccessibleError as e:
                    err += 1
                    yield json.dumps({"rel": rel, "status": "error",
                                      "error": f"locked/inaccessible: {e}"}) + "\n"
                    continue
                except ING.IngestVerifyError as e:
                    err += 1
                    yield json.dumps({"rel": rel, "status": "error",
                                      "error": f"verify failed: {e}"}) + "\n"
                    continue
                except Exception as e:
                    err += 1
                    yield json.dumps({"rel": rel, "status": "error",
                                      "error": f"{type(e).__name__}: {e}"}) + "\n"
                    continue

                if res.duplicate_of is not None:
                    dup += 1
                    yield json.dumps({
                        "rel": rel, "status": "duplicate",
                        "sha256": res.metadata.sha256,
                        "title": res.metadata.title,
                    }) + "\n"
                else:
                    ok += 1
                    payload = {
                        "rel": rel, "status": "ok",
                        "sha256": res.metadata.sha256,
                        "title": res.metadata.title,
                    }
                    if draft_err:
                        payload["ai_error"] = draft_err
                    yield json.dumps(payload) + "\n"

            yield json.dumps({
                "done": True, "ok": ok, "duplicate": dup, "error": err,
                "total": ok + dup + err,
            }) + "\n"

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @router.post("/extract/metadata", response_model=ExtractMetadataOut)
    def extract_metadata(body: ExtractMetadataIn) -> ExtractMetadataOut:
        """Stateless LLM metadata extract for an existing file path.

        Used by the edit form's "Suggest with AI" button. Unlike
        /api/ingest/ai this does NOT create a draft, hash the file, or
        check for duplicates -- it's a pure suggest helper that the user
        can invoke from any edit context (manual ingest, draft review, or
        editing an existing record).
        """
        src = Path(body.src_path).expanduser()
        if not src.is_file():
            raise HTTPException(status_code=400, detail=f"src_path is not a file: {src}")

        ext = EXT.extract_text(src, max_chars=cfg.llm.max_input_chars)
        images: list[tuple[str, bytes]] = []
        oc = cfg.llm.openai_compat
        if (
            cfg.llm.provider == "openai_compat"
            and oc.local_multimodal
            and len(ext.text.strip()) < oc.vision_text_threshold
        ):
            images = EXT.extract_images(
                src, max_pages=oc.max_image_pages, max_dim=oc.max_image_dim
            )

        try:
            provider = get_provider(cfg)
            out = provider.extract_metadata(
                text=ext.text, mime=ext.mime, filename=src.name, note=ext.note,
                images=images or None,
                existing_tags=collect_existing_tags(vault_root),
            )
            return ExtractMetadataOut(
                title=out.get("title") or src.stem,
                intro=out.get("intro") or "",
                tags=list(out.get("tags") or []),
                note=ext.note,
            )
        except LLMError as e:
            return ExtractMetadataOut(
                title=src.stem, intro="", tags=[], note=ext.note, error=str(e),
            )

    @router.get("/llm/status", response_model=LLMStatusOut)
    def llm_status() -> LLMStatusOut:
        """Quick reachability check for the configured LLM provider.

        - Claude: confirms an API key is resolvable (no network call — that
          would charge per check). The web UI calls this on every page load.
        - openai_compat: GET <base_url>/models with a short timeout. If the
          local server (Ollama / LM Studio) is up, this returns 200 in <50ms.
        """
        prov = cfg.llm.provider
        if prov == "claude":
            key = resolve_claude_api_key(cfg.llm.claude)
            if key:
                return LLMStatusOut(
                    provider="claude",
                    model=cfg.llm.claude.model,
                    connected=True,
                    detail=f"API key configured (env {cfg.llm.claude.api_key_env})",
                )
            return LLMStatusOut(
                provider="claude",
                model=cfg.llm.claude.model,
                connected=False,
                detail=f"no API key (set ${cfg.llm.claude.api_key_env})",
            )

        if prov == "openai_compat":
            import httpx

            oc = cfg.llm.openai_compat
            url = oc.base_url.rstrip("/") + "/models"
            try:
                # Short timeout — this runs on every page load. We just want
                # to know the LAN endpoint is breathing, not block the UI.
                r = httpx.get(url, timeout=2.0, headers={"Authorization": f"Bearer {oc.api_key or 'ollama'}"})
                if r.status_code < 400:
                    return LLMStatusOut(
                        provider="openai_compat",
                        model=oc.model,
                        base_url=oc.base_url,
                        connected=True,
                        detail=f"reachable ({r.status_code})",
                    )
                return LLMStatusOut(
                    provider="openai_compat",
                    model=oc.model,
                    base_url=oc.base_url,
                    connected=False,
                    detail=f"endpoint returned HTTP {r.status_code}",
                )
            except Exception as e:
                return LLMStatusOut(
                    provider="openai_compat",
                    model=oc.model,
                    base_url=oc.base_url,
                    connected=False,
                    detail=f"unreachable: {type(e).__name__}",
                )

        return LLMStatusOut(
            provider=prov, model="(unknown)", connected=False,
            detail=f"unknown provider: {prov}",
        )

    @router.get("/suggested-tags", response_model=SuggestedTagsOut)
    def suggested_tags() -> SuggestedTagsOut:
        """Tag chips for the edit form. Existing-vault tags ranked by
        frequency, padded out with config-defined `suggested_tags` that
        aren't already represented. Capped so the chip strip doesn't
        wrap into a wall of pills."""
        existing = collect_existing_tags(vault_root, max_tags=20)
        seen = {t.lower() for t in existing}
        extras = [t for t in cfg.ingest.suggested_tags if t.lower() not in seen]
        combined = (existing + extras)[:12]
        return SuggestedTagsOut(suggested=combined)

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

    @router.post("/source/open", response_model=OkOut)
    def source_open(body: SourcePathIn) -> OkOut:
        """Open a raw source path with the OS default handler.

        Used by the ingest progress page's clickable filename — at that
        point there is no vault record yet, so /open (which requires a
        sha256) doesn't apply.
        """
        src = Path(body.src_path).expanduser()
        if not src.is_file():
            raise HTTPException(status_code=404, detail=f"file not accessible: {src}")
        try:
            shell.open_default(src)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return OkOut(ok=True)

    @router.post("/source/delete", response_model=OkOut)
    def source_delete(body: SourcePathIn) -> OkOut:
        """Permanently delete a raw source file. The UI confirms with the
        user before calling this — the server just executes."""
        src = Path(body.src_path).expanduser()
        if not src.is_file():
            raise HTTPException(status_code=404, detail=f"file not accessible: {src}")
        try:
            src.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"could not delete file: {e}")
        return OkOut(ok=True, note=f"deleted {src}")

    return router


