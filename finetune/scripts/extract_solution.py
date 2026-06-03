"""Extract an editable solution file from a model response."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from model_eval_lib import extract_code_block, valid_solution_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract code from a model response")
    parser.add_argument("response", type=Path)
    parser.add_argument("--expected-path", required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    text = args.response.read_text(encoding="utf-8", errors="replace")
    solution, metadata = extract_code_block(text, args.expected_path)
    ok, error = valid_solution_text(solution, args.expected_path)
    metadata.update({"ok": ok, "error": error})
    if args.out and ok:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(solution.rstrip() + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2, sort_keys=True))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
