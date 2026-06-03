"""Load Qwen3.6 plus an optional PEFT adapter and generate one sample."""

from __future__ import annotations

import argparse
from pathlib import Path

from model_eval_lib import LocalGenerator


DEFAULT_PROMPT = "Return a minimal valid TypeScript React component for src/solution.tsx."


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a sample with a local base model and optional adapter")
    parser.add_argument("--base-model", default="Qwen/Qwen3.6-27B")
    parser.add_argument("--adapter", default="")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    generator = LocalGenerator(model_name=args.base_model, adapter=args.adapter)
    messages = [
        {"role": "system", "content": "You are a precise coding model. Return only the requested source code."},
        {"role": "user", "content": args.prompt},
    ]
    response = generator.generate(messages, max_tokens=args.max_tokens, temperature=args.temperature)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(response, encoding="utf-8")
    print(response)


if __name__ == "__main__":
    main()
