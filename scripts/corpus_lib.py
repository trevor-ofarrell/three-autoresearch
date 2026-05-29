"""Shared helpers for the Three/WebGPU autoresearch corpus pipeline."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
SHARDS_DIR = DATA_DIR / "shards"


@dataclass(frozen=True)
class Source:
    id: str
    kind: str
    url: str
    revision_or_date: str
    license_note: str
    allowed_use: str
    topics: list[str]
    include_globs: list[str]
    exclude_globs: list[str]
    parser: str

    @property
    def raw_dir(self) -> Path:
        return RAW_DIR / self.id


def load_sources(path: Path) -> list[Source]:
    """Load the source registry.

    The file is named .yaml for future compatibility, but is intentionally
    authored as JSON, which is valid YAML and requires no extra dependency.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    sources = [Source(**item) for item in raw]
    ids = [source.id for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("source ids must be unique")
    for source in sources:
        if source.kind not in {"git", "http"}:
            raise ValueError(f"{source.id}: unsupported kind {source.kind!r}")
        if source.parser not in {"code_or_text", "markdown", "html"}:
            raise ValueError(f"{source.id}: unsupported parser {source.parser!r}")
    return sources


def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def sync_git_source(source: Source) -> None:
    source.raw_dir.parent.mkdir(parents=True, exist_ok=True)
    if (source.raw_dir / ".git").exists():
        run(["git", "fetch", "--depth", "1", "origin", source.revision_or_date], cwd=source.raw_dir)
        run(["git", "checkout", "FETCH_HEAD"], cwd=source.raw_dir)
    else:
        run([
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            source.revision_or_date,
            source.url,
            str(source.raw_dir),
        ])


def sync_http_source(source: Source) -> None:
    import requests

    source.raw_dir.mkdir(parents=True, exist_ok=True)
    response = requests.get(source.url, timeout=30)
    response.raise_for_status()
    parsed = urlparse(source.url)
    suffix = ".html" if source.parser == "html" else ".txt"
    filename = (parsed.netloc + parsed.path).strip("/").replace("/", "__") or source.id
    (source.raw_dir / f"{filename}{suffix}").write_text(response.text, encoding="utf-8")


def iter_source_files(source: Source) -> Iterable[Path]:
    if source.kind == "http":
        yield from sorted(p for p in source.raw_dir.rglob("*") if p.is_file())
        return

    include_globs = source.include_globs or ["**/*"]
    exclude_globs = source.exclude_globs or []
    for path in sorted(p for p in source.raw_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(source.raw_dir).as_posix()
        if any(fnmatch.fnmatch(rel, pat) for pat in exclude_globs):
            continue
        if not any(fnmatch.fnmatch(rel, pat) for pat in include_globs):
            continue
        if path.stat().st_size > 2_000_000:
            continue
        yield path


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return normalize_whitespace(text)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    compact: list[str] = []
    blank = False
    for line in lines:
        if line.strip():
            compact.append(line)
            blank = False
        elif not blank:
            compact.append("")
            blank = True
    return "\n".join(compact).strip()


def read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1")
        except UnicodeDecodeError:
            return None


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def language_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".html": "html",
        ".htm": "html",
        ".md": "markdown",
        ".mdx": "mdx",
        ".js": "javascript",
        ".jsx": "jsx",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".glsl": "glsl",
        ".wgsl": "wgsl",
        ".json": "json",
        ".css": "css",
    }.get(ext, ext.removeprefix(".") or "text")


def canonical_url(source: Source, path: Path) -> str:
    if source.kind == "http":
        return source.url
    rel = path.relative_to(source.raw_dir).as_posix()
    return f"{source.url.rstrip('/')}/blob/{source.revision_or_date}/{rel}"


def repo_revision(path: Path) -> str:
    if not (path / ".git").exists():
        return ""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()
    except subprocess.CalledProcessError:
        return ""


def workspace_rel(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return os.fspath(path)
