# Three/WebGPU Autoresearch Runbook

This repository extends upstream `karpathy/autoresearch` into a domain research
harness for Three.js, Three.js Shading Language, WebGPU, React Three Fiber, and
Drei.

## Local Mac Setup

The local machine is for corpus work, tokenizer prep, eval harness development,
and runner dry-runs.

```bash
python3 scripts/create_smoke_corpus.py
python3 scripts/run_experiment.py --tag smoke --dry-run
```

The upstream lockfile pins CUDA PyTorch, so `uv sync` does not install on Apple
Silicon macOS. Use system Python for dependency-light corpus commands, and run
`uv sync` / `uv run prepare.py` / `uv run train.py` on the CUDA host unless a
Mac-specific dependency profile is added later.

## Corpus Pipeline

The registry is `data/sources.yaml`. It is JSON-formatted YAML so it can be read
without an extra parser dependency.

```bash
python3 scripts/corpus_sync.py --registry data/sources.yaml --only three,drei,react-three-fiber
python3 scripts/corpus_normalize.py --registry data/sources.yaml
python3 scripts/corpus_shard.py --input data/normalized/docs.jsonl --out data/shards --format jsonl
uv run prepare.py
```

Large corpus artifacts are written under `data/raw`, `data/normalized`, and
`data/shards`; all are gitignored. Shards default to parquet on the CUDA host;
use `--format jsonl` for dependency-light local smoke checks. Every normalized document keeps provenance:
source id, URL/path, package revision, license note, allowed use, topic tags,
and content hash.

## Domain Eval Harness

The first eval target is buildable generated apps, not question answering.

```bash
npm --prefix evals/app-template install
npm --prefix evals/app-template run typecheck
npm --prefix evals/app-template run build
npm --prefix evals/app-template run test
```

The template verifies strict TypeScript, Vite bundling, no browser/page errors,
nonblank WebGL canvas pixels, and a desktop screenshot captured from the
Playwright run.

## Local Codex Data Factory

Use `docs/DATA_FACTORY.md` for the AutoResearch-aligned local data loop. Each
task gives Codex one editable file, `src/solution.tsx`, and the locked scorer
decides whether the resulting app becomes clean SFT data.

## CUDA Training Loop

Real autoresearch runs happen later on a cloud NVIDIA/CUDA host.

```bash
git checkout -b autoresearch/<tag>
uv sync
uv run prepare.py
uv run scripts/run_experiment.py --tag <tag> --baseline --description baseline
```

After the baseline, an agent edits only `train.py`, then the runner commits the
experiment, runs `uv run train.py`, parses `val_bpb` and `peak_vram_mb`, writes
`results.tsv`, and keeps or resets the commit. The runner refuses destructive
reset behavior unless the current branch is `autoresearch/<tag>`.

## Agent Rules

- Human-maintained infrastructure: `prepare.py`, `data/sources.yaml`, `scripts`,
  `evals`, and this runbook.
- Agent experiment surface: `train.py` only.
- Primary metric: lower `val_bpb`.
- Secondary gate: domain evals must keep passing when `--with-domain-evals` is
  used.
- Never redistribute community-source corpus artifacts without reviewing the
  source terms.
