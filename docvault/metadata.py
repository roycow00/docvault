"""Metadata schema + frontmatter I/O.

One Markdown file per document, YAML frontmatter for structured fields, body
text for the free-text intro. All datetimes are tz-naive ISO-8601 strings to
keep YAML diff-friendly (no `!!timestamp` tagging).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterator, Literal

import frontmatter
import yaml

from docvault.fsops import fsync_dir

LocationType = Literal["vault", "external"]


@dataclass
class Location:
    type: LocationType
    path: str  # vault-relative POSIX (type=vault) OR absolute (type=external)
    source: str | None = None  # e.g. "onedrive_personal_vault" hint

    def to_dict(self) -> dict:
        d = {"type": self.type, "path": self.path}
        if self.source:
            d["source"] = self.source
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Location":
        return cls(type=d["type"], path=d["path"], source=d.get("source"))


@dataclass
class Metadata:
    title: str
    intro: str
    tags: list[str]
    file_created: str  # ISO-8601 string, tz-naive
    ingested: str  # ISO-8601 string, tz-naive
    sha256: str
    original_filename: str
    location: Location
    mime: str
    size: int
    important: bool = False

    def to_frontmatter_dict(self) -> dict:
        d = {
            "title": self.title,
            "tags": list(self.tags),
            "file_created": self.file_created,
            "ingested": self.ingested,
            "sha256": self.sha256,
            "original_filename": self.original_filename,
            "location": self.location.to_dict(),
            "mime": self.mime,
            "size": self.size,
        }
        # Only emit when set, so existing records don't grow a noisy
        # `important: false` line on round-trip.
        if self.important:
            d["important"] = True
        return d

    @classmethod
    def from_frontmatter(cls, fm: frontmatter.Post) -> "Metadata":
        d = fm.metadata
        return cls(
            title=d["title"],
            intro=fm.content.strip(),
            tags=list(d.get("tags", [])),
            file_created=str(d["file_created"]),
            ingested=str(d["ingested"]),
            sha256=d["sha256"],
            original_filename=d["original_filename"],
            location=Location.from_dict(d["location"]),
            mime=d.get("mime", "application/octet-stream"),
            size=int(d.get("size", 0)),
            important=bool(d.get("important", False)),
        )


def iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def iso_from_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).replace(microsecond=0).isoformat()


def load(meta_path: Path) -> Metadata:
    with meta_path.open("r", encoding="utf-8") as f:
        post = frontmatter.load(f)
    return Metadata.from_frontmatter(post)


def dump(meta_path: Path, m: Metadata) -> None:
    """Write metadata atomically (temp + rename + fsync)."""
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(content=m.intro, **m.to_frontmatter_dict())
    serialized = frontmatter.dumps(
        post,
        handler=frontmatter.YAMLHandler(),
        Dumper=yaml.SafeDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    tmp = meta_path.with_suffix(meta_path.suffix + ".partial")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(serialized)
        if not serialized.endswith("\n"):
            f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(meta_path)
    fsync_dir(meta_path.parent)


def iter_all(vault_root: Path) -> Iterator[Metadata]:
    meta_root = vault_root / "meta"
    if not meta_root.is_dir():
        return
    for md in sorted(meta_root.rglob("*.md")):
        try:
            yield load(md)
        except Exception:
            continue


__all__ = [
    "Location",
    "Metadata",
    "iso_now",
    "iso_from_timestamp",
    "load",
    "dump",
    "iter_all",
]
