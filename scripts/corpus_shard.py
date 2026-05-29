"""Convert normalized JSONL corpus documents into train/val parquet shards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ModuleNotFoundError:
    pa = None
    pq = None

from corpus_lib import SHARDS_DIR, content_hash, workspace_rel


def choose_split(doc: dict, val_fraction: float) -> str:
    # Stable source/page-level split. Do not use random line-level splitting.
    key = f"{doc['source_id']}:{doc['path']}"
    bucket = int(content_hash(key)[:8], 16) / 0xFFFFFFFF
    return "val" if bucket < val_fraction else "train"


def write_shard(path: Path, rows: list[dict], output_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "jsonl":
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return
    if pa is None or pq is None:
        raise SystemExit("pyarrow is required for parquet output; rerun with --format jsonl")
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd", row_group_size=512)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create parquet/jsonl shards for prepare.py")
    parser.add_argument("--input", type=Path, default=Path("data/normalized/docs.jsonl"))
    parser.add_argument("--out", type=Path, default=SHARDS_DIR)
    parser.add_argument("--val-fraction", type=float, default=0.08)
    parser.add_argument("--max-docs-per-shard", type=int, default=2048)
    parser.add_argument("--format", choices=["parquet", "jsonl"], default="parquet")
    parser.add_argument(
        "--trainable-only",
        action="store_true",
        help="Exclude private_research_reference docs from training/eval shards",
    )
    args = parser.parse_args()

    rows_by_split: dict[str, list[dict]] = {"train": [], "val": []}
    with args.input.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            doc = json.loads(line)
            if args.trainable_only and doc.get("allowed_use") == "private_research_reference":
                continue
            split = choose_split(doc, args.val_fraction)
            rows_by_split[split].append({
                "text": doc["text"],
                "doc_id": doc["doc_id"],
                "source_id": doc["source_id"],
                "path": doc["path"],
                "canonical_url": doc["canonical_url"],
                "language": doc["language"],
                "topic_tags": ",".join(doc.get("topic_tags", [])),
                "allowed_use": doc.get("allowed_use", ""),
                "license_note": doc.get("license_note", ""),
                "content_hash": doc["content_hash"],
            })

    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for split, rows in rows_by_split.items():
        if not rows:
            raise SystemExit(f"No rows for {split} split")
        for shard_idx in range(0, len(rows), args.max_docs_per_shard):
            chunk = rows[shard_idx:shard_idx + args.max_docs_per_shard]
            suffix = "parquet" if args.format == "parquet" else "jsonl"
            out_path = args.out / f"shard_{split}_{shard_idx // args.max_docs_per_shard:05d}.{suffix}"
            write_shard(out_path, chunk, args.format)
            print(f"Wrote {len(chunk)} rows to {workspace_rel(out_path)}")
            total += len(chunk)
    print(f"Done. Wrote {total} rows.")


if __name__ == "__main__":
    main()
