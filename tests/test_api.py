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
    return TestClient(create_app(cfg))


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
