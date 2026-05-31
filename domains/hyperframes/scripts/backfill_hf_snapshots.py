"""Backfill retained snapshot frames for completed HyperFrames task runs."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from hf_factory_lib import ARTIFACTS_DIR, copy_template_to_workspace, prepare_dependencies, run_command, write_json
from score_hf_task import score_run, snapshot_frames_retained


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_attempt_dir(run_dir: Path, verdict: dict[str, Any]) -> Path:
    attempts_used = int(verdict.get("attempts") or 1)
    return run_dir / "attempts" / str(attempts_used)


def copy_final_files_to_workspace(run_dir: Path, workspace: Path, verdict: dict[str, Any]) -> None:
    final_root = Path(verdict.get("final_files_root") or run_dir / "final_files")
    for file_path in verdict.get("final_files", []):
        src = final_root / file_path
        dst = workspace / file_path
        if src.exists() and src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def retained_frames(attempt_dir: Path) -> list[str]:
    return sorted(path.as_posix() for path in (attempt_dir / "snapshots").glob("frame-*.png"))


def report_frames_exist(attempt_dir: Path) -> bool:
    report_path = attempt_dir / "diagnostics" / "snapshot-report.json"
    if not report_path.exists():
        return False
    return snapshot_frames_retained(load_json(report_path), attempt_dir)


def update_verdict(run_dir: Path, attempt_dir: Path) -> dict[str, Any]:
    verdict_path = run_dir / "verdict.json"
    verdict = load_json(verdict_path)
    score = score_run(run_dir, attempt_dir=attempt_dir)
    verdict.update({
        "score": score["score"],
        "passed_checks": score["passed_checks"],
        "failed_checks": score["failed_checks"],
        "missing_required_checks": score["missing_required_checks"],
        "screenshots": sorted(path.as_posix() for path in (run_dir / "attempts").rglob("screenshots/*.png")),
        "snapshot_frames": retained_frames(attempt_dir),
    })
    write_json(verdict_path, verdict)
    return verdict


def backfill_run(run_dir: Path, timeout_seconds: int, force: bool, dry_run: bool) -> str:
    verdict_path = run_dir / "verdict.json"
    task_path = run_dir / "task.json"
    if not verdict_path.exists() or not task_path.exists():
        return "skip_missing_metadata"

    verdict = load_json(verdict_path)
    if verdict.get("factory") != "hyperframes" or verdict.get("status") != "pass":
        return "skip_not_pass"

    attempt_dir = latest_attempt_dir(run_dir, verdict)
    if not force and report_frames_exist(attempt_dir):
        if not dry_run:
            update_verdict(run_dir, attempt_dir)
        return "already_retained"

    if dry_run:
        return "would_backfill"

    snapshots_dir = attempt_dir / "snapshots"
    screenshots_dir = attempt_dir / "screenshots"
    diagnostics_dir = attempt_dir / "diagnostics"
    if snapshots_dir.exists():
        shutil.rmtree(snapshots_dir)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"{run_dir.name}-snapshot-") as tmp:
        workspace = Path(tmp)
        copy_template_to_workspace(workspace)
        prepare_dependencies(workspace)
        copy_final_files_to_workspace(run_dir, workspace, verdict)
        result = run_command(
            "backfill_snapshot",
            ["npm", "run", "snapshot"],
            workspace,
            attempt_dir / "logs" / "backfill_snapshot.log",
            timeout_seconds,
            env={
                "HF_EVAL_SNAPSHOT_DIR": snapshots_dir.as_posix(),
                "HF_EVAL_DESKTOP_SCREENSHOT_PATH": (screenshots_dir / "desktop.png").as_posix(),
            },
        )
        if (workspace / "diagnostics").exists():
            shutil.copytree(workspace / "diagnostics", diagnostics_dir, dirs_exist_ok=True)
        if result.returncode != 0:
            return "snapshot_failed"

    if not report_frames_exist(attempt_dir):
        return "frames_missing_after_backfill"
    update_verdict(run_dir, attempt_dir)
    return "backfilled"


def iter_run_dirs(root: Path):
    for verdict_path in sorted(root.glob("*/verdict.json")):
        yield verdict_path.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill retained HyperFrames snapshot frame PNGs")
    parser.add_argument("--runs-root", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--only", default="", help="Comma-separated task ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected = {item.strip() for item in args.only.split(",") if item.strip()}
    counts: dict[str, int] = {}
    processed = 0
    for run_dir in iter_run_dirs(args.runs_root):
        if selected and run_dir.name not in selected:
            continue
        if args.limit is not None and processed >= args.limit:
            break
        status = backfill_run(run_dir, args.timeout_seconds, args.force, args.dry_run)
        counts[status] = counts.get(status, 0) + 1
        processed += 1
        print(json.dumps({"task_id": run_dir.name, "status": status}, sort_keys=True))

    print(json.dumps({"processed": processed, "counts": counts}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
