"""Run an Axolotl QLoRA config and record experiment metadata."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from qwen36_common import PROJECT_ROOT, stable_hash, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one QLoRA experiment with Axolotl")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out-root", type=Path, default=PROJECT_ROOT / "artifacts" / "training-experiments")
    parser.add_argument("--timeout-seconds", type=int, default=0, help="0 means no timeout")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config_text = args.config.read_text(encoding="utf-8")
    run_dir = args.out_root / args.name
    command = ["axolotl", "train", args.config.as_posix()]
    metadata = {
        "name": args.name,
        "config": args.config.as_posix(),
        "config_hash": stable_hash(config_text),
        "command": command,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if args.dry_run:
        print(json.dumps({**metadata, "run_dir": run_dir.as_posix(), "dry_run": True}, indent=2, sort_keys=True))
        return

    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "metadata.started.json", metadata)
    started = time.time()
    with (run_dir / "axolotl.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=args.timeout_seconds or None,
            check=False,
        )
    finished = {
        **metadata,
        "returncode": result.returncode,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.time() - started, 3),
        "log_path": (run_dir / "axolotl.log").as_posix(),
    }
    write_json(run_dir / "metadata.finished.json", finished)
    print(json.dumps(finished, indent=2, sort_keys=True))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
