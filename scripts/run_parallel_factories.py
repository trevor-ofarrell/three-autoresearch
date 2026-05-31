"""Run Three and HyperFrames data factories with bounded parallel task workers."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
THREE_TASKS_DIR = PROJECT_ROOT / "evals" / "tasks"
THREE_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "task-runs"
HF_TASKS_DIR = PROJECT_ROOT / "domains" / "hyperframes" / "evals" / "tasks"
HF_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "hyperframes-task-runs"
SUPERVISOR_RUNS_DIR = PROJECT_ROOT / "artifacts" / "parallel-factory-runs"
STALE_LEASE_SECONDS = 6 * 60 * 60
BROWSER_CHECKS = {
    "playwright",
    "snapshot",
    "desktop_screenshot",
    "snapshot_nonblank",
    "snapshot_frame_variation",
    "snapshot_frames_retained",
    "no_console_errors",
}


@dataclass(frozen=True)
class FactoryConfig:
    key: str
    label: str
    task_file: Path
    artifacts_dir: Path
    runner_path: Path
    soft_cap: int
    stop_after_passes: int | None
    supports_service_tier: bool


@dataclass
class RunningTask:
    factory: FactoryConfig
    task_id: str
    process: subprocess.Popen[str]
    command: list[str]
    lease_dir: Path
    log_path: Path
    started_at: float


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def filesystem_timestamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


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


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True) + "\n")


def active_single_lane_factories() -> tuple[list[str], list[str]]:
    lines: list[str] = []
    errors: list[str] = []
    current_pid = str(os.getpid())
    for pattern in ["run_data_factory.py", "run_hf_factory.py"]:
        try:
            result = subprocess.run(
                ["pgrep", "-fl", pattern],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            errors.append(f"pgrep unavailable for {pattern}")
            continue
        if result.returncode not in {0, 1}:
            errors.append((result.stderr or f"pgrep failed for {pattern}").strip())
            continue
        for line in result.stdout.splitlines():
            parts = line.split(maxsplit=1)
            if not parts or parts[0] == current_pid:
                continue
            if line not in lines:
                lines.append(line)
    return lines, errors


def load_tasks(factory: FactoryConfig, limit: int | None) -> list[dict[str, Any]]:
    tasks = read_jsonl(factory.task_file)
    if limit is not None:
        return tasks[:limit]
    return tasks


def verdict_path(factory: FactoryConfig, task_id: str) -> Path:
    return factory.artifacts_dir / task_id / "verdict.json"


def completed_verdict(factory: FactoryConfig, task_id: str) -> dict[str, Any] | None:
    return read_json(verdict_path(factory, task_id))


def count_statuses(factory: FactoryConfig, tasks: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for task in tasks:
        verdict = completed_verdict(factory, task["id"])
        if verdict:
            counts[verdict.get("status", "unknown")] += 1
    return counts


def lease_dir(factory: FactoryConfig, task_id: str) -> Path:
    return factory.artifacts_dir / ".leases" / task_id


def lease_is_stale(path: Path, stale_seconds: int) -> bool:
    claim = read_json(path / "lease.json") or {}
    started_at = claim.get("started_epoch")
    if isinstance(started_at, (int, float)):
        return time.time() - float(started_at) > stale_seconds
    return time.time() - path.stat().st_mtime > stale_seconds


def remove_stale_lease(path: Path, stale_seconds: int) -> bool:
    if not path.exists():
        return True
    if not lease_is_stale(path, stale_seconds):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def acquire_lease(
    factory: FactoryConfig,
    task_id: str,
    worker_id: str,
    command: list[str],
    stale_seconds: int,
) -> Path | None:
    path = lease_dir(factory, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not remove_stale_lease(path, stale_seconds):
        return None
    try:
        path.mkdir()
    except FileExistsError:
        return None
    write_json(path / "lease.json", {
        "command": command,
        "factory": factory.key,
        "pid": None,
        "started_at": utc_timestamp(),
        "started_epoch": time.time(),
        "task_id": task_id,
        "worker_id": worker_id,
    })
    return path


def update_lease_pid(path: Path, pid: int) -> None:
    claim = read_json(path / "lease.json") or {}
    claim["pid"] = pid
    write_json(path / "lease.json", claim)


def release_lease(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def task_has_active_lease(factory: FactoryConfig, task_id: str, stale_seconds: int) -> bool:
    path = lease_dir(factory, task_id)
    return path.exists() and not remove_stale_lease(path, stale_seconds)


def archive_partial_run(factory: FactoryConfig, task_id: str) -> Path | None:
    run_dir = factory.artifacts_dir / task_id
    if not run_dir.exists() or (run_dir / "verdict.json").exists():
        return None
    partials = factory.artifacts_dir / "_partials"
    partials.mkdir(parents=True, exist_ok=True)
    base = partials / f"{task_id}-{filesystem_timestamp()}"
    target = base
    suffix = 1
    while target.exists():
        suffix += 1
        target = Path(f"{base}-{suffix}")
    shutil.move(os.fspath(run_dir), os.fspath(target))
    return target


def build_command(
    factory: FactoryConfig,
    task: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    command = [
        sys.executable,
        os.fspath(factory.runner_path),
        "--task-id",
        task["id"],
        "--split",
        args.split,
        "--attempts",
        str(args.attempts),
        "--codex-timeout-seconds",
        str(args.codex_timeout_seconds),
        "--check-timeout-seconds",
        str(args.check_timeout_seconds),
    ]
    if factory.supports_service_tier and args.service_tier:
        command.extend(["--service-tier", args.service_tier])
    return command


def machine_resource_state(args: argparse.Namespace) -> tuple[bool, dict[str, Any]]:
    cpus = os.cpu_count() or 1
    max_load = args.max_load if args.max_load > 0 else cpus * 2.0
    try:
        load_1, load_5, load_15 = os.getloadavg()
    except OSError:
        load_1 = load_5 = load_15 = None
    state: dict[str, Any] = {
        "adaptive": not args.no_adaptive,
        "cpu_count": cpus,
        "load_1": load_1,
        "load_5": load_5,
        "load_15": load_15,
        "max_load": max_load,
        "memory_free_ratio": memory_free_ratio(),
        "min_memory_free_ratio": args.min_memory_free_ratio,
    }
    if args.no_adaptive:
        state["gate"] = "disabled"
        return True, state
    if load_1 is not None and load_1 > max_load:
        state["gate"] = "load"
        return False, state
    free_ratio = state["memory_free_ratio"]
    if free_ratio is not None and free_ratio < args.min_memory_free_ratio:
        state["gate"] = "memory"
        return False, state
    state["gate"] = "open"
    return True, state


def memory_free_ratio() -> float | None:
    try:
        total_result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        total_bytes = int(total_result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    try:
        vm_result = subprocess.run(
            ["vm_stat"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    page_size = 4096
    free_pages = 0
    speculative_pages = 0
    for line in vm_result.stdout.splitlines():
        if "page size of" in line:
            parts = line.replace(")", "").split()
            for index, part in enumerate(parts):
                if part == "of" and index + 1 < len(parts):
                    try:
                        page_size = int(parts[index + 1])
                    except ValueError:
                        pass
        elif line.startswith("Pages free:"):
            free_pages = int(line.split(":", 1)[1].strip().rstrip("."))
        elif line.startswith("Pages speculative:"):
            speculative_pages = int(line.split(":", 1)[1].strip().rstrip("."))
    if total_bytes <= 0:
        return None
    return round(((free_pages + speculative_pages) * page_size) / total_bytes, 4)


def task_is_runnable(
    factory: FactoryConfig,
    task: dict[str, Any],
    running_ids: set[tuple[str, str]],
    stale_seconds: int,
) -> bool:
    task_id = task["id"]
    if (factory.key, task_id) in running_ids:
        return False
    if completed_verdict(factory, task_id):
        return False
    if task_has_active_lease(factory, task_id, stale_seconds):
        return False
    return True


def next_task(
    factory: FactoryConfig,
    tasks: list[dict[str, Any]],
    running_ids: set[tuple[str, str]],
    stale_seconds: int,
) -> dict[str, Any] | None:
    for task in tasks:
        if task_is_runnable(factory, task, running_ids, stale_seconds):
            return task
    return None


def factory_done(factory: FactoryConfig, tasks: list[dict[str, Any]]) -> bool:
    if factory.stop_after_passes is not None:
        statuses = count_statuses(factory, tasks)
        if statuses["pass"] >= factory.stop_after_passes:
            return True
    return False


def choose_factory(
    factories: list[FactoryConfig],
    tasks_by_factory: dict[str, list[dict[str, Any]]],
    running: list[RunningTask],
    stale_seconds: int,
) -> FactoryConfig | None:
    running_ids = {(item.factory.key, item.task_id) for item in running}
    running_counts = Counter(item.factory.key for item in running)
    candidates: list[FactoryConfig] = []
    for factory in factories:
        if factory_done(factory, tasks_by_factory[factory.key]):
            continue
        if next_task(factory, tasks_by_factory[factory.key], running_ids, stale_seconds):
            candidates.append(factory)
    if not candidates:
        return None
    under_soft = [item for item in candidates if running_counts[item.key] < item.soft_cap]
    pool = under_soft or candidates
    return min(pool, key=lambda item: running_counts[item.key] / max(item.soft_cap, 1))


def launch_task(
    factory: FactoryConfig,
    task: dict[str, Any],
    args: argparse.Namespace,
    run_log_dir: Path,
) -> RunningTask | None:
    task_id = task["id"]
    command = build_command(factory, task, args)
    worker_id = f"{factory.key}-{task_id}-{os.getpid()}"
    lease = acquire_lease(factory, task_id, worker_id, command, args.lease_stale_seconds)
    if lease is None:
        return None
    archived = archive_partial_run(factory, task_id)
    if archived:
        append_jsonl(run_log_dir / "supervisor.jsonl", {
            "archived_partial_run": archived.as_posix(),
            "event": "partial_archived",
            "factory": factory.key,
            "task_id": task_id,
            "time": utc_timestamp(),
        })
    log_path = run_log_dir / "workers" / f"{factory.key}-{task_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    update_lease_pid(lease, process.pid)
    return RunningTask(
        factory=factory,
        task_id=task_id,
        process=process,
        command=command,
        lease_dir=lease,
        log_path=log_path,
        started_at=time.time(),
    )


def verdict_after_run(factory: FactoryConfig, task_id: str) -> dict[str, Any]:
    return completed_verdict(factory, task_id) or {
        "failed_checks": ["missing_verdict"],
        "status": "runner_error",
        "task_id": task_id,
    }


def is_browser_failure(verdict: dict[str, Any]) -> bool:
    if verdict.get("status") == "pass":
        return False
    failed = set(verdict.get("failed_checks", [])) | set(verdict.get("missing_required_checks", []))
    return bool(failed & BROWSER_CHECKS)


def print_progress(
    factories: list[FactoryConfig],
    tasks_by_factory: dict[str, list[dict[str, Any]]],
    running: list[RunningTask],
    resource_state: dict[str, Any],
    run_started_at: float,
) -> None:
    running_ids = [f"{item.factory.key}:{item.task_id}" for item in running]
    summary: dict[str, Any] = {
        "elapsed_seconds": round(time.time() - run_started_at, 1),
        "resource_gate": resource_state.get("gate"),
        "running": len(running),
        "running_tasks": running_ids,
        "time": utc_timestamp(),
    }
    for factory in factories:
        statuses = count_statuses(factory, tasks_by_factory[factory.key])
        summary[factory.key] = {
            "completed": sum(statuses.values()),
            "pass": statuses["pass"],
            "fail": statuses["fail"],
            "runner_error": statuses["runner_error"],
            "target_passes": factory.stop_after_passes,
            "total_tasks": len(tasks_by_factory[factory.key]),
        }
    print(json.dumps(summary, sort_keys=True), flush=True)


def terminate_running(running: list[RunningTask]) -> None:
    for item in running:
        if item.process.poll() is None:
            try:
                os.killpg(item.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.time() + 15
    for item in running:
        while item.process.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        if item.process.poll() is None:
            try:
                os.killpg(item.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        release_lease(item.lease_dir)


def run_dry_run(
    factories: list[FactoryConfig],
    tasks_by_factory: dict[str, list[dict[str, Any]]],
    args: argparse.Namespace,
) -> None:
    planned: list[dict[str, Any]] = []
    running_ids: set[tuple[str, str]] = set()
    planned_counts: Counter[str] = Counter()
    while len(planned) < args.max_agents:
        candidates: list[FactoryConfig] = []
        for item in factories:
            if factory_done(item, tasks_by_factory[item.key]):
                continue
            if next_task(item, tasks_by_factory[item.key], running_ids, args.lease_stale_seconds):
                candidates.append(item)
        if not candidates:
            break
        under_soft = [item for item in candidates if planned_counts[item.key] < item.soft_cap]
        pool = under_soft or candidates
        factory = min(pool, key=lambda item: planned_counts[item.key] / max(item.soft_cap, 1))
        if factory is None:
            break
        task = next_task(factory, tasks_by_factory[factory.key], running_ids, args.lease_stale_seconds)
        if task is None:
            break
        task_id = task["id"]
        running_ids.add((factory.key, task_id))
        planned_counts[factory.key] += 1
        planned.append({
            "command": build_command(factory, task, args),
            "factory": factory.key,
            "task_id": task_id,
            "would_archive_partial": (
                (factory.artifacts_dir / task_id).exists()
                and not (factory.artifacts_dir / task_id / "verdict.json").exists()
            ),
        })
    print(json.dumps({
        "dry_run": True,
        "max_agents": args.max_agents,
        "planned": planned,
        "planned_count": len(planned),
    }, indent=2, sort_keys=True))


def run_supervisor(
    factories: list[FactoryConfig],
    tasks_by_factory: dict[str, list[dict[str, Any]]],
    args: argparse.Namespace,
) -> None:
    existing, process_check_errors = active_single_lane_factories()
    if process_check_errors and not args.allow_existing_factories:
        raise SystemExit(
            "Refusing to start parallel supervisor because the process safety check failed:\n"
            + "\n".join(process_check_errors)
            + "\nRun this from a normal terminal after stopping old factories, or pass "
            "--allow-existing-factories if you accept the collision risk."
        )
    if existing and not args.allow_existing_factories:
        raise SystemExit(
            "Refusing to start parallel supervisor while single-lane factories are running:\n"
            + "\n".join(existing)
            + "\nStop those processes first, or pass --allow-existing-factories if you accept the collision risk."
        )

    run_log_dir = SUPERVISOR_RUNS_DIR / filesystem_timestamp()
    run_log_dir.mkdir(parents=True, exist_ok=True)
    append_jsonl(run_log_dir / "supervisor.jsonl", {
        "args": vars(args),
        "event": "supervisor_started",
        "factories": [factory.key for factory in factories],
        "time": utc_timestamp(),
    })

    running: list[RunningTask] = []
    recent_browser_failures: deque[float] = deque()
    stop_requested = False

    def handle_stop(signum: int, _: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        append_jsonl(run_log_dir / "supervisor.jsonl", {
            "event": "stop_requested",
            "signal": signum,
            "time": utc_timestamp(),
        })

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    last_progress_at = 0.0
    run_started_at = time.time()
    try:
        while True:
            for item in list(running):
                rc = item.process.poll()
                if rc is None:
                    continue
                running.remove(item)
                release_lease(item.lease_dir)
                verdict = verdict_after_run(item.factory, item.task_id)
                duration = round(time.time() - item.started_at, 3)
                event = {
                    "duration_seconds": duration,
                    "event": "task_finished",
                    "factory": item.factory.key,
                    "returncode": rc,
                    "status": verdict.get("status"),
                    "task_id": item.task_id,
                    "time": utc_timestamp(),
                    "worker_log": item.log_path.as_posix(),
                }
                append_jsonl(run_log_dir / "supervisor.jsonl", event)
                if is_browser_failure(verdict):
                    recent_browser_failures.append(time.time())

            while recent_browser_failures and time.time() - recent_browser_failures[0] > args.failure_window_seconds:
                recent_browser_failures.popleft()

            resource_ok, resource_state = machine_resource_state(args)
            if len(recent_browser_failures) >= args.failure_backoff_count:
                resource_state["gate"] = "browser_failure_backoff"
                resource_ok = False
                append_jsonl(run_log_dir / "supervisor.jsonl", {
                    "event": "browser_failure_backoff",
                    "failures": len(recent_browser_failures),
                    "time": utc_timestamp(),
                })
                recent_browser_failures.clear()

            if stop_requested:
                if running:
                    terminate_running(running)
                break

            launched = False
            while resource_ok and len(running) < args.max_agents:
                factory = choose_factory(factories, tasks_by_factory, running, args.lease_stale_seconds)
                if factory is None:
                    break
                running_ids = {(item.factory.key, item.task_id) for item in running}
                task = next_task(factory, tasks_by_factory[factory.key], running_ids, args.lease_stale_seconds)
                if task is None:
                    break
                item = launch_task(factory, task, args, run_log_dir)
                if item is None:
                    break
                running.append(item)
                launched = True
                append_jsonl(run_log_dir / "supervisor.jsonl", {
                    "command": item.command,
                    "event": "task_started",
                    "factory": factory.key,
                    "pid": item.process.pid,
                    "task_id": item.task_id,
                    "time": utc_timestamp(),
                    "worker_log": item.log_path.as_posix(),
                })

            all_done = all(factory_done(factory, tasks_by_factory[factory.key]) for factory in factories)
            no_more_tasks = choose_factory(factories, tasks_by_factory, running, args.lease_stale_seconds) is None
            if not running and (all_done or no_more_tasks):
                append_jsonl(run_log_dir / "supervisor.jsonl", {
                    "event": "supervisor_finished",
                    "reason": "targets_reached" if all_done else "no_remaining_tasks",
                    "time": utc_timestamp(),
                })
                break

            now = time.time()
            if launched or now - last_progress_at >= args.progress_seconds:
                print_progress(factories, tasks_by_factory, running, resource_state, run_started_at)
                last_progress_at = now
            time.sleep(args.sleep_seconds)
    finally:
        if running:
            terminate_running(running)


def make_factories(args: argparse.Namespace) -> list[FactoryConfig]:
    factories = [
        FactoryConfig(
            key="three",
            label="Three/R3F",
            task_file=THREE_TASKS_DIR / f"{args.split}_tasks.jsonl",
            artifacts_dir=THREE_ARTIFACTS_DIR,
            runner_path=PROJECT_ROOT / "scripts" / "run_codex_task.py",
            soft_cap=args.three_soft_cap,
            stop_after_passes=args.three_stop_after_passes,
            supports_service_tier=True,
        ),
        FactoryConfig(
            key="hyperframes",
            label="HyperFrames",
            task_file=HF_TASKS_DIR / f"{args.split}_tasks.jsonl",
            artifacts_dir=HF_ARTIFACTS_DIR,
            runner_path=PROJECT_ROOT / "domains" / "hyperframes" / "scripts" / "run_hf_task.py",
            soft_cap=args.hf_soft_cap,
            stop_after_passes=args.hf_stop_after_passes,
            supports_service_tier=True,
        ),
    ]
    if args.scope == "three":
        return [factories[0]]
    if args.scope == "hyperframes":
        return [factories[1]]
    return factories


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run data-factory tasks in bounded parallel batches")
    parser.add_argument("--scope", choices=["both", "three", "hyperframes"], default="both")
    parser.add_argument("--split", choices=["train", "eval"], default="train")
    parser.add_argument("--max-agents", type=int, default=10)
    parser.add_argument("--three-soft-cap", type=int, default=6)
    parser.add_argument("--hf-soft-cap", type=int, default=4)
    parser.add_argument("--three-stop-after-passes", type=int, default=None)
    parser.add_argument("--hf-stop-after-passes", type=int, default=None)
    parser.add_argument("--limit-per-factory", type=int, default=None)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--codex-timeout-seconds", type=int, default=900)
    parser.add_argument("--check-timeout-seconds", type=int, default=120)
    parser.add_argument("--service-tier", default="fast")
    parser.add_argument("--resume", action="store_true", help="Accepted for compatibility; completed verdicts are always skipped")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-existing-factories", action="store_true")
    parser.add_argument("--lease-stale-seconds", type=int, default=STALE_LEASE_SECONDS)
    parser.add_argument("--progress-seconds", type=float, default=30.0)
    parser.add_argument("--sleep-seconds", type=float, default=2.0)
    parser.add_argument("--no-adaptive", action="store_true")
    parser.add_argument("--max-load", type=float, default=0.0)
    parser.add_argument("--min-memory-free-ratio", type=float, default=0.03)
    parser.add_argument("--failure-backoff-count", type=int, default=3)
    parser.add_argument("--failure-window-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.max_agents < 1:
        raise SystemExit("--max-agents must be >= 1")
    if args.max_agents > 10:
        raise SystemExit("--max-agents is hard-capped at 10 for this local supervisor")
    return args


def main() -> None:
    args = parse_args()
    factories = make_factories(args)
    tasks_by_factory = {
        factory.key: load_tasks(factory, args.limit_per_factory)
        for factory in factories
    }
    if args.dry_run:
        run_dry_run(factories, tasks_by_factory, args)
        return
    run_supervisor(factories, tasks_by_factory, args)


if __name__ == "__main__":
    main()
