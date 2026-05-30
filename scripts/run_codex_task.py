"""Run one AutoResearch-aligned Codex app-building task locally."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from score_task import score_run
from task_factory_lib import (
    ALLOWED_FILE,
    APP_TEMPLATE_DIR,
    ARTIFACTS_DIR,
    PROJECT_ROOT,
    append_jsonl,
    copy_final_solution,
    copy_template_to_workspace,
    find_task,
    git_diff,
    init_workspace_git,
    modified_files,
    remove_tree,
    run_command,
    stable_hash,
    summarize_log,
    utc_timestamp,
    write_json,
)


CODEX_SYSTEM_PROMPT = """You are generating verified training data for a Three.js domain coding model.

Hard rules:
- Edit only src/solution.tsx.
- Do not edit tests, package.json, Vite config, Playwright config, tsconfig, App.tsx, or any harness file.
- Keep the app buildable with strict TypeScript.
- Prefer idiomatic Three.js, React Three Fiber, Drei, TSL, and WebGPU patterns.
- Run checks when useful, but the outer runner will make the final decision.
- Do not ask questions. Produce the best solution you can in this workspace.
"""


def task_prompt(task: dict[str, Any], attempt: int, feedback: str = "") -> str:
    constraints = "\n".join(f"- {item}" for item in task["constraints"])
    checks = "\n".join(f"- {item}" for item in task["checks"])
    feedback_block = f"\nPrevious attempt feedback:\n{feedback}\n" if feedback else ""
    return f"""{CODEX_SYSTEM_PROMPT}

Task id: {task['id']}
Attempt: {attempt}
Editable file: {task.get('allowed_file', ALLOWED_FILE.as_posix())}

User task:
{task['prompt']}

Constraints:
{constraints}

