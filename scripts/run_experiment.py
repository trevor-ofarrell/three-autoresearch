"""Safe-ish runner for autoresearch training experiments.

The runner is intentionally conservative. It can dry-run locally on a Mac, but
real training still requires the upstream CUDA environment.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = PROJECT_ROOT / "results.tsv"
RUN_LOG = PROJECT_ROOT / "run.log"


SUMMARY_PATTERNS = {
    "val_bpb": re.compile(r"^val_bpb:\s+([0-9.]+)", re.MULTILINE),
    "peak_vram_mb": re.compile(r"^peak_vram_mb:\s+([0-9.]+)", re.MULTILINE),
}


def git(args: list[str], check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise SystemExit(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def current_branch() -> str:
    return git(["branch", "--show-current"])


def current_commit() -> str:
    return git(["rev-parse", "--short=7", "HEAD"])


def dirty_paths() -> list[str]:
    lines = git(["status", "--porcelain"], check=True).splitlines()
    paths: list[str] = []
    for line in lines:
        if not line:
            continue
        paths.append(line[3:])
    return paths


def ensure_autoresearch_branch(tag: str) -> None:
    branch = current_branch()
    expected = f"autoresearch/{tag}"
    if branch != expected:
        raise SystemExit(f"Refusing to run on {branch!r}; switch to {expected!r} first.")


def ensure_results_header() -> None:
    if RESULTS_PATH.exists():
        return
    RESULTS_PATH.write_text("commit\tval_bpb\tmemory_gb\tstatus\tdescription\n", encoding="utf-8")


def best_val_bpb() -> float | None:
    if not RESULTS_PATH.exists():
        return None
    best: float | None = None
    with RESULTS_PATH.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("status") != "keep":
                continue
            try:
                value = float(row["val_bpb"])
            except (KeyError, ValueError):
                continue
            best = value if best is None else min(best, value)
    return best


def parse_summary(log_text: str) -> tuple[float | None, float]:
    val_match = SUMMARY_PATTERNS["val_bpb"].search(log_text)
    mem_match = SUMMARY_PATTERNS["peak_vram_mb"].search(log_text)
    val_bpb = float(val_match.group(1)) if val_match else None
    memory_gb = float(mem_match.group(1)) / 1024 if mem_match else 0.0
    return val_bpb, memory_gb


def append_result(commit: str, val_bpb: float, memory_gb: float, status: str, description: str) -> None:
    ensure_results_header()
    with RESULTS_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow([commit, f"{val_bpb:.6f}", f"{memory_gb:.1f}", status, description])


def commit_train_change(description: str) -> tuple[str, bool]:
    changed = git(["status", "--porcelain", "--", "train.py"]).strip()
    if not changed:
        return current_commit(), False
    git(["add", "train.py"])
    git(["commit", "-m", f"experiment: {description}"])
    return current_commit(), True


def run_command(command: str, timeout_seconds: int) -> int:
    argv = shlex.split(command)
    with RUN_LOG.open("w", encoding="utf-8") as log:
        process = subprocess.run(
            argv,
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
    return process.returncode


def run_domain_evals() -> bool:
    commands = [
        ["npm", "--prefix", "evals/app-template", "run", "typecheck"],
        ["npm", "--prefix", "evals/app-template", "run", "build"],
        ["npm", "--prefix", "evals/app-template", "run", "test"],
    ]
    for command in commands:
        print("+", " ".join(command))
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if result.returncode != 0:
            return False
    return True


def reset_failed_commit(start_commit: str) -> None:
    branch = current_branch()
    if not branch.startswith("autoresearch/"):
        raise SystemExit(f"Refusing to reset branch {branch!r}")
    git(["reset", "--hard", start_commit])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one autoresearch experiment")
    parser.add_argument("--tag", required=True, help="Current branch suffix, e.g. may29-gpu0")
    parser.add_argument("--description", default="baseline", help="Short TSV description")
    parser.add_argument("--command", default="uv run train.py", help="Training command")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--baseline", action="store_true", help="Do not require train.py changes")
    parser.add_argument("--with-domain-evals", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start_commit = current_commit()

    if args.dry_run:
        print(f"branch={current_branch()}")
        print(f"expected_branch=autoresearch/{args.tag}")
        print(f"start_commit={start_commit}")
        print(f"command={args.command}")
        print("dry_run=1")
        return

    ensure_autoresearch_branch(args.tag)
    dirty = dirty_paths()
    allowed_dirty = {"train.py", "results.tsv", "run.log"}
    unexpected_dirty = [path for path in dirty if path not in allowed_dirty]
    if unexpected_dirty:
        raise SystemExit(f"Unexpected dirty paths: {unexpected_dirty}")

    ensure_results_header()

    commit, created_commit = commit_train_change(args.description)
    if not args.baseline and not created_commit:
        raise SystemExit("No train.py changes found. Use --baseline for unchanged baseline runs.")

    rc = run_command(args.command, args.timeout_seconds)
    log_text = RUN_LOG.read_text(encoding="utf-8", errors="replace") if RUN_LOG.exists() else ""
    val_bpb, memory_gb = parse_summary(log_text)
    prior_best = best_val_bpb()

    status = "crash"
    result_bpb = 0.0
    if rc == 0 and val_bpb is not None:
        result_bpb = val_bpb
        status = "keep" if prior_best is None or val_bpb < prior_best else "discard"

    if status == "keep" and args.with_domain_evals and not run_domain_evals():
        status = "discard"

    append_result(commit, result_bpb, memory_gb, status, args.description)
    print(f"status={status} val_bpb={result_bpb:.6f} memory_gb={memory_gb:.1f}")

    if status != "keep":
        reset_failed_commit(start_commit)


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        append_result(current_commit(), 0.0, 0.0, "crash", "timeout")
        raise SystemExit("Experiment timed out")
