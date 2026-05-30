"""Shared helpers for local AutoResearch-aligned task generation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_TEMPLATE_DIR = PROJECT_ROOT / "evals" / "app-template"
TASKS_DIR = PROJECT_ROOT / "evals" / "tasks"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "task-runs"
FINETUNE_DIR = PROJECT_ROOT / "finetune" / "datasets"
ALLOWED_FILE = Path("src/solution.tsx")


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    duration_seconds: float
    log_path: Path


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
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
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_tasks(tasks: list[dict[str, Any]], expected_split: str | None = None) -> None:
    seen: set[str] = set()
    required = {
        "id",
        "split",
        "kind",
        "prompt",
        "constraints",
        "topics",
        "difficulty",
        "allowed_file",
        "checks",
        "score_threshold",
    }
    for task in tasks:
        missing = required - set(task)
        if missing:
            raise ValueError(f"{task.get('id', '<unknown>')}: missing fields {sorted(missing)}")
        if task["id"] in seen:
            raise ValueError(f"duplicate task id: {task['id']}")
        seen.add(task["id"])
        if expected_split is not None and task["split"] != expected_split:
            raise ValueError(f"{task['id']}: expected split {expected_split!r}, got {task['split']!r}")
        if task["allowed_file"] != ALLOWED_FILE.as_posix():
            raise ValueError(f"{task['id']}: allowed_file must be {ALLOWED_FILE.as_posix()}")
        if task.get("schema_version", 1) >= 2:
            if not task.get("source_refs"):
                raise ValueError(f"{task['id']}: schema v2 tasks must include source_refs")
            if not task.get("semantic_checks"):
                raise ValueError(f"{task['id']}: schema v2 tasks must include semantic_checks")
        if not isinstance(task["constraints"], list) or not task["constraints"]:
            raise ValueError(f"{task['id']}: constraints must be a non-empty list")
        if not isinstance(task["checks"], list) or not task["checks"]:
            raise ValueError(f"{task['id']}: checks must be a non-empty list")
        if not isinstance(task["score_threshold"], int):
            raise ValueError(f"{task['id']}: score_threshold must be an integer")


def load_task_file(path: Path, expected_split: str | None = None) -> list[dict[str, Any]]:
    tasks = read_jsonl(path)
    validate_tasks(tasks, expected_split=expected_split)
    return tasks


def find_task(task_id: str, split: str | None = None) -> dict[str, Any]:
    paths = []
    if split:
        paths.append(TASKS_DIR / f"{split}_tasks.jsonl")
    else:
        paths.extend([TASKS_DIR / "train_tasks.jsonl", TASKS_DIR / "eval_tasks.jsonl"])
    for path in paths:
        if not path.exists():
            continue
        for task in load_task_file(path):
            if task["id"] == task_id:
                return task
    raise KeyError(f"task not found: {task_id}")


def copy_template_to_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)

    def ignore(_: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"node_modules", "dist", "test-results", "playwright-report", "generated"}
        }

    shutil.copytree(APP_TEMPLATE_DIR, workspace, ignore=ignore)


def run_command(
    name: str,
    command: list[str],
    cwd: Path,
    log_path: Path,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> CommandResult:
    start = time.time()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=command_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    return CommandResult(
        name=name,
        command=command,
        returncode=process.returncode,
        duration_seconds=round(time.time() - start, 3),
        log_path=log_path,
    )


def git_diff(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--", "."],
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.stdout


def modified_files(workspace: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path)
    return sorted(files)


def init_workspace_git(workspace: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=workspace, stdout=subprocess.DEVNULL, check=True)
    subprocess.run(["git", "config", "user.email", "codex-data-factory@example.invalid"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Codex Data Factory"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, stdout=subprocess.DEVNULL, check=True)
    subprocess.run(
        ["git", "commit", "-m", "template baseline"],
        cwd=workspace,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def allowed_file_clean(path: str) -> bool:
    normalized = Path(path).as_posix()
    return normalized == ALLOWED_FILE.as_posix()


def summarize_log(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def copy_final_solution(workspace: Path, run_dir: Path) -> Path | None:
    source = workspace / ALLOWED_FILE
    if not source.exists():
        return None
    target = run_dir / "final_files" / ALLOWED_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def ensure_inside(path: Path, parent: Path) -> None:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if os.path.commonpath([resolved_path, resolved_parent]) != os.fspath(resolved_parent):
        raise ValueError(f"{path} is outside {parent}")
