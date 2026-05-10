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
        # subprocess.Popen(["explorer.exe", "/select,<path>"]) goes through
        # subprocess.list2cmdline, which wraps the whole `/select,<path>`
        # arg in quotes when the path contains spaces. Some explorer.exe
        # builds parse the resulting `"/select,C:\foo bar\file.pdf"` as a
        # folder path instead of a `/select,` directive and silently open
        # the wrong window. ShellExecuteW takes the parameters string
        # verbatim, so the canonical `/select,"<path>"` form is preserved.
        try:
            import ctypes
            ctypes.windll.shell32.ShellExecuteW(
                None, "open", "explorer.exe", f'/select,"{p}"', None, 1
            )
            return
        except Exception:
            # Fallback for environments without ctypes / shell32 (rare).
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
