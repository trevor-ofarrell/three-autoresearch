"""Normalize raw source files into provenance-rich JSONL documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from corpus_lib import (
    NORMALIZED_DIR,
    canonical_url,
    content_hash,
    iter_source_files,
    language_for,
    load_sources,
    normalize_whitespace,
    read_text,
    repo_revision,
    strip_html,
    workspace_rel,
)


def normalize_text(text: str, parser: str, path: Path) -> str:
    if path.suffix.lower() in {".html", ".htm"} and "/examples/" in path.as_posix():
        return normalize_whitespace(text)
    if parser == "html" or path.suffix.lower() in {".html", ".htm"}:
        return strip_html(text)
    return normalize_whitespace(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize corpus sources into JSONL")
    parser.add_argument("--registry", type=Path, default=Path("data/sources.yaml"))
    parser.add_argument("--out", type=Path, default=NORMALIZED_DIR / "docs.jsonl")
    parser.add_argument("--min-chars", type=int, default=200)
    args = parser.parse_args()

    sources = load_sources(args.registry)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    seen_hashes: set[str] = set()
    written = 0
    with args.out.open("w", encoding="utf-8") as f:
        for source in sources:
            revision = repo_revision(source.raw_dir) or source.revision_or_date
            if not source.raw_dir.exists():
                print(f"Skipping {source.id}: {workspace_rel(source.raw_dir)} does not exist")
                continue
            for path in iter_source_files(source):
                raw_text = read_text(path)
                if raw_text is None:
                    continue
                text = normalize_text(raw_text, source.parser, path)
                if len(text) < args.min_chars:
                    continue
                digest = content_hash(text)
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                rel = path.relative_to(source.raw_dir).as_posix()
                doc = {
                    "doc_id": f"{source.id}:{digest[:16]}",
                    "source_id": source.id,
                    "canonical_url": canonical_url(source, path),
                    "path": rel,
                    "language": language_for(path),
                    "package": source.id,
                    "package_version": revision,
                    "topic_tags": source.topics,
                    "license_note": source.license_note,
                    "allowed_use": source.allowed_use,
                    "content_hash": digest,
                    "text": text,
                }
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")
                written += 1
    print(f"Wrote {written} docs to {workspace_rel(args.out)}")


if __name__ == "__main__":
    main()
