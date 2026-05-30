"""Create clean SFT JSONL datasets from passing local task runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from task_factory_lib import (
    ALLOWED_FILE,
    ARTIFACTS_DIR,
    FINETUNE_DIR,
    allowed_file_clean,
    stable_hash,
    write_json,
)


SYSTEM_PROMPT = (
    "You are an expert Three.js, TSL, WebGPU, React Three Fiber, and Drei coding agent. "
    "Return a correct implementation for the requested app task. Use strict TypeScript and "
    "edit only src/solution.tsx."
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_run_dirs(root: Path):
    if not root.exists():
        return
    for verdict_path in sorted(root.glob("*/verdict.json")):
        yield verdict_path.parent


def user_prompt(task: dict[str, Any]) -> str:
    constraints = "\n".join(f"- {item}" for item in task.get("constraints", []))
    checks = "\n".join(f"- {item}" for item in task.get("checks", []))
    return f"""Task: {task['prompt']}

Editable file: {task.get('allowed_file', ALLOWED_FILE.as_posix())}

Constraints:
{constraints}

Checks:
{checks}
"""


def assistant_response(solution: str) -> str:
    return f"""Implemented `src/solution.tsx`:

```tsx
{solution.rstrip()}
```
"""


def make_record(run_dir: Path) -> dict[str, Any] | None:
    verdict = load_json(run_dir / "verdict.json")
    task = load_json(run_dir / "task.json")
    if verdict.get("status") != "pass":
        return None
    if task.get("split") != "train":
        return None
    if int(verdict.get("score", 0)) < int(verdict.get("score_threshold", task.get("score_threshold", 0))):
        return None
    modified = verdict.get("modified_files", [])
    if ALLOWED_FILE.as_posix() not in modified:
        return None
    if any(not allowed_file_clean(path) for path in modified):
        return None
    screenshots = [Path(path) for path in verdict.get("screenshots", [])]
    if "desktop_screenshot" not in verdict.get("passed_checks", []):
        return None
    if not any(path.exists() for path in screenshots):
        return None
    solution_path = Path(verdict.get("final_solution_path", ""))
    if not solution_path.exists():
        return None
    solution = solution_path.read_text(encoding="utf-8", errors="replace")
    solution_hash = stable_hash(solution)
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(task)},
            {"role": "assistant", "content": assistant_response(solution)},
        ],
        "metadata": {
            "task_id": task["id"],
            "topics": task.get("topics", []),
            "difficulty": task.get("difficulty", ""),
            "score": verdict.get("score", 0),
            "checks_passed": verdict.get("passed_checks", []),
            "source_run_path": run_dir.as_posix(),
            "screenshot_path": next((path.as_posix() for path in screenshots if path.exists()), ""),
            "final_solution_hash": solution_hash,
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SFT datasets from passing task runs")
    parser.add_argument("--runs-root", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--out", type=Path, default=FINETUNE_DIR)
    parser.add_argument("--valid-fraction", type=float, default=0.05)
    args = parser.parse_args()

    records: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    eval_excluded = 0
    for run_dir in iter_run_dirs(args.runs_root) or []:
        verdict = load_json(run_dir / "verdict.json")
        task = load_json(run_dir / "task.json")
        if task.get("split") == "eval":
            eval_excluded += 1
            continue
        record = make_record(run_dir)
        if record is not None:
            records.append(record)
        else:
            rejected.append({
                "task_id": task.get("id", run_dir.name),
                "split": task.get("split"),
                "status": verdict.get("status"),
                "score": verdict.get("score", 0),
                "run_path": run_dir.as_posix(),
            })

    train: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    for record in records:
        task_id = record["metadata"]["task_id"]
        bucket = int(stable_hash(task_id)[:8], 16) / 0xFFFFFFFF
        if bucket < args.valid_fraction:
            valid.append(record)
        else:
            train.append(record)

    write_jsonl(args.out / "sft" / "train.jsonl", train)
    write_jsonl(args.out / "sft" / "valid.jsonl", valid)
    write_jsonl(args.out / "rejected" / "failed_runs.jsonl", rejected)
    manifest = {
        "total_passing_train_records": len(records),
        "train_records": len(train),
        "valid_records": len(valid),
        "rejected_train_runs": len(rejected),
        "eval_runs_excluded": eval_excluded,
        "valid_fraction": args.valid_fraction,
    }
    write_json(args.out / "sft" / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
