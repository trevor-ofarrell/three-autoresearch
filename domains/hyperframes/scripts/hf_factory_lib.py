"""Shared helpers for the isolated HyperFrames AutoResearch factory."""

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


DOMAIN_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DOMAIN_ROOT.parents[1]
TARGET_APP_ROOT = Path("/Users/trevor/Documents/New project 3")
TEMPLATE_DIR = DOMAIN_ROOT / "evals" / "template"
TASKS_DIR = DOMAIN_ROOT / "evals" / "tasks"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "hyperframes-task-runs"
FINETUNE_DIR = PROJECT_ROOT / "finetune" / "datasets-hyperframes"
DEFAULT_ALLOWED_FILES = ["index.html"]
GENERATED_ASSETS_PREFIX = "assets/generated/"


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    duration_seconds: float
    log_path: Path


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return rows


def validate_tasks(tasks: list[dict[str, Any]], expected_split: str | None = None) -> None:
    seen: set[str] = set()
    required = {
        "id",
        "factory",
        "schema_version",
        "split",
        "kind",
        "prompt",
        "constraints",
        "topics",
        "difficulty",
        "allowed_files",
        "allow_generated_assets",
        "checks",
        "semantic_checks",
        "score_threshold",
        "source_refs",
        "template_id",
        "scorer_id",
    }
    for task in tasks:
        missing = required - set(task)
        if missing:
            raise ValueError(f"{task.get('id', '<unknown>')}: missing fields {sorted(missing)}")
        task_id = task["id"]
        if task_id in seen:
            raise ValueError(f"duplicate task id: {task_id}")
        seen.add(task_id)
        if not task_id.startswith("hf-"):
            raise ValueError(f"{task_id}: HyperFrames task ids must start with hf-")
        if task["factory"] != "hyperframes":
            raise ValueError(f"{task_id}: factory must be hyperframes")
        if task["schema_version"] != 1:
            raise ValueError(f"{task_id}: schema_version must be 1")
        if expected_split is not None and task["split"] != expected_split:
            raise ValueError(f"{task_id}: expected split {expected_split!r}, got {task['split']!r}")
        if "index.html" not in task["allowed_files"]:
            raise ValueError(f"{task_id}: allowed_files must include index.html")
        if not task["source_refs"]:
            raise ValueError(f"{task_id}: source_refs must not be empty")
        if not task["semantic_checks"]:
            raise ValueError(f"{task_id}: semantic_checks must not be empty")


def load_task_file(path: Path, expected_split: str | None = None) -> list[dict[str, Any]]:
    tasks = read_jsonl(path)
    validate_tasks(tasks, expected_split=expected_split)
    return tasks


def find_task(task_id: str, split: str | None = None) -> dict[str, Any]:
    files = [TASKS_DIR / f"{split}_tasks.jsonl"] if split else [TASKS_DIR / "train_tasks.jsonl", TASKS_DIR / "eval_tasks.jsonl"]
    for path in files:
        if not path.exists():
            continue
        for task in load_task_file(path, expected_split=split):
            if task["id"] == task_id:
                return task
    raise KeyError(f"task not found: {task_id}")


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def copy_template_to_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)

    def ignore(_: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {"node_modules", "diagnostics", "snapshots", "renders", "test-results", "playwright-report"}
        }

    shutil.copytree(TEMPLATE_DIR, workspace, ignore=ignore)
    ensure_vendor_assets(workspace)


def ensure_vendor_assets(workspace: Path) -> None:
    gsap_src = TARGET_APP_ROOT / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    gsap_dst = workspace / "vendor" / "gsap" / "gsap.min.js"
    if gsap_src.exists() and not gsap_dst.exists():
        gsap_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gsap_src, gsap_dst)

    ck_root = TARGET_APP_ROOT / "node_modules" / "canvaskit-wasm" / "bin"
    for filename in ["canvaskit.js", "canvaskit.wasm"]:
        src = ck_root / filename
        dst = workspace / "vendor" / "canvaskit" / filename
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def prepare_dependencies(workspace: Path) -> None:
    node_modules = workspace / "node_modules"
    if node_modules.exists():
        return
    candidates = [
        PROJECT_ROOT / "evals" / "app-template" / "node_modules",
        TARGET_APP_ROOT / "node_modules",
    ]
    for candidate in candidates:
        if candidate.exists():
            node_modules.symlink_to(candidate, target_is_directory=True)
            return
    subprocess.run(["npm", "install"], cwd=workspace, check=True)


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
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            env=command_env,
        )
    return CommandResult(
        name=name,
        command=command,
        returncode=process.returncode,
        duration_seconds=round(time.time() - start, 3),
        log_path=log_path,
    )


def init_workspace_git(workspace: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=workspace, check=True)


def git_diff(workspace: Path) -> str:
    result = subprocess.run(["git", "diff", "--", "."], cwd=workspace, check=False, capture_output=True, text=True)
    return result.stdout


def modified_files(workspace: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
    )
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path)
    return sorted(files)


def allowed_file_clean(path: str, task: dict[str, Any]) -> bool:
    normalized = path.replace("\\", "/")
    if normalized in task.get("allowed_files", DEFAULT_ALLOWED_FILES):
        return True
    if task.get("allow_generated_assets") and normalized.startswith(GENERATED_ASSETS_PREFIX):
        return ".." not in Path(normalized).parts
    return False


def copy_final_files(workspace: Path, run_dir: Path, task: dict[str, Any]) -> list[str]:
    out_root = run_dir / "final_files"
    if out_root.exists():
        shutil.rmtree(out_root)
    copied: list[str] = []
    for file_path in modified_files(workspace):
        if not allowed_file_clean(file_path, task):
            continue
        src = workspace / file_path
        if not src.exists() or not src.is_file() or src.is_symlink():
            continue
        dst = out_root / file_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(file_path)
    return copied


def summarize_log(path: Path, max_chars: int = 2000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
