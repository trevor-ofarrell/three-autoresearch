"""Summarize Axolotl/Trainer outputs for one run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def find_trainer_state(root: Path) -> Path | None:
    candidates = sorted(root.rglob("trainer_state.json"), key=lambda path: len(path.parts))
    return candidates[-1] if candidates else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize training loss/eval loss from a run directory")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    trainer_state_path = find_trainer_state(args.run_dir)
    log_history = []
    if trainer_state_path:
        log_history = load_json(trainer_state_path).get("log_history", [])

    train_losses = [item["loss"] for item in log_history if "loss" in item]
    eval_losses = [item["eval_loss"] for item in log_history if "eval_loss" in item]
    checkpoints = sorted(path.as_posix() for path in args.run_dir.rglob("checkpoint-*") if path.is_dir())
    summary = {
        "run_dir": args.run_dir.as_posix(),
        "trainer_state_path": trainer_state_path.as_posix() if trainer_state_path else "",
        "train_loss_first": train_losses[0] if train_losses else None,
        "train_loss_last": train_losses[-1] if train_losses else None,
        "eval_loss_last": eval_losses[-1] if eval_losses else None,
        "checkpoint_count": len(checkpoints),
        "latest_checkpoint": checkpoints[-1] if checkpoints else "",
    }
    text = json.dumps(summary, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
