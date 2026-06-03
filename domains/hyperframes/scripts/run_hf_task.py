"""Run one isolated HyperFrames AutoResearch task locally."""

from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from hf_factory_lib import (
    ARTIFACTS_DIR,
    DEFAULT_ALLOWED_FILES,
    TARGET_APP_ROOT,
    append_jsonl,
    copy_final_files,
    copy_template_to_workspace,
    find_task,
    git_diff,
    init_workspace_git,
    modified_files,
    prepare_dependencies,
    remove_tree,
    run_command,
    stable_hash,
    summarize_log,
    utc_timestamp,
    write_json,
)
from score_hf_task import score_run


CODEX_SYSTEM_PROMPT = """You are generating verified training data for a HyperFrames video/canvas coding model.

Hard rules:
- Work only inside this copied task workspace.
- Edit only files allowed by the task, usually index.html.
- Do not edit project.manifest.json, vendor files, diagnostics, snapshots, renders, package.json, tools, or runner files.
- Build deterministic HyperFrames HTML: seek-driven animation, no wall-clock animation, no network render dependencies.
- Prefer production-grade HTML-in-Canvas, CanvasKit/Skia, WebGPU/TypeGPU, and HyperFrames patterns when requested.
- Include real visible fallbacks for experimental APIs.
- Do not ask questions. Produce the best solution you can in this workspace.
"""


def task_prompt(task: dict[str, Any], attempt: int, feedback: str = "") -> str:
    constraints = "\n".join(f"- {item}" for item in task["constraints"])
    checks = "\n".join(f"- {item}" for item in task["checks"])
    allowed_files = "\n".join(f"- {item}" for item in task.get("allowed_files", DEFAULT_ALLOWED_FILES))
    refs = "\n".join(f"- {item['label']}: {item['url']}" for item in task.get("source_refs", []))
    feedback_block = f"\nPrevious attempt feedback:\n{feedback}\n" if feedback else ""
    return f"""{CODEX_SYSTEM_PROMPT}

Task id: {task['id']}
Attempt: {attempt}

Editable files:
{allowed_files}

User task:
{task['prompt']}

Source references:
{refs}

Constraints:
{constraints}

Expected checks:
{checks}
{feedback_block}
When finished, leave the accepted HyperFrames implementation in the allowed files.
"""


def run_codex(
    prompt: str,
    workspace: Path,
    attempt_dir: Path,
    timeout_seconds: int,
    service_tier: str,
) -> int:
    prompt_path = attempt_dir / "prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    output_path = attempt_dir / "codex.jsonl"
    stderr_path = attempt_dir / "codex.stderr.log"
    last_message_path = attempt_dir / "last_message.md"
    command = [
        "codex",
        "--ask-for-approval",
        "never",
    ]
    if service_tier:
        command.extend(["-c", f'service_tier="{service_tier}"'])
    command.extend([
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-C",
        os.fspath(workspace),
        "--output-last-message",
        os.fspath(last_message_path),
        "-",
    ])
    print(f"[codex] starting in {workspace}")
    start = time.time()
    with prompt_path.open("r", encoding="utf-8") as stdin:
        with output_path.open("w", encoding="utf-8") as stdout:
            with stderr_path.open("w", encoding="utf-8") as stderr:
                process = subprocess.Popen(
                    command,
                    stdin=stdin,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    start_new_session=True,
                )
                while True:
                    rc = process.poll()
                    if rc is not None:
                        print(f"[codex] exited rc={rc} after {time.time() - start:.1f}s")
                        return rc
                    elapsed = time.time() - start
                    if elapsed > timeout_seconds:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                        raise subprocess.TimeoutExpired(command, timeout_seconds)
                    print(f"[codex] still running after {elapsed:.0f}s")
                    time.sleep(30)


def copy_generated_reports(workspace: Path, attempt_dir: Path) -> None:
    diagnostics_src = workspace / "diagnostics"
    diagnostics_dst = attempt_dir / "diagnostics"
    if diagnostics_src.exists():
        if diagnostics_dst.exists():
            shutil.rmtree(diagnostics_dst)
        shutil.copytree(diagnostics_src, diagnostics_dst)

    snapshots_src = workspace / "snapshots"
    snapshots_dst = attempt_dir / "snapshots"
    if snapshots_src.exists():
        snapshots_dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(snapshots_src, snapshots_dst, dirs_exist_ok=True)


