"""Run locked held-out evals against a base model or served adapter."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from model_eval_lib import (
    LocalGenerator,
    append_jsonl,
    endpoint_chat_completion,
    extract_code_block,
    read_jsonl,
    utc_timestamp,
    valid_solution_text,
    write_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
THREE_SCRIPTS = PROJECT_ROOT / "scripts"
HF_SCRIPTS = PROJECT_ROOT / "domains" / "hyperframes" / "scripts"
sys.path.insert(0, THREE_SCRIPTS.as_posix())
sys.path.insert(0, HF_SCRIPTS.as_posix())

from run_codex_task import prepare_dependencies as prepare_three_dependencies  # noqa: E402
from run_codex_task import run_clean_replay as run_three_clean_replay  # noqa: E402
from score_task import score_run as score_three_run  # noqa: E402
from task_factory_lib import ALLOWED_FILE as THREE_ALLOWED_FILE  # noqa: E402
from task_factory_lib import copy_final_solution as copy_three_final_solution  # noqa: E402
from task_factory_lib import copy_template_to_workspace as copy_three_template  # noqa: E402
from task_factory_lib import git_diff as three_git_diff  # noqa: E402
from task_factory_lib import init_workspace_git as init_three_git  # noqa: E402
from task_factory_lib import modified_files as three_modified_files  # noqa: E402
from task_factory_lib import stable_hash as three_stable_hash  # noqa: E402

from hf_factory_lib import copy_final_files as copy_hf_final_files  # noqa: E402
from hf_factory_lib import copy_template_to_workspace as copy_hf_template  # noqa: E402
from hf_factory_lib import git_diff as hf_git_diff  # noqa: E402
from hf_factory_lib import init_workspace_git as init_hf_git  # noqa: E402
from hf_factory_lib import modified_files as hf_modified_files  # noqa: E402
from hf_factory_lib import prepare_dependencies as prepare_hf_dependencies  # noqa: E402
from hf_factory_lib import stable_hash as hf_stable_hash  # noqa: E402
from run_hf_task import run_clean_replay as run_hf_clean_replay  # noqa: E402
from score_hf_task import score_run as score_hf_run  # noqa: E402


THREE_TASK_FILE = PROJECT_ROOT / "evals" / "tasks" / "eval_tasks.jsonl"
HF_TASK_FILE = PROJECT_ROOT / "domains" / "hyperframes" / "evals" / "tasks" / "eval_tasks.jsonl"
DEFAULT_OUT = PROJECT_ROOT / "artifacts" / "model-evals"


def three_system_prompt() -> str:
    return (
        "You are an expert Three.js, WebGPU, TSL, React Three Fiber, and Drei coding model. "
        "Return only the complete contents of src/solution.tsx. Do not edit or describe any other file."
    )


def hyperframes_system_prompt() -> str:
    return (
        "You are an expert HyperFrames, deterministic HTML video, HTML-in-Canvas, CanvasKit/Skia, "
        "and WebGPU coding model. Return only the complete contents of index.html."
    )


def format_task_prompt(task: dict[str, Any], factory: str) -> str:
    constraints = "\n".join(f"- {item}" for item in task.get("constraints", []))
    checks = "\n".join(f"- {item}" for item in task.get("checks", []))
    semantic = "\n".join(f"- {item.get('name', '')}" for item in task.get("semantic_checks", []))
    refs = ""
    if task.get("source_refs"):
        refs = "\n\nSource references:\n" + "\n".join(
            f"- {item.get('label', '')}: {item.get('url', '')}" for item in task.get("source_refs", [])
        )
    editable = "src/solution.tsx" if factory == "three" else "index.html"
    return f"""Task id: {task['id']}
Editable file: {editable}

Task:
{task['prompt']}
{refs}

Constraints:
{constraints}

Automated checks:
{checks}

Semantic checks:
{semantic or '- none declared'}