Expected checks:
{checks}
{feedback_block}
When finished, leave your implementation in src/solution.tsx.
"""


def prepare_dependencies(workspace: Path, use_template_node_modules: bool) -> None:
    template_node_modules = APP_TEMPLATE_DIR / "node_modules"
    workspace_node_modules = workspace / "node_modules"
    if use_template_node_modules and template_node_modules.exists() and not workspace_node_modules.exists():
        workspace_node_modules.symlink_to(template_node_modules, target_is_directory=True)
        return
    if not workspace_node_modules.exists():
        subprocess.run(["npm", "install"], cwd=workspace, check=True)


def run_codex(prompt: str, workspace: Path, attempt_dir: Path, timeout_seconds: int) -> int:
    prompt_path = attempt_dir / "prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    output_path = attempt_dir / "codex.jsonl"
    stderr_path = attempt_dir / "codex.stderr.log"
    last_message_path = attempt_dir / "last_message.md"
    command = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-C",
        os.fspath(workspace),
        "--output-last-message",
        os.fspath(last_message_path),
        "-",
    ]
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


def run_checks(workspace: Path, attempt_dir: Path, timeout_seconds: int) -> dict[str, dict[str, Any]]:
    logs_dir = attempt_dir / "logs"
    commands = [
        ("typecheck", ["npm", "run", "typecheck"]),
        ("build", ["npm", "run", "build"]),
        ("playwright", ["npm", "run", "test"]),
    ]
    results: dict[str, dict[str, Any]] = {}
    for name, command in commands:
        print(f"[check] {name}: {' '.join(command)}")
        env = None
        screenshot_path = None
        if name == "playwright":
            screenshot_path = attempt_dir / "screenshots" / "desktop.png"
            env = {"EVAL_SCREENSHOT_PATH": screenshot_path.as_posix()}
        try:
            result = run_command(name, command, workspace, logs_dir / f"{name}.log", timeout_seconds, env=env)
            results[name] = {
                "command": command,
                "returncode": result.returncode,
                "duration_seconds": result.duration_seconds,
                "log_path": result.log_path.as_posix(),
            }
            if screenshot_path:
                results[name]["screenshot_path"] = screenshot_path.as_posix()
                results[name]["screenshot_exists"] = screenshot_path.exists()
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
            if screenshot_path:
                results[name]["screenshot_path"] = screenshot_path.as_posix()
                results[name]["screenshot_exists"] = screenshot_path.exists()
            break
    write_json(attempt_dir / "checks.json", results)
    return results


def make_feedback(attempt_dir: Path, score: dict[str, Any]) -> str:
    lines = [
        f"Score: {score['score']} / threshold {score['score_threshold']}",
        f"Failed checks: {', '.join(score.get('failed_checks', [])) or 'none'}",
    ]
    for log_name in ["typecheck", "build", "playwright"]:
        log_path = attempt_dir / "logs" / f"{log_name}.log"
        excerpt = summarize_log(log_path, max_chars=1800)
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
    solution_path = copy_final_solution(run_dir / "workspace", run_dir)
    final_patch = run_dir / "final.patch"
    final_patch.write_text(git_diff(run_dir / "workspace"), encoding="utf-8")
    screenshots = sorted(str(path) for path in (run_dir / "attempts").rglob("screenshots/*.png"))
    verdict = {
        "task_id": task["id"],
        "split": task["split"],
        "status": status,
        "score": score.get("score", 0) if score else 0,
        "score_threshold": task["score_threshold"],
        "attempts": attempts_used,
        "passed_checks": score.get("passed_checks", []) if score else [],
        "failed_checks": score.get("failed_checks", []) if score else ["runner_error"],
        "modified_files": modified_files(run_dir / "workspace"),
        "final_patch_path": final_patch.as_posix(),
        "final_solution_path": solution_path.as_posix() if solution_path else "",
        "screenshots": screenshots,
        "started_at": started_at,
        "finished_at": utc_timestamp(),
        "duration_seconds": round(time.time() - started_time, 3),
    }
    write_json(run_dir / "verdict.json", verdict)
    append_jsonl(ARTIFACTS_DIR / "index.jsonl", verdict)
    return verdict


def run_task(
    task: dict[str, Any],
    attempts: int,
    codex_timeout_seconds: int,
    check_timeout_seconds: int,
    force: bool,
    dry_run: bool,
    use_template_node_modules: bool,
) -> dict[str, Any] | None:
    run_dir = ARTIFACTS_DIR / task["id"]
    workspace = run_dir / "workspace"
    if dry_run:
        print(json.dumps({
            "task_id": task["id"],
            "run_dir": run_dir.as_posix(),
            "workspace": workspace.as_posix(),
            "allowed_file": task["allowed_file"],
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
    prepare_dependencies(workspace, use_template_node_modules=use_template_node_modules)
    init_workspace_git(workspace)
    baseline_solution = workspace / ALLOWED_FILE
    if baseline_solution.exists():
        (run_dir / "baseline_solution_hash.txt").write_text(
            stable_hash(baseline_solution.read_text(encoding="utf-8", errors="replace")) + "\n",
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
            codex_rc = run_codex(prompt, workspace, attempt_dir, timeout_seconds=codex_timeout_seconds)
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
        run_checks(workspace, attempt_dir, timeout_seconds=check_timeout_seconds)
        last_score = score_run(run_dir, attempt_dir=attempt_dir)
        if last_score["accepted"]:
            print(f"[task] {task['id']} accepted with score {last_score['score']}")
            return final_verdict(task, run_dir, "pass", last_score, attempts_used, started_at, started_time)
        feedback = make_feedback(attempt_dir, last_score)
        print(f"[task] {task['id']} attempt {attempt} score {last_score['score']} below threshold")

    return final_verdict(task, run_dir, "fail", last_score, attempts_used, started_at, started_time)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one local Codex data-factory task")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--split", choices=["train", "eval"], default=None)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--codex-timeout-seconds", type=int, default=900)
    parser.add_argument("--check-timeout-seconds", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--no-template-node-modules", action="store_true")
    args = parser.parse_args()

    task = find_task(args.task_id, split=args.split)
    verdict = run_task(
        task,
        attempts=args.attempts,
        codex_timeout_seconds=args.codex_timeout_seconds,
        check_timeout_seconds=args.check_timeout_seconds,
        force=args.rerun,
        dry_run=args.dry_run,
        use_template_node_modules=not args.no_template_node_modules,
    )
    if verdict:
        print(json.dumps(verdict, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
