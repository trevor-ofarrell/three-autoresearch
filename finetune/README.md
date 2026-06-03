# Fine-Tuning Artifacts

Generated SFT and rejected-run datasets are derived from local task-run
artifacts and are intentionally gitignored.

## Export Commands

```bash
python3 scripts/make_sft_dataset.py
python3 domains/hyperframes/scripts/make_hf_sft_dataset.py
```

Outputs:

- `finetune/datasets/sft/` for Three/R3F/WebGPU/Drei records.
- `finetune/datasets-hyperframes/sft/` for HyperFrames records.
- `finetune/datasets-combined/sft/` for the mixed specialist dataset.

Current clean combined split:

- train: 520 records
- valid: 30 records
- schema: chat `messages` with `system`, `user`, `assistant`
- raw Codex transcripts: archived under `artifacts/**/codex.jsonl`, not embedded

## Upload Bundle

The current upload-ready bundle is:

```bash
artifacts/training-bundles/sft-datasets-20260603.tar.gz
```

It contains the per-domain SFT datasets, the combined SFT dataset, rejected-run
metadata, and both held-out eval task banks.

## Qwen3.6-27B Training Path

The first serious run uses `Qwen/Qwen3.6-27B` only. There are no fallback
models, teacher models, reference models, or model-judge graders in v1. Codex is
the operator; pass/fail grading comes from the locked Python, Playwright, and
HyperFrames scorers.

Configs:

- `finetune/configs/qwen3_6_27b_smoke.yml`: 50-step QLoRA smoke.
- `finetune/configs/qwen3_6_27b_baseline.yml`: first full QLoRA SFT baseline.
- `finetune/configs/qwen3_6_27b_experiment_template.yml`: template for the
  later 100-experiment sweep.

Pre-training audits:

```bash
python3 finetune/scripts/inspect_chat_template.py \
  --model Qwen/Qwen3.6-27B \
  --dataset finetune/datasets-combined/sft/train.jsonl

python3 finetune/scripts/verify_label_masking.py \
  --model Qwen/Qwen3.6-27B \
  --dataset finetune/datasets-combined/sft/train.jsonl \
  --limit 20
```

Smoke and baseline:

```bash
axolotl train finetune/configs/qwen3_6_27b_smoke.yml

python3 finetune/scripts/generate_with_adapter.py \
  --base-model Qwen/Qwen3.6-27B \
  --adapter /workspace/three-autoresearch-training/outputs/qwen36-smoke/checkpoint-best

axolotl train finetune/configs/qwen3_6_27b_baseline.yml
```

Locked held-out evals can run against either a local Transformers load or an
OpenAI-compatible endpoint such as vLLM:

```bash
python3 finetune/scripts/run_model_evals.py \
  --model Qwen/Qwen3.6-27B \
  --scope both \
  --split eval \
  --out artifacts/model-evals/qwen36-27b-base

python3 finetune/scripts/run_model_evals.py \
  --model qwen36-threehf \
  --model-endpoint http://127.0.0.1:8000/v1 \
  --scope both \
  --split eval \
  --out artifacts/model-evals/qwen36-27b-baseline
```

The model-eval runner writes raw model responses, extracted editable files,
diffs, checks, scalar scores, screenshots, HyperFrames snapshot frames, per-task
verdicts, and an aggregate `summary.json`. It writes only the allowed target file
inside each copied eval workspace: `src/solution.tsx` for Three tasks and
`index.html` for HyperFrames tasks.
