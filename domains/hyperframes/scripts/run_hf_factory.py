"""Run many isolated HyperFrames AutoResearch tasks."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from hf_factory_lib import ARTIFACTS_DIR, TASKS_DIR, load_task_file, write_json
from run_hf_task import run_task


def completed_verdicts() -> dict[str, dict]:
    verdicts: dict[str, dict] = {}
    if not ARTIFACTS_DIR.exists():
        return verdicts
    for verdict_path in ARTIFACTS_DIR.glob("*/verdict.json"):
        try:
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if verdict.get("factory") != "hyperframes":
            continue
        verdicts[verdict.get("task_id", verdict_path.parent.name)] = verdict
    return verdicts


def count_statuses(verdicts: dict[str, dict], task_ids: set[str]) -> tuple[int, int]:
    passes = 0
    failures = 0
    for task_id, verdict in verdicts.items():
        if task_id not in task_ids:
            continue
        if verdict.get("status") == "pass":
            passes += 1
        else:
            failures += 1
    return passes, failures


def write_lock() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = ARTIFACTS_DIR / ".factory.lock"
    if not lock_path.exists():
        write_json(lock_path, {
            "factory": "hyperframes",
            "artifact_root": ARTIFACTS_DIR.as_posix(),
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the HyperFrames data factory")
    parser.add_argument("--split", choices=["train", "eval"], required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", default="", help="Comma-separated task ids")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--stop-after-passes", type=int, default=None)
    parser.add_argument("--max-failures", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=2.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--codex-timeout-seconds", type=int, default=900)
    parser.add_argument("--check-timeout-seconds", type=int, default=120)
    parser.add_argument("--service-tier", default="fast")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    write_lock()
    task_file = TASKS_DIR / f"{args.split}_tasks.jsonl"
    selected_ids = {item.strip() for item in args.only.split(",") if item.strip()}
    fresh_passes = 0
    fresh_failures = 0

    while True:
        tasks = load_task_file(task_file, expected_split=args.split)
        if selected_ids:
            tasks = [task for task in tasks if task["id"] in selected_ids]
        if args.limit is not None:
            tasks = tasks[:args.limit]

        task_ids = {task["id"] for task in tasks}
        verdicts = completed_verdicts() if args.resume and not args.rerun else {}
        if args.resume and not args.rerun:
            passes, failures = count_statuses(verdicts, task_ids)
        else:
            passes, failures = fresh_passes, fresh_failures
        if args.stop_after_passes is not None and passes >= args.stop_after_passes:
            print(f"[hf-factory] stop-after-passes reached: {passes}/{args.stop_after_passes}")
            return
        if args.max_failures is not None and failures >= args.max_failures:
            print(f"[hf-factory] max-failures reached: {failures}/{args.max_failures}")
            return

        done = set(verdicts) if args.resume and not args.rerun else set()
        made_progress = False
        for task in tasks:
            if task["id"] in done:
                continue
            made_progress = True
            verdict = run_task(
                task,
                attempts=args.attempts,
                codex_timeout_seconds=args.codex_timeout_seconds,
                check_timeout_seconds=args.check_timeout_seconds,
                force=args.rerun,
                dry_run=args.dry_run,
                service_tier=args.service_tier,
            )
            if args.dry_run:
                continue
            if args.resume and not args.rerun and verdict:
                verdicts[task["id"]] = verdict
                passes, failures = count_statuses(verdicts, task_ids)
            else:
                if verdict and verdict.get("status") == "pass":
                    fresh_passes += 1
                else:
                    fresh_failures += 1
                passes, failures = fresh_passes, fresh_failures
            if args.stop_after_passes is not None and passes >= args.stop_after_passes:
                print(f"[hf-factory] stop-after-passes reached: {passes}/{args.stop_after_passes}")
                return
            if args.max_failures is not None and failures >= args.max_failures:
                print(f"[hf-factory] max-failures reached: {failures}/{args.max_failures}")
                return
            time.sleep(args.sleep_seconds)

        if not args.loop:
            return
        if not made_progress:
            if args.stop_after_passes is not None:
                print(
                    f"[hf-factory] no remaining tasks; passes={passes}, failures={failures}, "
                    f"target_passes={args.stop_after_passes}"
                )
                return
            time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    main()
