"""Fetch the source registry into data/raw.

Usage:
    uv run scripts/corpus_sync.py --registry data/sources.yaml
    uv run scripts/corpus_sync.py --registry data/sources.yaml --only three,drei
"""

from __future__ import annotations

import argparse
from pathlib import Path

from corpus_lib import load_sources, sync_git_source, sync_http_source


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Three/WebGPU corpus sources")
    parser.add_argument("--registry", type=Path, default=Path("data/sources.yaml"))
    parser.add_argument("--only", default="", help="Comma-separated source ids to sync")
    args = parser.parse_args()

    selected = {item.strip() for item in args.only.split(",") if item.strip()}
    sources = load_sources(args.registry)
    if selected:
        sources = [source for source in sources if source.id in selected]

    for source in sources:
        print(f"Syncing {source.id} ({source.kind})")
        if source.kind == "git":
            sync_git_source(source)
        elif source.kind == "http":
            sync_http_source(source)
    print("Done.")


if __name__ == "__main__":
    main()
