# docvault

Offline document organizer for Windows. Folder-as-database, human-readable metadata, optional AI ingest.

## Quick start (Windows)

One-shot setup (creates venv, installs deps, init-vaults, registers right-click verbs):

```powershell
cd C:\path\to\docvault
powershell -ExecutionPolicy Bypass -File .\windows\setup.ps1
.\.venv\Scripts\docvault.exe serve
```

If Python 3.11+ isn't on PATH, add `-InstallPython` to fetch it via winget. See
`windows/README.md` for flags and the manual install path.

Update in place (vault data untouched): `.\windows\update.ps1`
Uninstall (vault data untouched): `.\windows\uninstall.ps1`

## Quick start (macOS dev)

```sh
cd /path/to/docvault
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docvault init-vault ~/docvault-data
docvault serve
```

Open `http://127.0.0.1:7777/`.
