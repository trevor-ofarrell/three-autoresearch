"""Verify assistant-only trainable spans for chat-template SFT records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qwen36_common import (
    DEFAULT_MODEL,
    PROJECT_ROOT,
    common_prefix_len,
    decode,
    load_processor_and_tokenizer,
    read_jsonl,
    render_chat,
    token_ids,
    write_json,
)


DEFAULT_DATASET = PROJECT_ROOT / "finetune" / "datasets-combined" / "sft" / "train.jsonl"


def inspect_record(tokenizer, row: dict, row_index: int) -> dict:
    messages = row.get("messages", [])
    if len(messages) < 2 or messages[-1].get("role") != "assistant":
        return {
            "row_index": row_index,
            "ok": False,
            "error": "record must end with an assistant message",
        }

    prompt_text = render_chat(tokenizer, messages[:-1], add_generation_prompt=True)
    full_text = render_chat(tokenizer, messages, add_generation_prompt=False)
    prompt_ids = token_ids(tokenizer, prompt_text)
    full_ids = token_ids(tokenizer, full_text)
    prefix_len = common_prefix_len(prompt_ids, full_ids)
    trainable_ids = full_ids[prefix_len:]
    trainable_text = decode(tokenizer, trainable_ids)
    assistant_content = messages[-1].get("content", "")
    user_content = "\n".join(message.get("content", "") for message in messages if message.get("role") == "user")

    failures: list[str] = []
    if not trainable_ids:
        failures.append("empty trainable span")
    if assistant_content.strip() and assistant_content.strip()[:80] not in trainable_text:
        failures.append("assistant content is not visible in trainable span preview")
    if user_content.strip() and user_content.strip()[:80] in trainable_text:
        failures.append("user content leaked into trainable span")

    return {
        "row_index": row_index,
        "task_id": row.get("metadata", {}).get("task_id", ""),
        "ok": not failures,
        "failures": failures,
        "full_tokens": len(full_ids),
        "masked_prefix_tokens": prefix_len,
        "trainable_tokens": len(trainable_ids),
        "trainable_preview": trainable_text[:1000],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify assistant-only label masking")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    _, tokenizer = load_processor_and_tokenizer(args.model)
    rows = read_jsonl(args.dataset)[: args.limit]
    records = [inspect_record(tokenizer, row, index) for index, row in enumerate(rows)]
    failures = [record for record in records if not record["ok"]]
    report = {
        "model": args.model,
        "dataset": args.dataset.as_posix(),
        "checked_records": len(records),
        "failed_records": len(failures),
        "records": records,
    }
    if args.out:
        write_json(args.out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
