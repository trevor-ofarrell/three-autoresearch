"""Shared helpers for Qwen3.6 fine-tuning utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "Qwen/Qwen3.6-27B"


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_processor_and_tokenizer(model_name: str, trust_remote_code: bool = True):
    """Return (processor_or_none, tokenizer_like).

    Qwen3.6-27B is exposed as image-text-to-text on Hugging Face, so tokenizer-only
    loading can fail in some environments. The utilities first try AutoProcessor
    and then fall back to AutoTokenizer for text-only workflows.
    """

    from transformers import AutoProcessor, AutoTokenizer

    processor = None
    try:
        processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=trust_remote_code)
        tokenizer = getattr(processor, "tokenizer", processor)
        if hasattr(tokenizer, "apply_chat_template"):
            return processor, tokenizer
    except Exception:
        processor = None

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=trust_remote_code)
    return processor, tokenizer


def render_chat(tokenizer: Any, messages: list[dict[str, Any]], add_generation_prompt: bool) -> str:
    rendered = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=add_generation_prompt,
    )
    if isinstance(rendered, list):
        return "".join(str(item) for item in rendered)
    return str(rendered)


def token_ids(tokenizer: Any, text: str) -> list[int]:
    encoded = tokenizer(text, add_special_tokens=False)
    return list(encoded["input_ids"])


def decode(tokenizer: Any, ids: list[int]) -> str:
    return tokenizer.decode(ids, skip_special_tokens=False)


def common_prefix_len(left: list[int], right: list[int]) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def load_messages_record(path: Path, index: int) -> dict[str, Any]:
    rows = read_jsonl(path)
    if index < 0 or index >= len(rows):
        raise IndexError(f"record index {index} is outside dataset of {len(rows)} rows")
    row = rows[index]
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"{path}:{index}: record has no chat messages")
    return row
