"""Create clean SFT datasets from passing HyperFrames task runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hf_factory_lib import ARTIFACTS_DIR, FINETUNE_DIR, TASKS_DIR, allowed_file_clean, load_task_file, stable_hash, write_json


SYSTEM_PROMPT = (
    "You are an expert HyperFrames, HTML-in-Canvas, CanvasKit/Skia, WebGPU, and deterministic "
    "HTML video composition agent. Return correct source edits for the requested HyperFrames task."
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
    refs = "\n".join(f"- {item['label']}: {item['url']}" for item in task.get("source_refs", []))
    allowed = "\n".join(f"- {item}" for item in task.get("allowed_files", ["index.html"]))
    return f"""Task: {task['prompt']}

Editable files:
{allowed}

Source references:
{refs}

Constraints:
{constraints}

Checks:
{checks}
"""


def format_file(path: str, content: str) -> str:
    fence = "html" if path.endswith(".html") else ""
    return f"File: `{path}`\n\n```{fence}\n{content.rstrip()}\n```"


def assistant_response(final_root: Path, files: list[str]) -> str:
    parts = []
    for file_path in files:
        path = final_root / file_path
        if not path.exists() or not path.is_file():
            continue
        if path.stat().st_size > 120_000:
            parts.append(f"File: `{file_path}`\n\n[omitted: generated asset larger than 120KB]")
            continue
        parts.append(format_file(file_path, path.read_text(encoding="utf-8", errors="replace")))
    return "Implemented accepted HyperFrames project source:\n\n" + "\n\n".join(parts)


def make_record(run_dir: Path, current_train_ids: set[str]) -> dict[str, Any] | None:
    verdict = load_json(run_dir / "verdict.json")
    task = load_json(run_dir / "task.json")
    if verdict.get("factory") != "hyperframes":
        return None
    if verdict.get("status") != "pass":
        return None
    if task.get("split") != "train":
        return None
    if task.get("id") not in current_train_ids:
        return None
    if int(verdict.get("score", 0)) < int(verdict.get("score_threshold", task.get("score_threshold", 0))):
        return None
    if verdict.get("missing_required_checks"):
        return None
    modified = verdict.get("modified_files", [])
    if "index.html" not in modified:
        return None
    if any(not allowed_file_clean(path, task) for path in modified):
        return None
    screenshots = [Path(path) for path in verdict.get("screenshots", [])]
    if "desktop_screenshot" not in verdict.get("passed_checks", []):
        return None
    if not any(path.exists() for path in screenshots):
        return None
    snapshot_frames = [Path(path) for path in verdict.get("snapshot_frames", [])]
    if "snapshot_frames_retained" not in verdict.get("passed_checks", []):
        return None
    if len(snapshot_frames) < 3 or not all(path.exists() for path in snapshot_frames):
        return None
    final_root = Path(verdict.get("final_files_root", ""))
    files = [path for path in verdict.get("final_files", []) if (final_root / path).exists()]
    if not files:
        return None
    index_text = (final_root / "index.html").read_text(encoding="utf-8", errors="replace") if (final_root / "index.html").exists() else ""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(task)},
            {"role": "assistant", "content": assistant_response(final_root, files)},
        ],
        "metadata": {
            "task_id": task["id"],
            "factory": "hyperframes",
            "topics": task.get("topics", []),
            "difficulty": task.get("difficulty", ""),
            "score": verdict.get("score", 0),
            "checks_passed": verdict.get("passed_checks", []),
            "source_run_path": run_dir.as_posix(),
            "screenshot_path": next((path.as_posix() for path in screenshots if path.exists()), ""),
            "snapshot_frame_paths": [path.as_posix() for path in snapshot_frames if path.exists()],
            "final_index_hash": stable_hash(index_text),
            "final_files": files,
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HyperFrames SFT datasets from passing runs")
    parser.add_argument("--runs-root", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--out", type=Path, default=FINETUNE_DIR)
    parser.add_argument("--valid-fraction", type=float, default=0.05)
    args = parser.parse_args()

    current_train_ids = {task["id"] for task in load_task_file(TASKS_DIR / "train_tasks.jsonl", expected_split="train")}
    records: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    eval_excluded = 0
    for run_dir in iter_run_dirs(args.runs_root) or []:
        verdict = load_json(run_dir / "verdict.json")
        task = load_json(run_dir / "task.json")
        if task.get("split") == "eval":
            eval_excluded += 1
            continue
        record = make_record(run_dir, current_train_ids)
        if record is not None:
            records.append(record)
        else:
            rejected.append({
                "task_id": task.get("id", run_dir.name),
                "factory": task.get("factory"),
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
        "factory": "hyperframes",
        "total_passing_train_records": len(records),
        "train_records": len(train),
        "valid_records": len(valid),
        "valid_fraction": args.valid_fraction,
        "rejected_train_runs": len(rejected),
        "eval_runs_excluded": eval_excluded,
    }
    write_json(args.out / "sft" / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
