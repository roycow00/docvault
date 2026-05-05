"""Streaming SHA-256."""

from __future__ import annotations

import hashlib
from pathlib import Path


class FileInaccessibleError(Exception):
    """Raised when a file cannot be opened or read (locked OneDrive Vault, missing, denied)."""


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                h.update(buf)
    except (FileNotFoundError, PermissionError, OSError) as e:
        raise FileInaccessibleError(f"cannot read {path}: {e}") from e
    return h.hexdigest()
