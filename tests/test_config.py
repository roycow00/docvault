"""Config resolution tests: pointer redirect, BOM tolerance."""

from __future__ import annotations

from pathlib import Path

from docvault.config import load


def test_pointer_config_redirects_to_vault_config(tmp_path: Path) -> None:
    vault = tmp_path / "vaultdata"
    vault.mkdir()
    (vault / "config.toml").write_text(
        f'vault_root = "{str(vault).replace(chr(92), chr(92) * 2)}"\nserver_port = 7999\n',
        encoding="utf-8",
    )
    pointer = tmp_path / "home" / ".config" / "docvault" / "config.toml"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(
        f'vault_root = "{str(vault).replace(chr(92), chr(92) * 2)}"\n', encoding="utf-8"
    )

    cfg = load(pointer)  # explicit path: no redirect
    assert cfg.server_port == 7777  # pointer has no port -> default

    # Simulate resolution finding the pointer non-explicitly
    import docvault.config as C

    cfg2 = C._from_file(C._pointer_target(pointer) or pointer)
    assert cfg2.server_port == 7999  # redirected to the vault's own config


def test_full_config_is_not_redirected(tmp_path: Path) -> None:
    """A config that sets anything beyond vault_root is authoritative as-is."""
    vault = tmp_path / "vaultdata"
    vault.mkdir()
    (vault / "config.toml").write_text(
        f'vault_root = "{str(vault).replace(chr(92), chr(92) * 2)}"\nserver_port = 7999\n',
        encoding="utf-8",
    )
    full = tmp_path / "config.toml"
    full.write_text(
        f'vault_root = "{str(vault).replace(chr(92), chr(92) * 2)}"\nserver_port = 8001\n',
        encoding="utf-8",
    )
    import docvault.config as C

    assert C._pointer_target(full) is None


def test_config_tolerates_utf8_bom(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    vault.mkdir()
    p = tmp_path / "config.toml"
    body = f'vault_root = "{str(vault).replace(chr(92), chr(92) * 2)}"\n'
    p.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    cfg = load(p)
    assert cfg.vault_root == vault
