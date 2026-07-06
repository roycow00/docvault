# Windows packaging

These scripts wire docvault into the Windows Explorer context menu (HKCU; no
admin required) and provide background launchers for the local server.

## One-shot install (recommended)

```
powershell -ExecutionPolicy Bypass -File windows\setup.ps1
```

This finds Python 3.11+ (or installs it via winget with `-InstallPython`),
creates `.venv`, installs docvault, runs `init-vault` (default vault path
`C:\docvault-data`), writes a pointer config so `docvault serve` finds the
vault, and registers the Explorer right-click verbs. Idempotent — safe to
re-run.

Useful flags:

- `-VaultPath D:\my-vault` — pick a different vault location.
- `-SkipContextMenu` — install without touching the registry.
- `-InstallPython` — auto-install Python 3.12 via winget if none is found.

After the script finishes, restart Explorer to refresh the context menu:

```
Stop-Process -Name explorer -Force; Start-Process explorer
```

## Update (after pulling new code)

```
powershell -ExecutionPolicy Bypass -File windows\update.ps1
```

Reinstalls docvault into the existing `.venv` and refreshes the context-menu
verbs (useful if the checkout moved). The vault — documents, metadata,
config, trash — is never touched. If a server is running it keeps executing
the old code until you restart it; the script reminds you.

## Uninstall

```
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1
```

Removes the context-menu verbs. Optional flags:

- `-RemoveVenv` — also delete the `.venv`.
- `-RemovePointerConfig` — also delete `~\.config\docvault\config.toml`.

The vault directory is **never** deleted by any docvault script; your
documents stay where they are and remain fully usable by a future install on
this or another computer (the vault is plain files + Markdown metadata).

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
3. Point docvault at the vault, either per-shell (`set DOCVAULT_VAULT=C:\docvault-data`)
   or persistently by creating `%USERPROFILE%\.config\docvault\config.toml` with:
   ```toml
   vault_root = "C:\\docvault-data"
   ```
   (A pointer file with only `vault_root` defers to the vault's own
   `config.toml` for all other settings.)
4. Edit `C:\docvault-data\config.toml` for the vault path / LLM provider.
5. Register the context menu (per-user, no admin):
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

## Troubleshooting

- Server won't start from the context menu: check `<vault>\logs\server.log`
  (the server writes a rotating log there even when launched headless), or run
  `.venv\Scripts\docvault.exe serve` in a console to see the error directly.
- The `.bat` launchers assume port 7777; if you changed `server_port` in the
  vault config, update `PORT=` in the two `.bat` files as well.

## Notes

- The launchers `chcp 65001` to handle Unicode filenames.
- The verbs target `HKCU\Software\Classes\*\shell\` — no admin needed.
- Multiple files selected: Windows invokes the verb once per file, opening one
  browser tab per file. For batch ingest, prefer `docvault ingest <path>` from
  PowerShell in a loop.
- The OneDrive Personal Vault path is auto-detected at ingest time and the
  edit form defaults to "Reference in place" so the file isn't moved out.