Return only the complete source for {editable}.
"""


class ModelClient:
    def __init__(
        self,
        model: str,
        endpoint: str,
        adapter: str,
        max_tokens: int,
        temperature: float,
        request_timeout_seconds: int,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.request_timeout_seconds = request_timeout_seconds
        self.local_generator: LocalGenerator | None = None
        if not endpoint:
            self.local_generator = LocalGenerator(model_name=model, adapter=adapter)

    def generate(self, messages: list[dict[str, str]]) -> str:
        if self.endpoint:
            return endpoint_chat_completion(
                self.endpoint,
                self.model,
                messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout_seconds=self.request_timeout_seconds,
            )
        assert self.local_generator is not None
        return self.local_generator.generate(messages, max_tokens=self.max_tokens, temperature=self.temperature)


def selected_tasks(scope: str, split: str, only: set[str], limit: int | None) -> list[tuple[str, dict[str, Any]]]:
    tasks: list[tuple[str, dict[str, Any]]] = []
    if scope in {"three", "both"}:
        tasks.extend(("three", task) for task in read_jsonl(PROJECT_ROOT / "evals" / "tasks" / f"{split}_tasks.jsonl"))
    if scope in {"hyperframes", "both"}:
        tasks.extend(
            ("hyperframes", task)
            for task in read_jsonl(PROJECT_ROOT / "domains" / "hyperframes" / "evals" / "tasks" / f"{split}_tasks.jsonl")
        )
    if only:
        tasks = [(factory, task) for factory, task in tasks if task["id"] in only]
    if limit is not None:
        tasks = tasks[:limit]
    return tasks


def write_generation_artifacts(
    attempt_dir: Path,
    messages: list[dict[str, str]],
    response: str,
    expected_path: str,
) -> tuple[str, bool, dict[str, Any]]:
    write_json(attempt_dir / "messages.json", {"messages": messages})
    (attempt_dir / "raw_response.md").write_text(response, encoding="utf-8")
    solution, extraction = extract_code_block(response, expected_path)
    ok, error = valid_solution_text(solution, expected_path)
    extraction.update({"ok": ok, "error": error, "expected_path": expected_path})
    write_json(attempt_dir / "extraction.json", extraction)
    if ok:
        (attempt_dir / "generation_returncode.txt").write_text("0\n", encoding="utf-8")
    else:
        (attempt_dir / "generation_returncode.txt").write_text("1\n", encoding="utf-8")
    return solution, ok, extraction


def run_three_eval(
    task: dict[str, Any],
    client: ModelClient,
    out_root: Path,
    check_timeout_seconds: int,
    rerun: bool,
    use_template_node_modules: bool,
) -> dict[str, Any]:
    run_dir = out_root / task["id"]
    workspace = run_dir / "workspace"
    if run_dir.exists() and rerun:
        shutil.rmtree(run_dir)
    elif (run_dir / "verdict.json").exists():
        return json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))

    started_at = utc_timestamp()
    started_time = time.time()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "task.json", task)
    copy_three_template(workspace)
    prepare_three_dependencies(workspace, use_template_node_modules=use_template_node_modules)
    init_three_git(workspace)
    baseline = workspace / THREE_ALLOWED_FILE
    if baseline.exists():
        (run_dir / "baseline_solution_hash.txt").write_text(
            three_stable_hash(baseline.read_text(encoding="utf-8", errors="replace")) + "\n",
            encoding="utf-8",
        )

    attempt_dir = run_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "system", "content": three_system_prompt()},
        {"role": "user", "content": format_task_prompt(task, "three")},
    ]
    score: dict[str, Any] | None = None
    generation_error = ""
    try:
        response = client.generate(messages)
        solution, ok, _ = write_generation_artifacts(attempt_dir, messages, response, THREE_ALLOWED_FILE.as_posix())
        if ok:
            target = workspace / THREE_ALLOWED_FILE
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(solution.rstrip() + "\n", encoding="utf-8")
            write_json(attempt_dir / "modified_files.json", three_modified_files(workspace))
            (attempt_dir / "diff.patch").write_text(three_git_diff(workspace), encoding="utf-8")
            run_three_clean_replay(
                workspace,
                attempt_dir,
                timeout_seconds=check_timeout_seconds,
                use_template_node_modules=use_template_node_modules,
            )
        else:
            write_json(attempt_dir / "checks.json", {})
            write_json(attempt_dir / "modified_files.json", three_modified_files(workspace))
            (attempt_dir / "diff.patch").write_text(three_git_diff(workspace), encoding="utf-8")
        score = score_three_run(run_dir, attempt_dir=attempt_dir)
        status = "pass" if score["accepted"] else "fail"
    except Exception as exc:
        generation_error = repr(exc)
        (attempt_dir / "generation_returncode.txt").write_text("1\n", encoding="utf-8")
        write_json(attempt_dir / "checks.json", {})
        write_json(attempt_dir / "modified_files.json", three_modified_files(workspace) if workspace.exists() else [])
        score = score_three_run(run_dir, attempt_dir=attempt_dir)
        status = "runner_error"

    final_solution = copy_three_final_solution(workspace, run_dir)
    final_patch = run_dir / "final.patch"
    final_patch.write_text(three_git_diff(workspace), encoding="utf-8")
    screenshots = sorted(str(path) for path in (run_dir / "attempts").rglob("screenshots/*.png"))
    verdict = {
        "task_id": task["id"],
        "factory": "three",
        "split": task["split"],
        "status": status,
        "score": score.get("score", 0) if score else 0,
        "score_threshold": task.get("score_threshold", 0),
        "attempts": 1,
        "passed_checks": score.get("passed_checks", []) if score else [],
        "failed_checks": score.get("failed_checks", []) if score else ["runner_error"],
        "missing_required_checks": score.get("missing_required_checks", []) if score else ["runner_error"],
        "modified_files": three_modified_files(workspace) if workspace.exists() else [],
        "final_patch_path": final_patch.as_posix(),
        "final_solution_path": final_solution.as_posix() if final_solution else "",
        "screenshots": screenshots,
        "generation_error": generation_error,
        "started_at": started_at,
        "finished_at": utc_timestamp(),
        "duration_seconds": round(time.time() - started_time, 3),
    }
    write_json(run_dir / "verdict.json", verdict)
    append_jsonl(out_root / "index.jsonl", verdict)
    return verdict


def run_hyperframes_eval(
    task: dict[str, Any],
    client: ModelClient,
    out_root: Path,
    check_timeout_seconds: int,
    rerun: bool,
) -> dict[str, Any]:
    run_dir = out_root / task["id"]
    workspace = run_dir / "workspace"
    if run_dir.exists() and rerun:
        shutil.rmtree(run_dir)
    elif (run_dir / "verdict.json").exists():
        return json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))

    started_at = utc_timestamp()
    started_time = time.time()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "task.json", task)
    copy_hf_template(workspace)
    prepare_hf_dependencies(workspace)
    init_hf_git(workspace)
    baseline = workspace / "index.html"
    (run_dir / "baseline_index_hash.txt").write_text(
        hf_stable_hash(baseline.read_text(encoding="utf-8", errors="replace")) + "\n",
        encoding="utf-8",
    )

    attempt_dir = run_dir / "attempts" / "1"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "system", "content": hyperframes_system_prompt()},
        {"role": "user", "content": format_task_prompt(task, "hyperframes")},
    ]
    score: dict[str, Any] | None = None
    generation_error = ""
    try:
        response = client.generate(messages)
        solution, ok, _ = write_generation_artifacts(attempt_dir, messages, response, "index.html")
        if ok:
            (workspace / "index.html").write_text(solution.rstrip() + "\n", encoding="utf-8")
            write_json(attempt_dir / "modified_files.json", hf_modified_files(workspace))
            (attempt_dir / "diff.patch").write_text(hf_git_diff(workspace), encoding="utf-8")
            run_hf_clean_replay(workspace, attempt_dir, task, timeout_seconds=check_timeout_seconds)
        else:
            write_json(attempt_dir / "checks.json", {})
            write_json(attempt_dir / "modified_files.json", hf_modified_files(workspace))
            (attempt_dir / "diff.patch").write_text(hf_git_diff(workspace), encoding="utf-8")
        score = score_hf_run(run_dir, attempt_dir=attempt_dir)
        status = "pass" if score["accepted"] else "fail"
    except Exception as exc:
        generation_error = repr(exc)
        (attempt_dir / "generation_returncode.txt").write_text("1\n", encoding="utf-8")
        write_json(attempt_dir / "checks.json", {})
        write_json(attempt_dir / "modified_files.json", hf_modified_files(workspace) if workspace.exists() else [])
        score = score_hf_run(run_dir, attempt_dir=attempt_dir)
        status = "runner_error"

    final_files = copy_hf_final_files(workspace, run_dir, task)
    final_patch = run_dir / "final.patch"
    final_patch.write_text(hf_git_diff(workspace), encoding="utf-8")
    screenshots = sorted(str(path) for path in (run_dir / "attempts").rglob("screenshots/*.png"))
    snapshot_frames = sorted(str(path) for path in (run_dir / "attempts").rglob("snapshots/frame-*.png"))
    verdict = {
        "task_id": task["id"],
        "factory": "hyperframes",
        "split": task["split"],
        "status": status,
        "score": score.get("score", 0) if score else 0,
        "score_threshold": task.get("score_threshold", 0),
        "attempts": 1,
        "passed_checks": score.get("passed_checks", []) if score else [],
        "failed_checks": score.get("failed_checks", []) if score else ["runner_error"],
        "missing_required_checks": score.get("missing_required_checks", []) if score else ["runner_error"],
        "modified_files": hf_modified_files(workspace) if workspace.exists() else [],
        "final_patch_path": final_patch.as_posix(),
        "final_files": final_files,
        "final_files_root": (run_dir / "final_files").as_posix(),
        "screenshots": screenshots,
        "snapshot_frames": snapshot_frames,
        "generation_error": generation_error,
        "started_at": started_at,
        "finished_at": utc_timestamp(),
        "duration_seconds": round(time.time() - started_time, 3),
    }
    write_json(run_dir / "verdict.json", verdict)
    append_jsonl(out_root / "index.jsonl", verdict)
    return verdict


def summarize(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    by_factory: dict[str, Counter] = {}
    failed_checks: Counter = Counter()
    for verdict in verdicts:
        factory = verdict.get("factory", "unknown")
        by_factory.setdefault(factory, Counter())[verdict.get("status", "unknown")] += 1
        if verdict.get("status") != "pass":
            failed_checks.update(verdict.get("failed_checks", []))
    return {
        "total": len(verdicts),
        "status_counts": dict(Counter(verdict.get("status", "unknown") for verdict in verdicts)),
        "factory_status_counts": {factory: dict(counts) for factory, counts in by_factory.items()},
        "average_score": round(sum(float(verdict.get("score", 0)) for verdict in verdicts) / max(len(verdicts), 1), 3),
        "failed_check_counts": dict(failed_checks.most_common()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run locked model evals")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-endpoint", default="")
    parser.add_argument("--adapter", default="")
    parser.add_argument("--scope", choices=["three", "hyperframes", "both"], default="both")
    parser.add_argument("--split", choices=["train", "eval"], default="eval")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT / "qwen36-run")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", default="")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--request-timeout-seconds", type=int, default=900)
    parser.add_argument("--check-timeout-seconds", type=int, default=180)
    parser.add_argument("--no-template-node-modules", action="store_true")
    args = parser.parse_args()

    only = {item.strip() for item in args.only.split(",") if item.strip()}
    tasks = selected_tasks(args.scope, args.split, only=only, limit=args.limit)
    if args.dry_run:
        print(json.dumps({
            "model": args.model,
            "endpoint": args.model_endpoint,
            "out": args.out.as_posix(),
            "tasks": [{"factory": factory, "task_id": task["id"]} for factory, task in tasks],
        }, indent=2, sort_keys=True))
        return

    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "run_config.json", {
        "model": args.model,
        "model_endpoint": args.model_endpoint,
        "adapter": args.adapter,
        "scope": args.scope,
        "split": args.split,
        "started_at": utc_timestamp(),
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    })
    client = ModelClient(
        model=args.model,
        endpoint=args.model_endpoint,
        adapter=args.adapter,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        request_timeout_seconds=args.request_timeout_seconds,
    )

    verdicts: list[dict[str, Any]] = []
    for factory, task in tasks:
        print(f"[eval] {factory} {task['id']}")
        if factory == "three":
            verdict = run_three_eval(
                task,
                client,
                args.out,
                check_timeout_seconds=args.check_timeout_seconds,
                rerun=args.rerun,
                use_template_node_modules=not args.no_template_node_modules,
            )
        else:
            verdict = run_hyperframes_eval(
                task,
                client,
                args.out,
                check_timeout_seconds=args.check_timeout_seconds,
                rerun=args.rerun,
            )
        verdicts.append(verdict)

    summary = summarize(verdicts)
    summary["finished_at"] = utc_timestamp()
    write_json(args.out / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
