# Windows packaging

These scripts wire docvault into Windows: an interactive installer, Explorer
right-click verbs, an optional logon-time auto-start scheduled task, and a
matching uninstaller. Everything is per-user (HKCU + per-user Task Scheduler);
no admin elevation required.

## Install (recommended)

```
powershell -ExecutionPolicy Bypass -File windows\setup.ps1
```

The installer is interactive — it asks where to put the vault, what server
port to use, which LLM provider to wire up (Claude API key / local OpenAI
endpoint / skip), whether to register the right-click verbs, and whether to
auto-start the server at logon. Defaults are sensible; press Enter to accept
each one. It writes `<vault>\config.toml` from your answers, so you don't
have to hand-edit afterward.

Idempotent — safe to re-run. To accept all defaults silently (CI / repeat
runs), pass `-NonInteractive` plus whatever flags you want to pre-seed:

```
powershell -ExecutionPolicy Bypass -File windows\setup.ps1 `
    -VaultPath D:\vault -LlmProvider openai_compat `
    -OpenAIBaseUrl http://mac.local:11434/v1 -OpenAIModel qwen3:14b `
    -Autostart yes -NonInteractive
```

If the script can't find Python 3.11+ on PATH it offers a `winget install`
(user scope, no admin); add `-InstallPython` to skip the prompt.

After install, restart Explorer to refresh the context menu:

```
Stop-Process -Name explorer -Force; Start-Process explorer
```

## Auto-start

`install-autostart.ps1` registers a per-user scheduled task ("Docvault Server
(user logon)") that runs `windows\docvault-server.bat` at every interactive
logon. The bat uses `pythonw.exe` so no console window appears. The task is
hidden, runs at user privilege level, and is delayed 5 seconds after logon.

Manage manually:

```
Get-ScheduledTask -TaskName 'Docvault Server (user logon)'
Start-ScheduledTask  -TaskName 'Docvault Server (user logon)'
Unregister-ScheduledTask -TaskName 'Docvault Server (user logon)' -Confirm:$false
```

## How the ingest flow works

Right-click on a file in Explorer to get three verbs (HKCU\\Software\\Classes\\\*\\shell):

| Verb                                | Behavior                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------ |
| `Ingest into docvault`              | Manual entry form (`/static/edit.html?src=…`)                            |
| `Ingest into docvault (AI)`         | AI drafts metadata, then opens the review form                           |
| `Ingest document in-place (AI)`     | Same as above but storage mode is locked to "Reference in place"         |

Right-click on a **folder** to get one more verb (HKCU\\Software\\Classes\\Directory\\shell):

| Verb                                | Behavior                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------ |
| `Ingest folder into docvault`       | Opens a tree-view picker; uncheck files you don't want, then bulk-ingest |

The folder picker streams per-file results back as NDJSON so you see progress
live; AI extraction is on by default and storage defaults to "Reference in
place" (so a 1000-file folder doesn't get moved by accident).

Under the hood, every verb's .bat file:
1. probes `http://127.0.0.1:7777/health`
2. starts `pythonw -m docvault serve` if down (no console window)
3. opens the relevant page in the default browser

## Uninstall

```
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1
```

Stops a running server, removes the autostart scheduled task, removes the
right-click verbs, and clears the `DOCVAULT_VAULT` user env var. Prompts
before clearing `ANTHROPIC_API_KEY` (other tools may use it) or deleting
`.venv`. Vault data is preserved by default; pass `-PurgeVault` to delete it.

For non-interactive removal:

```
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1 `
    -RemoveVenv -RemoveAnthropicKey -NonInteractive
```

If you only want to remove the context-menu entries (not a full uninstall):

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
- The autostart task and `.venv` live entirely under your user account — no
  machine-wide footprint.
