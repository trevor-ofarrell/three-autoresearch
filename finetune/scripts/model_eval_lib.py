"""Shared helpers for locked model evals."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def endpoint_chat_completion(
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    timeout_seconds: int,
) -> str:
    base = endpoint.rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"model endpoint HTTP {exc.code}: {body}") from exc
    return data["choices"][0]["message"]["content"]


@dataclass
class LocalGenerator:
    model_name: str
    adapter: str = ""
    dtype: str = "auto"
    device_map: str = "auto"
    trust_remote_code: bool = True

    def __post_init__(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoProcessor, AutoTokenizer

        torch_dtype = self.dtype
        if self.dtype == "bfloat16":
            torch_dtype = torch.bfloat16
        elif self.dtype == "float16":
            torch_dtype = torch.float16

        self.processor = None
        try:
            self.processor = AutoProcessor.from_pretrained(self.model_name, trust_remote_code=self.trust_remote_code)
            self.tokenizer = getattr(self.processor, "tokenizer", self.processor)
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=self.trust_remote_code)

        model_kwargs = {
            "torch_dtype": torch_dtype,
            "device_map": self.device_map,
            "trust_remote_code": self.trust_remote_code,
        }
        try:
            self.model = AutoModelForImageTextToText.from_pretrained(self.model_name, **model_kwargs)
        except Exception:
            self.model = AutoModelForCausalLM.from_pretrained(self.model_name, **model_kwargs)

        if self.adapter:
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, self.adapter)
        self.model.eval()

    def generate(self, messages: list[dict[str, str]], max_tokens: int, temperature: float) -> str:
        import torch

        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        do_sample = temperature > 0
        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "do_sample": do_sample,
        }
        if do_sample:
            generate_kwargs["temperature"] = temperature
        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                **generate_kwargs,
            )
        generated = output_ids[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(generated, skip_special_tokens=True)


def extract_code_block(response: str, expected_path: str) -> tuple[str, dict[str, Any]]:
    extension = expected_path.rsplit(".", 1)[-1].lower()
    preferred = {
        "tsx": {"tsx", "typescript", "ts", "jsx", "javascript", "js"},
        "html": {"html", "xml"},
    }.get(extension, {extension})

    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"```([A-Za-z0-9_-]*)\s*\n(.*?)```", response, flags=re.DOTALL):
        blocks.append((match.group(1).strip().lower(), match.group(2)))

    chosen = ""
    language = ""
    if blocks:
        for lang, body in blocks:
            if lang in preferred:
                language = lang
                chosen = body
                break
        if not chosen:
            language, chosen = max(blocks, key=lambda item: len(item[1]))
    else:
        chosen = response

    cleaned = chosen.strip()
    cleaned = re.sub(r"^File:\s*`?[^`\n]+`?\s*", "", cleaned).strip()
    metadata = {
        "used_code_fence": bool(blocks),
        "fence_language": language,
        "response_chars": len(response),
        "solution_chars": len(cleaned),
    }
    return cleaned, metadata


def valid_solution_text(solution: str, expected_path: str) -> tuple[bool, str]:
    if not solution.strip():
        return False, "empty solution"
    if len(solution) > 200_000:
        return False, "solution exceeds 200000 chars"
    if expected_path.endswith(".html") and "<" not in solution:
        return False, "html solution does not contain markup"
    if expected_path.endswith(".tsx") and ("export" not in solution and "function" not in solution and "const" not in solution):
        return False, "tsx solution does not look like TypeScript/React source"
    return True, ""
