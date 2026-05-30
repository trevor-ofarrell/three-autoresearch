"""Score one local task run with a scalar AutoResearch-style metric."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from task_factory_lib import ALLOWED_FILE, allowed_file_clean, stable_hash, write_json


BASE_CHECK_POINTS = {
    "clean_replay": 100,
    "typecheck": 100,
    "build": 100,
    "playwright": 100,
    "no_console_errors": 100,
    "canvas_nonblank": 100,
    "desktop_screenshot": 100,
}

BONUS_POINTS = {
    "static_webgpu_guard": 100,
    "static_tsl_imports": 100,
    "drei_usage": 75,
    "asset_handling": 75,
    "animation": 50,
}

FORBIDDEN_EDIT_PENALTY = 1000
CODEX_FAILURE_PENALTY = 1000
NO_OP_SOLUTION_PENALTY = 1000
EXCESSIVE_CODE_PENALTY = 100
DEFAULT_MAX_SOLUTION_CHARS = 20_000
MIN_SCREENSHOT_BYTES = 1024
MIN_DESKTOP_SCREENSHOT_WIDTH = 1000
MIN_DESKTOP_SCREENSHOT_HEIGHT = 600


def latest_attempt_dir(run_dir: Path) -> Path:
    attempts_dir = run_dir / "attempts"
    attempts = sorted(
        (path for path in attempts_dir.iterdir() if path.is_dir() and path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    if not attempts:
        raise FileNotFoundError(f"No attempts found in {attempts_dir}")
    return attempts[-1]


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def png_dimensions(path: Path) -> tuple[int, int] | None:
    if not path.exists() or path.stat().st_size < MIN_SCREENSHOT_BYTES:
        return None
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return width, height


def valid_desktop_screenshot(path: Path) -> bool:
    dimensions = png_dimensions(path)
    if dimensions is None:
        return False
    width, height = dimensions
    return width >= MIN_DESKTOP_SCREENSHOT_WIDTH and height >= MIN_DESKTOP_SCREENSHOT_HEIGHT


def read_solution(run_dir: Path) -> str:
    workspace_solution = run_dir / "workspace" / ALLOWED_FILE
    final_solution = run_dir / "final_files" / ALLOWED_FILE
    path = workspace_solution if workspace_solution.exists() else final_solution
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def has_webgpu_guard(source: str) -> bool:
    lowered = source.lower()
    return "navigator.gpu" in lowered and ("fallback" in lowered or "webgl" in lowered)


def has_tsl_imports(source: str) -> bool:
    return "three/tsl" in source or "three/webgpu" in source or "Fn(" in source or "uniform(" in source


def has_drei_usage(source: str) -> bool:
    helpers = [
        "@react-three/drei",
        "OrbitControls",
        "CameraControls",
        "Environment",
        "Float",
        "Html",
        "Bounds",
        "ContactShadows",
        "useGLTF",
        "useTexture",
    ]
    return any(helper in source for helper in helpers)


def has_asset_handling(source: str) -> bool:
    helpers = ["useGLTF", "useTexture", "TextureLoader", "GLTFLoader", "Suspense", "Preload"]
    return any(helper in source for helper in helpers)


def has_animation(source: str) -> bool:
    return "useFrame" in source or "requestAnimationFrame" in source or ".rotation" in source


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

    flags = re.MULTILINE | (0 if check.get("case_sensitive", True) else re.IGNORECASE)
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


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"(^|[^:])//.*$", r"\1", source, flags=re.MULTILINE)
    return source


def score_run(run_dir: Path, attempt_dir: Path | None = None) -> dict[str, Any]:
    attempt_dir = attempt_dir or latest_attempt_dir(run_dir)
    task = load_json(run_dir / "task.json", {})
    checks = load_json(attempt_dir / "checks.json", {})
    modified_files = load_json(attempt_dir / "modified_files.json", [])
    source = read_solution(run_dir)
    source_hash = stable_hash(source) if source else ""

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

    clean_replay_passed = checks.get("_meta", {}).get("clean_replay") is True
    typecheck_passed = checks.get("typecheck", {}).get("returncode") == 0
    build_passed = checks.get("build", {}).get("returncode") == 0
    playwright_passed = checks.get("playwright", {}).get("returncode") == 0
    screenshot_path_text = checks.get("playwright", {}).get("screenshot_path", "")
    screenshot_path = Path(screenshot_path_text) if screenshot_path_text else attempt_dir / "screenshots" / "desktop.png"
    desktop_screenshot_passed = valid_desktop_screenshot(screenshot_path)
    add_check("clean_replay", clean_replay_passed, BASE_CHECK_POINTS["clean_replay"])
    add_check("typecheck", typecheck_passed, BASE_CHECK_POINTS["typecheck"])
    add_check("build", build_passed, BASE_CHECK_POINTS["build"])
    add_check("playwright", playwright_passed, BASE_CHECK_POINTS["playwright"])
    add_check("no_console_errors", playwright_passed, BASE_CHECK_POINTS["no_console_errors"])
    add_check("canvas_nonblank", playwright_passed, BASE_CHECK_POINTS["canvas_nonblank"])
    add_check("desktop_screenshot", desktop_screenshot_passed, BASE_CHECK_POINTS["desktop_screenshot"])

    semantic_detail: dict[str, Any] = {}
    semantic_checks = task.get("semantic_checks", [])
    if semantic_checks:
        for check in semantic_checks:
            name = check["name"]
            points = int(check.get("points", 100))
            passed, failures = semantic_check_passed(source, check)
            add_check(name, passed, points)
            semantic_detail[name] = {
                "passed": passed,
                "failures": failures,
                "points": points if passed else 0,
            }
    else:
        task_checks = set(task.get("checks", []))
        topics = set(task.get("topics", []))
        if "static_webgpu_guard" in task_checks or "webgpu" in topics:
            add_check("static_webgpu_guard", has_webgpu_guard(source), BONUS_POINTS["static_webgpu_guard"])
        if "static_tsl_imports" in task_checks or "tsl" in topics:
            add_check("static_tsl_imports", has_tsl_imports(source), BONUS_POINTS["static_tsl_imports"])
        if "drei_usage" in task_checks or "drei" in topics:
            add_check("drei_usage", has_drei_usage(source), BONUS_POINTS["drei_usage"])
        if "asset_handling" in task_checks or "assets" in topics:
            add_check("asset_handling", has_asset_handling(source), BONUS_POINTS["asset_handling"])
        if "animation" in task_checks or "animation" in topics:
            add_check("animation", has_animation(source), BONUS_POINTS["animation"])

    penalties: dict[str, int] = {}
    codex_returncode_path = attempt_dir / "codex_returncode.txt"
    if codex_returncode_path.exists():
        try:
            codex_returncode = int(codex_returncode_path.read_text(encoding="utf-8").strip())
        except ValueError:
            codex_returncode = 1
        if codex_returncode != 0:
            penalties["codex_failure"] = CODEX_FAILURE_PENALTY
            score -= CODEX_FAILURE_PENALTY
            failed_checks.append("codex_success")
        else:
            passed_checks.append("codex_success")

    baseline_hash_path = run_dir / "baseline_solution_hash.txt"
    if baseline_hash_path.exists() and source_hash:
        baseline_hash = baseline_hash_path.read_text(encoding="utf-8").strip()
        if source_hash == baseline_hash:
            penalties["no_op_solution"] = NO_OP_SOLUTION_PENALTY
            score -= NO_OP_SOLUTION_PENALTY
            failed_checks.append("solution_changed")
        else:
            passed_checks.append("solution_changed")

    forbidden_edits = [path for path in modified_files if not allowed_file_clean(path)]
    if forbidden_edits:
        penalties["forbidden_file_edits"] = FORBIDDEN_EDIT_PENALTY
        score -= FORBIDDEN_EDIT_PENALTY
        failed_checks.append("allowed_file_only")
    else:
        passed_checks.append("allowed_file_only")

    max_chars = int(task.get("max_solution_chars", DEFAULT_MAX_SOLUTION_CHARS))
    if len(source) > max_chars:
        penalties["excessive_code_size"] = EXCESSIVE_CODE_PENALTY
        score -= EXCESSIVE_CODE_PENALTY
        failed_checks.append("solution_size")
    else:
        passed_checks.append("solution_size")

    default_required = {
        "clean_replay",
        "typecheck",
        "build",
        "playwright",
        "no_console_errors",
        "canvas_nonblank",
        "desktop_screenshot",
        "codex_success",
        "solution_changed",
        "allowed_file_only",
        "solution_size",
    }
    required_checks = default_required | set(task.get("required_checks", []))
    threshold = int(task.get("score_threshold", sum(BASE_CHECK_POINTS.values())))
    passed_set = set(passed_checks)
    missing_required = sorted(required_checks - passed_set)
    result = {
        "task_id": task.get("id", ""),
        "score": score,
        "score_threshold": threshold,
        "accepted": score >= threshold and not forbidden_edits and not missing_required,
        "passed_checks": sorted(set(passed_checks)),
        "failed_checks": sorted(set(failed_checks)),
        "detail": detail,
        "penalties": penalties,
        "semantic_detail": semantic_detail,
        "missing_required_checks": missing_required,
        "modified_files": modified_files,
        "screenshot_path": screenshot_path.as_posix(),
        "solution_hash": source_hash,
        "solution_chars": len(source),
        "attempt_dir": attempt_dir.as_posix(),
    }
    write_json(attempt_dir / "score.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a task run directory")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--attempt", type=int, default=None)
    args = parser.parse_args()

    attempt_dir = None
    if args.attempt is not None:
        attempt_dir = args.run_dir / "attempts" / str(args.attempt)
    result = score_run(args.run_dir, attempt_dir=attempt_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
