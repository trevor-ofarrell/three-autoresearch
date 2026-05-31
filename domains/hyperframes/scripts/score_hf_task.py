"""Score one HyperFrames AutoResearch task run."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from hf_factory_lib import allowed_file_clean, stable_hash, write_json


BASE_CHECK_POINTS = {
    "allowed_file_only": 100,
    "solution_changed": 100,
    "clean_replay": 100,
    "typecheck": 100,
    "lint": 100,
    "validate": 100,
    "snapshot": 100,
    "desktop_screenshot": 100,
    "no_console_errors": 100,
    "snapshot_nonblank": 100,
    "snapshot_frame_variation": 100,
    "snapshot_frames_retained": 100,
    "deterministic_source": 100,
}
FORBIDDEN_EDIT_PENALTY = 1000
NO_OP_PENALTY = 1000
CODEX_FAILURE_PENALTY = 1000
EXCESSIVE_SOURCE_PENALTY = 100
MIN_SCREENSHOT_BYTES = 1024
MIN_DESKTOP_SCREENSHOT_WIDTH = 1000
MIN_DESKTOP_SCREENSHOT_HEIGHT = 600
DEFAULT_MAX_INDEX_CHARS = 80_000


def latest_attempt_dir(run_dir: Path) -> Path:
    attempts = sorted(
        (path for path in (run_dir / "attempts").iterdir() if path.is_dir() and path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    if not attempts:
        raise FileNotFoundError(f"No attempts found in {run_dir / 'attempts'}")
    return attempts[-1]


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_index(run_dir: Path) -> str:
    workspace_index = run_dir / "workspace" / "index.html"
    final_index = run_dir / "final_files" / "index.html"
    path = workspace_index if workspace_index.exists() else final_index
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def png_dimensions(path: Path) -> tuple[int, int] | None:
    if not path.exists() or path.stat().st_size < MIN_SCREENSHOT_BYTES:
        return None
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def valid_desktop_screenshot(path: Path) -> bool:
    dimensions = png_dimensions(path)
    if dimensions is None:
        return False
    width, height = dimensions
    return width >= MIN_DESKTOP_SCREENSHOT_WIDTH and height >= MIN_DESKTOP_SCREENSHOT_HEIGHT


def snapshot_frames_retained(snapshot_report: dict[str, Any], attempt_dir: Path) -> bool:
    frames = snapshot_report.get("frames", [])
    if not isinstance(frames, list) or not frames:
        return False
    for frame in frames:
        if not isinstance(frame, dict) or not frame.get("path"):
            return False
        path = Path(frame["path"])
        if not path.is_absolute():
            path = attempt_dir / path
        if png_dimensions(path) is None:
            return False
    return True


def strip_comments(source: str) -> str:
    source = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"(^|[^:])//.*$", r"\1", source, flags=re.MULTILINE)
    return source


def deterministic_source_passed(source: str) -> bool:
    checked = strip_comments(source)
    forbidden = [
        r"\bDate\.now\s*\(",
        r"\bperformance\.now\s*\(",
        r"\bMath\.random\s*\(",
        r"\brequestAnimationFrame\s*\(",
        r"\bsetInterval\s*\(",
        r"\b(?:src|href|poster)\s*=\s*['\"]https?://",
        r"\burl\(\s*['\"]?https?://",
        r"\bfetch\s*\(\s*['\"]https?://",
    ]
    return all(re.search(pattern, checked, re.IGNORECASE | re.MULTILINE) is None for pattern in forbidden)


def semantic_check_passed(source: str, check: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    checked_source = strip_comments(source) if check.get("ignore_comments", True) else source
    haystack = checked_source if check.get("case_sensitive", True) else checked_source.lower()

    def normalize(value: str) -> str:
        return value if check.get("case_sensitive", True) else value.lower()

    for needle in check.get("all_of", []):
        if normalize(needle) not in haystack:
            failures.append(f"missing {needle!r}")

    for group in check.get("any_of", []):
        if not any(normalize(needle) in haystack for needle in group):
            failures.append(f"missing one of {group!r}")

    for needle in check.get("none_of", []):
        if normalize(needle) in haystack:
            failures.append(f"forbidden {needle!r}")

    flags = re.MULTILINE | re.DOTALL | (0 if check.get("case_sensitive", True) else re.IGNORECASE)
    for pattern in check.get("regex_all", []):
        if re.search(pattern, checked_source, flags) is None:
            failures.append(f"missing regex {pattern!r}")

    for group in check.get("regex_any", []):
        if not any(re.search(pattern, checked_source, flags) is not None for pattern in group):
            failures.append(f"missing one regex from {group!r}")

    for pattern in check.get("regex_none", []):
        if re.search(pattern, checked_source, flags) is not None:
            failures.append(f"forbidden regex {pattern!r}")

    for requirement in check.get("count_at_least", []):
        pattern = requirement["pattern"]
        minimum = int(requirement["count"])
        found = len(re.findall(pattern, checked_source, flags))
        if found < minimum:
            failures.append(f"regex {pattern!r} count {found} < {minimum}")

    return not failures, failures


def score_run(run_dir: Path, attempt_dir: Path | None = None) -> dict[str, Any]:
    attempt_dir = attempt_dir or latest_attempt_dir(run_dir)
    task = load_json(run_dir / "task.json", {})
    checks = load_json(attempt_dir / "checks.json", {})
    modified_files = load_json(attempt_dir / "modified_files.json", [])
    source = read_index(run_dir)
    baseline_hash_path = run_dir / "baseline_index_hash.txt"
    baseline_hash = baseline_hash_path.read_text(encoding="utf-8").strip() if baseline_hash_path.exists() else ""
    source_hash = stable_hash(source) if source else ""
    snapshot_report = load_json(attempt_dir / "diagnostics" / "snapshot-report.json", {})

    score = 0
    passed_checks: list[str] = []
    failed_checks: list[str] = []
    detail: dict[str, int] = {}

    def add_check(name: str, passed: bool, points: int) -> None:
        nonlocal score
        if passed:
            score += points
            passed_checks.append(name)
            detail[name] = points
        else:
            failed_checks.append(name)
            detail[name] = 0

    allowed_file_only = bool(modified_files) and all(allowed_file_clean(path, task) for path in modified_files)
    solution_changed = bool(source_hash and source_hash != baseline_hash)
    clean_replay = checks.get("_meta", {}).get("clean_replay") is True
    typecheck_passed = checks.get("typecheck", {}).get("returncode") == 0
    lint_passed = checks.get("lint", {}).get("returncode") == 0
    validate_passed = checks.get("validate", {}).get("returncode") == 0
    snapshot_passed = checks.get("snapshot", {}).get("returncode") == 0
    screenshot_path_text = checks.get("snapshot", {}).get("desktop_screenshot_path", "")
    screenshot_path = Path(screenshot_path_text) if screenshot_path_text else attempt_dir / "screenshots" / "desktop.png"
    no_console_errors = not snapshot_report.get("consoleErrors") and not snapshot_report.get("pageErrors")
    snapshot_nonblank = bool(snapshot_report.get("visibility", {}).get("visibleElements", 0) > 0)
    snapshot_frame_variation = int(snapshot_report.get("uniqueFrameHashes", 0) or 0) > 1
    retained_frames = snapshot_frames_retained(snapshot_report, attempt_dir)

    add_check("allowed_file_only", allowed_file_only, BASE_CHECK_POINTS["allowed_file_only"])
    add_check("solution_changed", solution_changed, BASE_CHECK_POINTS["solution_changed"])
    add_check("clean_replay", clean_replay, BASE_CHECK_POINTS["clean_replay"])
    add_check("typecheck", typecheck_passed, BASE_CHECK_POINTS["typecheck"])
    add_check("lint", lint_passed, BASE_CHECK_POINTS["lint"])
    add_check("validate", validate_passed, BASE_CHECK_POINTS["validate"])
    add_check("snapshot", snapshot_passed, BASE_CHECK_POINTS["snapshot"])
    add_check("desktop_screenshot", valid_desktop_screenshot(screenshot_path), BASE_CHECK_POINTS["desktop_screenshot"])
    add_check("no_console_errors", no_console_errors, BASE_CHECK_POINTS["no_console_errors"])
    add_check("snapshot_nonblank", snapshot_nonblank, BASE_CHECK_POINTS["snapshot_nonblank"])
    add_check("snapshot_frame_variation", snapshot_frame_variation, BASE_CHECK_POINTS["snapshot_frame_variation"])
    add_check("snapshot_frames_retained", retained_frames, BASE_CHECK_POINTS["snapshot_frames_retained"])
    add_check("deterministic_source", deterministic_source_passed(source), BASE_CHECK_POINTS["deterministic_source"])

    semantic_detail: dict[str, Any] = {}
    for check in task.get("semantic_checks", []):
        name = check["name"]
        points = int(check.get("points", 100))
        passed, failures = semantic_check_passed(source, check)
        add_check(name, passed, points)
        semantic_detail[name] = {
            "passed": passed,
            "failures": failures,
            "points": points if passed else 0,
        }

    if any(not allowed_file_clean(path, task) for path in modified_files):
        score -= FORBIDDEN_EDIT_PENALTY
        failed_checks.append("forbidden_file_edit")
        detail["forbidden_file_edit"] = -FORBIDDEN_EDIT_PENALTY

    codex_rc_path = attempt_dir / "codex_returncode.txt"
    codex_rc = codex_rc_path.read_text(encoding="utf-8").strip() if codex_rc_path.exists() else ""
    if codex_rc == "0":
        passed_checks.append("codex_success")
    else:
        score -= CODEX_FAILURE_PENALTY
        failed_checks.append("codex_success")
        detail["codex_success"] = -CODEX_FAILURE_PENALTY

    if not solution_changed:
        score -= NO_OP_PENALTY
        detail["solution_changed_penalty"] = -NO_OP_PENALTY

    max_chars = int(task.get("max_index_chars", DEFAULT_MAX_INDEX_CHARS))
    if len(source) <= max_chars:
        passed_checks.append("solution_size")
    else:
        score -= EXCESSIVE_SOURCE_PENALTY
        failed_checks.append("solution_size")
        detail["solution_size"] = -EXCESSIVE_SOURCE_PENALTY

    required_checks = set(task.get("required_checks", task.get("checks", [])))
    missing_required = sorted(check for check in required_checks if check not in passed_checks)
    accepted = score >= int(task.get("score_threshold", 0)) and not missing_required

    result = {
        "accepted": accepted,
        "score": score,
        "score_threshold": task.get("score_threshold", 0),
        "passed_checks": sorted(set(passed_checks)),
        "failed_checks": sorted(set(failed_checks)),
        "missing_required_checks": missing_required,
        "detail": detail,
        "semantic_detail": semantic_detail,
        "modified_files": modified_files,
        "screenshot_path": screenshot_path.as_posix(),
        "snapshot_report_path": (attempt_dir / "diagnostics" / "snapshot-report.json").as_posix(),
        "source_hash": source_hash,
    }
    write_json(attempt_dir / "score.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a HyperFrames task run")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--attempt-dir", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(score_run(args.run_dir, attempt_dir=args.attempt_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