def run_checks(workspace: Path, attempt_dir: Path, timeout_seconds: int) -> dict[str, dict[str, Any]]:
    logs_dir = attempt_dir / "logs"
    screenshot_dir = attempt_dir / "screenshots"
    desktop_screenshot = screenshot_dir / "desktop.png"
    hyperframes_bin = TARGET_APP_ROOT / "node_modules" / ".bin" / "hyperframes"
    lint_command = [hyperframes_bin.as_posix(), "lint", "--json", "."] if hyperframes_bin.exists() else ["npm", "run", "lint"]
    commands = [
        ("typecheck", ["npm", "run", "typecheck"]),
        ("lint", lint_command),
        ("validate", ["npm", "run", "validate"]),
        ("snapshot", ["npm", "run", "snapshot"]),
    ]
    results: dict[str, dict[str, Any]] = {}
    for name, command in commands:
        print(f"[check] {name}: {' '.join(command)}")
        env = None
        if name == "snapshot":
            env = {
                "HF_EVAL_SNAPSHOT_DIR": (attempt_dir / "snapshots").as_posix(),
                "HF_EVAL_DESKTOP_SCREENSHOT_PATH": desktop_screenshot.as_posix(),
            }
        try:
            result = run_command(name, command, workspace, logs_dir / f"{name}.log", timeout_seconds, env=env)
            results[name] = {
                "command": command,
                "returncode": result.returncode,
                "duration_seconds": result.duration_seconds,
                "log_path": result.log_path.as_posix(),
            }
        except subprocess.TimeoutExpired:
            timeout_log = logs_dir / f"{name}.log"
            timeout_log.parent.mkdir(parents=True, exist_ok=True)
            timeout_log.write_text(f"{name} timed out after {timeout_seconds}s\n", encoding="utf-8")
            results[name] = {
                "command": command,
                "returncode": 124,
                "duration_seconds": timeout_seconds,
                "log_path": timeout_log.as_posix(),
            }
            break
        finally:
            copy_generated_reports(workspace, attempt_dir)
        if name == "snapshot":
            results[name]["desktop_screenshot_path"] = desktop_screenshot.as_posix()
            results[name]["desktop_screenshot_exists"] = desktop_screenshot.exists()
    write_json(attempt_dir / "checks.json", results)
    return results


def overlay_allowed_files(src_workspace: Path, dst_workspace: Path, task: dict[str, Any]) -> None:
    for file_path in modified_files(src_workspace):
        normalized = file_path.replace("\\", "/")
        allowed = normalized in task.get("allowed_files", DEFAULT_ALLOWED_FILES)
        generated_asset = task.get("allow_generated_assets") and normalized.startswith("assets/generated/")
        if not allowed and not generated_asset:
            continue
        src = src_workspace / normalized
        dst = dst_workspace / normalized
        if not src.exists() or not src.is_file() or src.is_symlink():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def run_clean_replay(workspace: Path, attempt_dir: Path, task: dict[str, Any], timeout_seconds: int) -> None:
    replay_workspace = attempt_dir / "clean_replay_workspace"
    copy_template_to_workspace(replay_workspace)
    prepare_dependencies(replay_workspace)
    overlay_allowed_files(workspace, replay_workspace, task)
    results = run_checks(replay_workspace, attempt_dir, timeout_seconds=timeout_seconds)
    results["_meta"] = {
        "clean_replay": True,
        "clean_replay_workspace": replay_workspace.as_posix(),
    }
    write_json(attempt_dir / "checks.json", results)


def make_feedback(attempt_dir: Path, score: dict[str, Any]) -> str:
    lines = [
        f"Score: {score['score']} / threshold {score['score_threshold']}",
        f"Failed checks: {', '.join(score.get('failed_checks', [])) or 'none'}",
        f"Missing required checks: {', '.join(score.get('missing_required_checks', [])) or 'none'}",
    ]
    for log_name in ["typecheck", "lint", "validate", "snapshot"]:
        excerpt = summarize_log(attempt_dir / "logs" / f"{log_name}.log", max_chars=1800)
        if excerpt:
            lines.append(f"\n{log_name} log excerpt:\n{excerpt}")
    return "\n".join(lines)


def final_verdict(
    task: dict[str, Any],
    run_dir: Path,
    status: str,
    score: dict[str, Any] | None,
    attempts_used: int,
    started_at: str,
    started_time: float,
) -> dict[str, Any]:
    final_files = copy_final_files(run_dir / "workspace", run_dir, task)
    final_patch = run_dir / "final.patch"
    final_patch.write_text(git_diff(run_dir / "workspace"), encoding="utf-8")
    screenshots = sorted(str(path) for path in (run_dir / "attempts").rglob("screenshots/*.png"))
    snapshot_frames = sorted(str(path) for path in (run_dir / "attempts").rglob("snapshots/frame-*.png"))
    verdict = {
        "task_id": task["id"],
        "factory": "hyperframes",
        "split": task["split"],
        "status": status,
        "score": score.get("score", 0) if score else 0,
        "score_threshold": task["score_threshold"],
        "attempts": attempts_used,
        "passed_checks": score.get("passed_checks", []) if score else [],
        "failed_checks": score.get("failed_checks", []) if score else ["runner_error"],
        "missing_required_checks": score.get("missing_required_checks", []) if score else ["runner_error"],
        "modified_files": modified_files(run_dir / "workspace"),
        "final_patch_path": final_patch.as_posix(),
        "final_files": final_files,
        "final_files_root": (run_dir / "final_files").as_posix(),
        "screenshots": screenshots,
        "snapshot_frames": snapshot_frames,
        "started_at": started_at,
        "finished_at": utc_timestamp(),
        "duration_seconds": round(time.time() - started_time, 3),
    }
    tmp_path = run_dir / "verdict.json.tmp"
    write_json(tmp_path, verdict)
    tmp_path.replace(run_dir / "verdict.json")
    append_jsonl(ARTIFACTS_DIR / "index.jsonl", verdict)
    return verdict


