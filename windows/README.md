# Windows packaging

These scripts wire docvault into the Windows Explorer context menu (HKCU; no
admin required) and provide background launchers for the local server.

## One-shot install (recommended)

```
powershell -ExecutionPolicy Bypass -File windows\setup.ps1
```

This finds Python 3.11+ (or installs it via winget with `-InstallPython`),
creates `.venv`, installs docvault, runs `init-vault` (default vault path
`C:\docvault-data`), and registers the Explorer right-click verbs. Idempotent
— safe to re-run.

Useful flags:

- `-VaultPath D:\my-vault` — pick a different vault location.
- `-SkipContextMenu` — install without touching the registry.
- `-InstallPython` — auto-install Python 3.12 via winget if none is found.

After the script finishes, restart Explorer to refresh the context menu:

```
Stop-Process -Name explorer -Force; Start-Process explorer
```

## Manual install (if you want full control)

1. Install Python 3.11+ (e.g. from python.org) and add it to PATH.
2. From a Windows shell:
   ```
   cd C:\path\to\docvault
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   python -m docvault init-vault C:\docvault-data
   ```
3. Edit `C:\docvault-data\config.toml` if you want a different vault path or LLM provider.
4. Register the context menu (per-user, no admin):
   ```
   powershell -ExecutionPolicy Bypass -File windows\install-context-menu.ps1
   Stop-Process -Name explorer -Force
   ```

You should now see "Ingest into docvault" and "Ingest into docvault (AI)" when
right-clicking any file in Explorer.

## How the ingest flow works

`docvault-ingest.bat "%1"`:
1. probes `http://127.0.0.1:7777/health`
2. starts `pythonw -m docvault serve` if down (no console window)
3. URL-encodes the file path and opens the default browser to
   `http://127.0.0.1:7777/static/edit.html?src=<encoded>`

`docvault-ingest-ai.bat "%1"` does the same but POSTs to `/api/ingest/ai` first
and opens `?draft=<id>` instead.

## Uninstall

```
powershell -ExecutionPolicy Bypass -File windows\uninstall-context-menu.ps1
Stop-Process -Name explorer -Force
```

## Notes

- The launchers `chcp 65001` to handle Unicode filenames.
- The verbs target `HKCU\Software\Classes\*\shell\` — no admin needed.
- Multiple files selected: Windows invokes the verb once per file, opening one
  browser tab per file. For batch ingest, prefer `docvault ingest <path>` from
  PowerShell in a loop.
- The OneDrive Personal Vault path is auto-detected at ingest time and the
  edit form defaults to "Reference in place" so the file isn't moved out.
