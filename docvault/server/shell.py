"""OS-level integration: reveal in file manager, open with default handler."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def reveal(path: Path) -> None:
    """Open the OS file manager with `path` selected/highlighted."""
    p = str(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", f"/select,{p}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", p])
    else:
        # Linux: best-effort open the parent directory
        subprocess.Popen(["xdg-open", str(path.parent)])


def open_default(path: Path) -> None:
    """Open `path` with the OS default handler."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
