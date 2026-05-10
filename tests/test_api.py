"""HTTP layer tests via FastAPI TestClient."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docvault.config import (
    Config,
    LLMCfg,
    IngestCfg,
    CleanupCfg,
    TrashCfg,
)
from docvault.server.app import create_app


@pytest.fixture
def cfg(vault: Path) -> Config:
    return Config(
        vault_root=vault,
        server_port=0,
        llm=LLMCfg(),
        ingest=IngestCfg(),
        cleanup=CleanupCfg(),
        trash=TrashCfg(),
    )


@pytest.fixture
def client(cfg: Config) -> TestClient:
    # The CSRF middleware rejects requests whose Host header isn't loopback.
    # TestClient defaults to base_url=http://testserver — pin it to 127.0.0.1
    # so existing tests pass through untouched.
    return TestClient(create_app(cfg), base_url="http://127.0.0.1")


@pytest.fixture
def src_file(tmp_path: Path) -> Path:
    p = tmp_path / "incoming" / "report.pdf"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4\nbody\n" * 200)
    return p


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_ingest_manual_then_list(client: TestClient, src_file: Path) -> None:
    pre_hash = _hash(src_file)

    r = client.post(
        "/api/ingest/manual",
        json={
            "src_path": str(src_file),
            "metadata": {"title": "Report", "intro": "test", "tags": ["A", "B"]},
            "mode": "move",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sha256"] == pre_hash
    assert body["duplicate"] is False

    # List shows it
    r = client.get("/api/docs")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 1
    d = docs[0]
    assert d["sha256"] == pre_hash
    assert d["title"] == "Report"
    assert d["tags"] == ["A", "B"]
    assert d["location"]["type"] == "vault"
    assert d["accessible"] is True

    # Source has been moved
    assert not src_file.exists()


def test_ingest_reference_keeps_source(client: TestClient, src_file: Path) -> None:
    r = client.post(
        "/api/ingest/manual",
        json={
            "src_path": str(src_file),
            "metadata": {"title": "Ref"},
            "mode": "reference",
        },
    )
    assert r.status_code == 200, r.text
    assert src_file.is_file()

    docs = client.get("/api/docs").json()
    assert docs[0]["location"]["type"] == "external"
    assert docs[0]["location"]["path"] == str(src_file.resolve())


def test_get_404(client: TestClient) -> None:
    r = client.get("/api/docs/deadbeef")
    assert r.status_code == 404


def test_update_doc(client: TestClient, src_file: Path) -> None:
    sha = client.post(
        "/api/ingest/manual",
        json={"src_path": str(src_file), "metadata": {"title": "Old"}, "mode": "move"},
    ).json()["sha256"]

    r = client.put(
        f"/api/docs/{sha}",
        json={"title": "New", "intro": "hello", "tags": ["X"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "New"
    assert body["intro"] == "hello"
    assert body["tags"] == ["X"]


def test_delete_entry_only_keeps_file(client: TestClient, src_file: Path, vault: Path) -> None:
    sha = client.post(
        "/api/ingest/manual",
        json={"src_path": str(src_file), "metadata": {"title": "K"}, "mode": "move"},
    ).json()["sha256"]
    file_path = Path(client.get(f"/api/docs/{sha}").json()["location"]["resolved"])
    assert file_path.is_file()

    r = client.request("DELETE", f"/api/docs/{sha}", json={"action": "entry_only"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/docs/{sha}").status_code == 404
    assert file_path.is_file(), "entry_only must not touch the file"


def test_delete_entry_and_file_moves_both_to_trash(
    client: TestClient, src_file: Path, vault: Path
) -> None:
    sha = client.post(
        "/api/ingest/manual",
        json={"src_path": str(src_file), "metadata": {"title": "K"}, "mode": "move"},
    ).json()["sha256"]
    file_path = Path(client.get(f"/api/docs/{sha}").json()["location"]["resolved"])

    r = client.request("DELETE", f"/api/docs/{sha}", json={"action": "entry_and_file"})
    assert r.status_code == 200, r.text
    assert not file_path.exists()
    # File now lives in trash/
    trash_files = list((vault / "trash").rglob("*"))
    # md + file + sidecars
    assert any(p.name.endswith(src_file.name) for p in trash_files)


def test_show_endpoint_uses_shell(
    client: TestClient, src_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = client.post(
        "/api/ingest/manual",
        json={"src_path": str(src_file), "metadata": {"title": "K"}, "mode": "move"},
    ).json()["sha256"]

    calls = []

    def fake_reveal(p):
        calls.append(p)

    from docvault.server import shell as shell_mod
    monkeypatch.setattr(shell_mod, "reveal", fake_reveal)
    # The route imports shell at module load; patch it there too
    from docvault.server import routes as routes_mod
    monkeypatch.setattr(routes_mod.shell, "reveal", fake_reveal)

    r = client.post("/api/show", json={"sha256": sha})
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    assert str(calls[0]).endswith(src_file.name) or src_file.name in str(calls[0])


def test_ingest_ai_without_credentials_records_error(
    client: TestClient, src_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the LLM provider can't be configured, the AI route still creates
    a draft (with error flag set) so the user can fall back to manual entry."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/ingest/ai", json={"src_path": str(src_file)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["draft_id"]
    assert body["error"]  # LLM call failed -> error captured
    assert body["sha256"]  # but hash succeeded

    # Source untouched (AI path never touches the file)
    assert src_file.is_file()

    # Get the draft back
    r2 = client.get(f"/api/draft/{body['draft_id']}")
    assert r2.status_code == 200
    assert r2.json()["draft_id"] == body["draft_id"]


def test_finalize_completes_ingest(
    client: TestClient, src_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    draft = client.post("/api/ingest/ai", json={"src_path": str(src_file)}).json()

    r = client.post(
        "/api/ingest/finalize",
        json={
            "draft_id": draft["draft_id"],
            "metadata": {"title": "Final", "intro": "user-edited", "tags": ["X"]},
            "mode": "move",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["sha256"] == draft["sha256"]
    assert out["duplicate"] is False

    # Draft was deleted
    r2 = client.get(f"/api/draft/{draft['draft_id']}")
    assert r2.status_code == 404

    # Source moved
    assert not src_file.exists()


def test_extract_metadata_endpoint_falls_back_on_no_llm(
    client: TestClient, src_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an LLM key the endpoint should still return a usable shape:
    title=filename stem, empty intro/tags, error captured."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/api/extract/metadata", json={"src_path": str(src_file)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == src_file.stem
    assert body["intro"] == ""
    assert body["tags"] == []
    assert body["error"]  # LLM call failed -> error captured


def test_extract_metadata_endpoint_rejects_nonfile(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/api/extract/metadata", json={"src_path": str(tmp_path / "nope.txt")})
    assert r.status_code == 400


def test_llm_status_claude_no_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default LLMCfg is provider=claude; with no key, status reports disconnected."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.get("/api/llm/status")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "claude"
    assert body["connected"] is False
    assert "no API key" in body["detail"]


def test_llm_status_claude_with_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    r = client.get("/api/llm/status")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert "API key configured" in body["detail"]


def test_folder_scan_lists_files(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # Scan target lives *outside* the vault — the API refuses to scan inside
    # the vault to prevent recursive self-ingest.
    folder = tmp_path_factory.mktemp("scanme")
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("alpha")
    (folder / "sub" / "b.pdf").write_bytes(b"%PDF-1.4")
    (folder / ".hidden").write_text("skip me")

    r = client.post("/api/folder/scan", json={"root": str(folder)})
    assert r.status_code == 200, r.text
    body = r.json()
    rels = sorted(f["rel"] for f in body["files"])
    assert rels == ["a.txt", "sub/b.pdf"]
    assert body["truncated"] is False


def test_folder_scan_rejects_nondir(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory
) -> None:
    base = tmp_path_factory.mktemp("scan_nondir")
    f = base / "single.txt"
    f.write_text("x")
    r = client.post("/api/folder/scan", json={"root": str(f)})
    assert r.status_code == 400


def test_folder_scan_refuses_inside_vault(
    client: TestClient, tmp_path: Path
) -> None:
    inside = tmp_path / "would_recurse"
    inside.mkdir()
    (inside / "x.txt").write_text("y")
    r = client.post("/api/folder/scan", json={"root": str(inside)})
    assert r.status_code == 400
    assert "vault" in r.text.lower()


def test_folder_ingest_stream_no_ai(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("batch")
    (folder / "one.txt").write_text("one")
    (folder / "two.txt").write_text("two")

    with client.stream(
        "POST", "/api/folder/ingest",
        json={"root": str(folder), "rel_paths": ["one.txt", "two.txt"],
              "mode": "reference", "use_ai": False},
    ) as r:
        assert r.status_code == 200
        lines = [ln for ln in r.iter_lines() if ln.strip()]

    import json as _json
    events = [_json.loads(ln) for ln in lines]
    # last event must be the summary
    assert events[-1]["done"] is True
    assert events[-1]["ok"] == 2
    assert events[-1]["error"] == 0
    # the per-file events
    assert {e["rel"] for e in events[:-1]} == {"one.txt", "two.txt"}
    assert all(e["status"] == "ok" for e in events[:-1])


def test_suggested_tags_combines_existing_and_config(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory
) -> None:
    src = tmp_path_factory.mktemp("inbox") / "doc.pdf"
    src.write_bytes(b"%PDF-1.4\nbody\n" * 50)
    # Ingest one record carrying tags so collect_existing_tags has something to find.
    client.post(
        "/api/ingest/manual",
        json={"src_path": str(src), "metadata": {"title": "T", "tags": ["MyTag"]}, "mode": "reference"},
    ).raise_for_status()

    r = client.get("/api/suggested-tags")
    assert r.status_code == 200, r.text
    body = r.json()
    tags = body["suggested"]
    # MyTag came from existing record; "Immigration" from default config suggested_tags.
    assert "MyTag" in tags
    assert "Immigration" in tags
    # Cap at 12.
    assert len(tags) <= 12


def test_open_404_when_external_missing(
    client: TestClient, tmp_path: Path
) -> None:
    # Create + reference an external file, then delete the source
    p = tmp_path / "ext.txt"
    p.write_text("hi")
    sha = client.post(
        "/api/ingest/manual",
        json={"src_path": str(p), "metadata": {"title": "Ext"}, "mode": "reference"},
    ).json()["sha256"]
    p.unlink()

    r = client.post("/api/open", json={"sha256": sha})
    assert r.status_code == 404


# ---------- CSRF / Host middleware ---------------------------------------

def test_csrf_blocks_cross_origin_post(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory
) -> None:
    src = tmp_path_factory.mktemp("ext") / "x.txt"
    src.write_text("hi")
    r = client.post(
        "/api/ingest/manual",
        json={"src_path": str(src), "metadata": {"title": "X"}, "mode": "reference"},
        headers={"Origin": "http://evil.example.com"},
    )
    assert r.status_code == 403


def test_csrf_blocks_cross_site_sec_fetch(client: TestClient) -> None:
    r = client.get("/api/docs", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_csrf_allows_same_origin_with_explicit_headers(
    client: TestClient,
) -> None:
    r = client.get(
        "/api/docs",
        headers={
            "Origin": "http://127.0.0.1:0",  # cfg.server_port=0 in fixture
            "Sec-Fetch-Site": "same-origin",
        },
    )
    assert r.status_code == 200


def test_csrf_allows_curl_like_no_origin(client: TestClient) -> None:
    # Headless tools (curl, scripts) send neither Origin nor Sec-Fetch-Site.
    # The middleware must let them through.
    r = client.get("/api/docs")
    assert r.status_code == 200


def test_csrf_blocks_non_loopback_host(cfg: Config) -> None:
    # DNS-rebinding defense: if Host header isn't loopback, refuse.
    bad = TestClient(create_app(cfg), base_url="http://docvault.evil.example.com")
    r = bad.get("/health")
    assert r.status_code == 403


def test_csrf_allows_static(client: TestClient) -> None:
    # /static/ is fetched cross-origin by no one in practice (the UI is
    # always same-origin), but a cross-origin GET to /static/index.html
    # doesn't read user data — it's just the bundled UI assets. The
    # middleware only protects /api/ + non-GET methods.
    r = client.get(
        "/static/index.html", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert r.status_code == 200


# ---------- Important flag -----------------------------------------------

def test_ingest_important_lands_in_important_folder(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory, vault: Path
) -> None:
    src = tmp_path_factory.mktemp("inbox") / "tax_return.pdf"
    src.write_bytes(b"%PDF-1.4\nimportant body\n" * 50)

    r = client.post(
        "/api/ingest/manual",
        json={
            "src_path": str(src),
            "metadata": {"title": "Tax Return", "important": True},
            "mode": "move",
        },
    )
    assert r.status_code == 200, r.text
    sha = r.json()["sha256"]

    # File lives under <vault>/Important/
    important_dir = vault / "Important"
    assert important_dir.is_dir()
    files = list(important_dir.iterdir())
    assert len(files) == 1
    assert sha[:6] in files[0].name

    # No #Archived-* folder was created
    assert not list(vault.glob("#Archived-*"))

    # DocOut surfaces important=true
    doc = client.get(f"/api/docs/{sha}").json()
    assert doc["important"] is True
    assert "Important/" in doc["location"]["path"]


def test_update_important_flag_relocates_managed_file(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory, vault: Path
) -> None:
    src = tmp_path_factory.mktemp("inbox") / "boring.pdf"
    src.write_bytes(b"%PDF-1.4\nplain body\n" * 50)

    sha = client.post(
        "/api/ingest/manual",
        json={"src_path": str(src), "metadata": {"title": "Plain"}, "mode": "move"},
    ).json()["sha256"]

    # File starts in #Archived-*
    archived = list(vault.glob("#Archived-*/*"))
    assert len(archived) == 1

    # PUT important=true relocates the file into Important/
    r = client.put(
        f"/api/docs/{sha}",
        json={"title": "Plain", "intro": "", "tags": [], "important": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["important"] is True
    assert body["location"]["path"].startswith("Important/")
    assert (vault / "Important").is_dir()
    assert len(list((vault / "Important").iterdir())) == 1
    # Original archived path is gone
    assert not archived[0].exists()

    # PUT important=false relocates it back into #Archived-{today}
    r = client.put(
        f"/api/docs/{sha}",
        json={"title": "Plain", "intro": "", "tags": [], "important": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["important"] is False
    assert not list((vault / "Important").iterdir())
    assert len(list(vault.glob("#Archived-*/*"))) == 1


def test_update_important_on_external_only_records_flag(
    client: TestClient, tmp_path_factory: pytest.TempPathFactory, vault: Path
) -> None:
    src = tmp_path_factory.mktemp("ext") / "elsewhere.pdf"
    src.write_bytes(b"%PDF-1.4\nstays put\n" * 50)

    sha = client.post(
        "/api/ingest/manual",
        json={"src_path": str(src), "metadata": {"title": "Ext"}, "mode": "reference"},
    ).json()["sha256"]

    # Toggle important; file must NOT move (external/reference)
    r = client.put(
        f"/api/docs/{sha}",
        json={"title": "Ext", "intro": "", "tags": [], "important": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["important"] is True
    assert body["location"]["type"] == "external"
    assert src.is_file()
    assert not (vault / "Important").exists() or not list((vault / "Important").iterdir())
