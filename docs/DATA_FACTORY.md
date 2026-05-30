# Local Codex Data Factory

This loop creates verified SFT examples for a Three.js / TSL / WebGPU / React
Three Fiber / Drei specialist model.

Each task follows the AutoResearch constraints:

- Codex may edit only `src/solution.tsx`.
- The app harness, tests, configs, and scorer are locked.
- The evaluator returns one scalar score plus detailed checks.
- Each attempt captures one desktop Playwright screenshot at
  `attempts/<n>/screenshots/desktop.png`; screenshot presence and dimensions are
  part of the scalar score.
- Full Codex traces are archived, but clean SFT data only uses passing final
  solutions.

## Dry Run

```bash
python3 scripts/run_codex_task.py --task-id train-r3f-scene-001 --split train --dry-run
```

## Run One Task

```bash
python3 scripts/run_codex_task.py --task-id train-r3f-scene-001 --split train
```

Artifacts are written to:

```text
artifacts/task-runs/<task_id>/
```

The accepted run stores its final screenshot path in `verdict.json` and keeps
all attempt screenshots under:

```text
artifacts/task-runs/<task_id>/attempts/<attempt>/screenshots/desktop.png
```

## Run A Batch

```bash
python3 scripts/run_data_factory.py --split train --limit 10 --resume
```

For unattended looping:

```bash
python3 scripts/run_data_factory.py --split train --resume --loop --stop-after-passes 300
```

## Build SFT Dataset

```bash
python3 scripts/make_sft_dataset.py
```

Outputs are written under gitignored `finetune/datasets/`.
