from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    for sub in ("files", "meta", "drafts", "trash", ".pending-cleanup", "index", "logs"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path