def run_task(
    task: dict[str, Any],
    attempts: int,
    codex_timeout_seconds: int,
    check_timeout_seconds: int,
    force: bool,
    dry_run: bool,
    service_tier: str,
) -> dict[str, Any] | None:
    run_dir = ARTIFACTS_DIR / task["id"]
    workspace = run_dir / "workspace"
    if dry_run:
        print(json.dumps({
            "task_id": task["id"],
            "factory": "hyperframes",
            "run_dir": run_dir.as_posix(),
            "workspace": workspace.as_posix(),
            "allowed_files": task["allowed_files"],
            "allow_generated_assets": task["allow_generated_assets"],
            "attempts": attempts,
            "checks": task["checks"],
        }, indent=2, sort_keys=True))
        return None

    if run_dir.exists() and force:
        remove_tree(run_dir)
    elif (run_dir / "verdict.json").exists():
        return json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))

    started_at = utc_timestamp()
    started_time = time.time()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "task.json", task)
    copy_template_to_workspace(workspace)
    prepare_dependencies(workspace)
    init_workspace_git(workspace)
    baseline_index = workspace / "index.html"
    (run_dir / "baseline_index_hash.txt").write_text(
        stable_hash(baseline_index.read_text(encoding="utf-8", errors="replace")) + "\n",
        encoding="utf-8",
    )

    feedback = ""
    last_score: dict[str, Any] | None = None
    attempts_used = 0
    for attempt in range(1, attempts + 1):
        attempts_used = attempt
        attempt_dir = run_dir / "attempts" / str(attempt)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        prompt = task_prompt(task, attempt=attempt, feedback=feedback)
        print(f"[task] {task['id']} attempt {attempt}/{attempts}")
        try:
            codex_rc = run_codex(prompt, workspace, attempt_dir, timeout_seconds=codex_timeout_seconds, service_tier=service_tier)
        except KeyboardInterrupt:
            return final_verdict(task, run_dir, "runner_error", last_score, attempts_used, started_at, started_time)
        except subprocess.TimeoutExpired:
            (attempt_dir / "codex.stderr.log").write_text(
                f"codex timed out after {codex_timeout_seconds}s\n",
                encoding="utf-8",
            )
            codex_rc = 124
        (attempt_dir / "codex_returncode.txt").write_text(f"{codex_rc}\n", encoding="utf-8")

        mods = modified_files(workspace)
        write_json(attempt_dir / "modified_files.json", mods)
        (attempt_dir / "diff.patch").write_text(git_diff(workspace), encoding="utf-8")
        run_clean_replay(workspace, attempt_dir, task, timeout_seconds=check_timeout_seconds)
        last_score = score_run(run_dir, attempt_dir=attempt_dir)
        if last_score["accepted"]:
            print(f"[task] {task['id']} accepted with score {last_score['score']}")
            return final_verdict(task, run_dir, "pass", last_score, attempts_used, started_at, started_time)
        feedback = make_feedback(attempt_dir, last_score)
        print(f"[task] {task['id']} attempt {attempt} score {last_score['score']} below threshold")

    return final_verdict(task, run_dir, "fail", last_score, attempts_used, started_at, started_time)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one HyperFrames data-factory task")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--split", choices=["train", "eval"], default=None)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--codex-timeout-seconds", type=int, default=900)
    parser.add_argument("--check-timeout-seconds", type=int, default=120)
    parser.add_argument("--service-tier", default="fast")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args()

    task = find_task(args.task_id, split=args.split)
    verdict = run_task(
        task,
        attempts=args.attempts,
        codex_timeout_seconds=args.codex_timeout_seconds,
        check_timeout_seconds=args.check_timeout_seconds,
        force=args.rerun,
        dry_run=args.dry_run,
        service_tier=args.service_tier,
    )
    if verdict:
        print(json.dumps(verdict, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
