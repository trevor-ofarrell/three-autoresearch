"""Inspect Qwen3.6 chat-template rendering for the SFT dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qwen36_common import DEFAULT_MODEL, PROJECT_ROOT, load_messages_record, load_processor_and_tokenizer, render_chat, token_ids


DEFAULT_DATASET = PROJECT_ROOT / "finetune" / "datasets-combined" / "sft" / "train.jsonl"


def sample_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "You are an expert Three.js and HyperFrames coding agent."},
        {"role": "user", "content": "Create the editable file for a deterministic visual app."},
        {"role": "assistant", "content": "Implemented the requested file.\n\n```tsx\nexport default function Solution() { return null }\n```"},
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Qwen3.6 chat template rendering")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--record-index", type=int, default=0)
    parser.add_argument("--sample", action="store_true", help="Use a built-in sample instead of a dataset record")
    parser.add_argument("--max-preview-chars", type=int, default=4000)
    args = parser.parse_args()

    _, tokenizer = load_processor_and_tokenizer(args.model)
    messages = sample_messages() if args.sample else load_messages_record(args.dataset, args.record_index)["messages"]
    rendered_full = render_chat(tokenizer, messages, add_generation_prompt=False)
    rendered_prompt = render_chat(tokenizer, messages[:-1], add_generation_prompt=True)
    full_ids = token_ids(tokenizer, rendered_full)
    prompt_ids = token_ids(tokenizer, rendered_prompt)

    report = {
        "model": args.model,
        "tokenizer_class": tokenizer.__class__.__name__,
        "message_roles": [message.get("role", "") for message in messages],
        "full_chars": len(rendered_full),
        "full_tokens": len(full_ids),
        "prompt_chars": len(rendered_prompt),
        "prompt_tokens": len(prompt_ids),
        "rendered_preview": rendered_full[: args.max_preview_chars],
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
