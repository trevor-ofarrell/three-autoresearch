# HyperFrames AutoResearch Factory

This domain is an isolated AutoResearch-style data factory for HyperFrames, HTML-in-Canvas, CanvasKit/Skia, WebGPU/TypeGPU, and deterministic HTML video composition tasks.

It intentionally does not share task IDs, task files, artifact roots, or dataset outputs with the Three.js factory.

## Layout

- `evals/template/`: copied into each per-task workspace.
- `evals/tasks/`: generated train/eval task banks.
- `scripts/generate_hf_tasks.py`: reproducible task-bank generator.
- `scripts/run_hf_task.py`: run one task in a fresh copied workspace.
- `scripts/run_hf_factory.py`: run many tasks with resume/loop support.
- `scripts/score_hf_task.py`: scalar scorer and semantic gates.
- `scripts/make_hf_sft_dataset.py`: clean SFT export from passing train runs.

Generated outputs are separate:

- `artifacts/hyperframes-task-runs/`
- `finetune/datasets-hyperframes/`
- `data/hyperframes/`

## Commands

```bash
python3 domains/hyperframes/scripts/generate_hf_tasks.py
python3 domains/hyperframes/scripts/run_hf_task.py --task-id hf-train-html-canvas-card-001 --split train --dry-run
python3 domains/hyperframes/scripts/run_hf_task.py --task-id hf-train-html-canvas-card-001 --split train --rerun
python3 domains/hyperframes/scripts/run_hf_factory.py --split train --resume --loop --stop-after-passes 300
python3 domains/hyperframes/scripts/make_hf_sft_dataset.py
```

The runner passes `service_tier="fast"` to `codex exec` by default. Override with `--service-tier ""` if needed.

## Task Bank

The v1 bank is generated as 300 train tasks plus 50 held-out eval tasks. The prompts and semantic gates are grounded in:

- The target app's HyperFrames rendering, timeline, HTML-in-Canvas, determinism, snapshot, asset, CanvasKit, and WebGPU validator code.
- WICG HTML-in-Canvas primitives: `layoutsubtree`, `drawElementImage`, `paint`, `requestPaint`, `texElementImage2D`, and `copyElementImageToTexture`.
- CanvasKit/Skia patterns for local WASM runtime loading, SkSurface flushing, text/path/shader/Skottie-style work, and WASM-backed object lifecycle.
- WebGPU/TypeGPU patterns for adapter/device fallback, typed shader/uniform intent, texture usage flags, queue submission, and completion fencing.
- GSAP timeline semantics for paused, seekable, label-driven HyperFrames composition state.

Every task requires automated checks, desktop screenshots, frame variation across seeked snapshots, deterministic source rules, clean replay, allowed-file enforcement, and task-specific semantic gates.

## Safety

Codex task attempts never run inside `/Users/trevor/Documents/New project 3`. The target app is used only as read-only source material and for local vendor assets copied into each task workspace.

By default, Codex may edit only `index.html`. Tasks can opt into generated local assets under `assets/generated/**`, but locked project files, vendor files, diagnostics, snapshots, renders, and runner files are rejected by the scorer.
