# MedLink-IE v2

MedLink-IE is a deterministic, offline medical information-extraction framework
for Vietnamese clinical documents. It preserves raw source text and computes all
entity positions from that source. It is a project framework, not an official
competition scorer or a claim of competition performance.

## Problem and architecture

The pipeline produces entities with exact raw-text spans, type, assertions, and
eligible terminology candidates. Its deterministic order is:

```text
raw bytes → lossless UTF-8 loader → structure/text views → proposals
→ grounding → fusion/boundary resolution → type/assertion → validation → JSON
```

Grounding happens before type and assertion classification. Submission JSON
contains only final entities; operational traces, per-entity decisions, timing,
memory, and failure categories are written separately. No normal operational log
contains raw clinical text.

The source-of-truth order is `specs/TASK_CONTRACT.md`,
`specs/ANNOTATION_GUIDE.md`, `specs/terminology_manifest.yaml`, the framework,
tests, then source code.

## Supported environment

The supported deterministic baseline is Python 3.11+ with the exact runtime
dependency in [requirements.lock](requirements.lock): PyYAML 6.0.3. Development
uses the optional tools declared in `pyproject.toml` (pytest, ruff, mypy). The
latest recorded clean-directory drill used CPython 3.13.12 on Windows 11 AMD64,
with 20 logical CPUs and no CUDA device. The documented container base is
`python:3.11-slim`.

CPU-only execution is supported and is the expected smoke-test mode. GPU is
optional: the preflight report records CUDA availability when PyTorch is locally
installed. The shipped XLM-R artifact declares 277,461,515 parameters, below the
hard 9B limit. No model adapter may silently change model, device, precision, or
download an artifact.

For a clean CPU image, use [Dockerfile](Dockerfile). It contains code and locked
runtime dependencies only; mount data and artifacts at runtime. Runtime examples
use `--network none` and set Hugging Face offline environment flags.

## Repository layout

- `src/medlink_ie/` — deterministic pipeline, validation, terminology, CLI.
- `configs/` — component and local model configuration.
- `specs/` — task contracts, terminology and artifact inventories.
- `data/terminology/` — local frozen terminology archives; never fetched during inference.
- `artifacts/` — local models, prepared tables, run reports, and traces.
- `examples/smoke/` — deterministic one-file smoke input and expected output hash.
- `scripts/` — smoke, full inference, training adapter, and reproduction entry points.
- `tests/` — unit, integration, and framework/golden checks.

## Artifacts, provenance, and secrets

`specs/artifact_inventory.yaml` is the local artifact inventory. Each entry has a
relative path, byte size, SHA-256, license/usage basis, required flag, and model
parameter count where applicable. The inventory currently requires WHO ICD-10
2019, RxNorm Current Prescribable Content dated 2026-07-06, and the local
framework-v1 medication aliases. The trained XLM-R artifact is optional.

Place archives only at their declared paths or change a copied inventory/config
deliberately. Do not put tokens, passwords, API keys, or credentials in configs:
the loader rejects secret-like keys and the container excludes `.env`.

Verify the local inventory without network access:

```powershell
medlink-ie offline-preflight --config examples/smoke/config.yaml
```

This writes `offline_preflight.json` and `environment.json` under the configured
run directory. Missing required files report the declared artifact name and a
local remediation; they are never downloaded automatically.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install -e .
python -m pip install -e ".[dev]"
```

Check strict configuration parsing before running work:

```powershell
medlink-ie validate-config --config examples/smoke/config.yaml
```

All relative paths resolve from the config file, not from the shell working
directory. The resolved config is stored in run artifacts with secrets excluded.

## Terminology preparation

Terminology preparation accepts only frozen local archives whose checksums match
the terminology manifest. It writes canonical concept/alias tables and a
checksummed preparation manifest.

```powershell
medlink-ie prepare-terminology --config path/to/config.yaml
```

The config must include `terminology.manifest` and may set
`terminology.output_dir`. This command does not contact WHO, NLM, Hugging Face,
or another service.

## Training

Training is adapter-based and local-only. A training adapter must return a
`TrainingArtifact`; its model checksum, split provenance, seed, interface version,
and parameter count are validated before it can be used.

```powershell
python scripts/train_encoder_span_type.py `
  --adapter package.module:train `
  --model-config configs/encoder_xlm_roberta_base.yaml `
  --training-config path/to/training.yaml `
  --dataset path/to/local_dataset `
  --output artifacts/runs/my_run/training_artifact.json
```

Expected artifacts are a local model file, tokenizer/config files where required,
and a non-overwritten training artifact JSON containing model name, SHA-256,
parameter count, and seed. The CLI `train` command intentionally returns an
unsupported result until a concrete adapter is registered; it will not choose a
fallback model.

## Inference, evaluation, packaging

Run one configured file or `.txt` directory:

```powershell
medlink-ie infer --config path/to/inference.yaml
```

`batch.batch_size`, `batch.resume_policy`, `batch.timeout_seconds`, and
`batch.capture_memory` control deterministic batching. A run writes submission
JSON, separate per-entity traces, `run_manifest.json`, and `infer_summary.json`.
Only an output paired with a completed matching trace checksum can be resumed.

Score two local entity JSON arrays with the documented local framework scorer:

```powershell
medlink-ie evaluate --config path/to/evaluation.yaml
```

Package and validate a directory submission:

```powershell
medlink-ie package --config path/to/inference.yaml
medlink-ie validate-submit --config path/to/inference.yaml
```

The validator checks zip layout, count, JSON schema, enums, duplicate objects,
and raw-slice semantics. It does not claim organizer-scorer equivalence.

## Profiles, feature flags, and offline mode

Profiles are `mvp_deterministic`, `competition_full`, and `fast_fallback` (with
short aliases `mvp`, `competition`, and `fast`). Feature flags are `llm`, `dense`,
`reranker`, `ontology`, and `fuzzy_grounding`. Incompatible combinations fail at
config load: reranking requires dense retrieval, ontology requires reranking,
MVP forbids model/dense features, and fast fallback forbids all optional flags.

`offline: true` is mandatory. The final gate checks this policy and confirms that
the artifact preflight recorded `network_accessed: false`. A competition profile
must therefore use only verified local artifacts; external model/terminology
calls are not an accepted fallback.

## Smoke, full reproduction, and resource estimates

Run the one-command smoke test:

```powershell
./scripts/smoke_infer.ps1
```

It runs preflight and inference, then compares the generated submission bytes
against the versioned expected SHA-256. Run a full configured inference with:

```powershell
./scripts/full_infer.ps1 -Config path/to/inference.yaml
```

For a clean copied workspace or an offline container drill:

```powershell
./scripts/reproduce.ps1 -Mode clean-dir
./scripts/reproduce.ps1 -Mode container
```

The smoke baseline has no active model and normally needs only Python process
memory plus one document. Terminology preparation needs disk space for roughly
75 MB of declared source archives and additional canonical tables. CPU/GPU model
memory and latency depend on the verified local adapter; record them from the run
manifest rather than assuming a benchmark number.

## Versioned evaluation evidence

The only checked-in benchmark report is
`artifacts/reports/provisional_synthetic_v1_seed17_epoch1/benchmark.json`. It is
explicitly `provisional_synthetic_only`, with one fold-seed run and dev/test
exact-span F1 of 0.0 (precision 1.0, recall 0.0). These values are not competition
results and must not be used as a performance claim. No official scorer or
competition benchmark result is present in the repository.

## Final submission-readiness gate

Run the complete local gate before packaging a submission:

```powershell
medlink-ie final-gate --config path/to/inference.yaml --recorded-commit (git rev-parse HEAD)
```

The gate writes `final_gate.json` and checks: clean git status or the supplied
HEAD commit; strict config; required source/data/docs; artifact checksums; ≤9B
model declarations; offline policy; tests; smoke inference; smoke output JSON and
expected hash; and finalized/complete run manifest. A dirty tree without a
recorded matching commit fails.

## Troubleshooting and limitations

- **Missing/checksum mismatch** — restore the exact local artifact named by
  `offline_preflight.json`; do not download during inference.
- **Config rejection** — remove unknown/secret-like keys and correct incompatible
  profile/feature flags; inspect `resolved_config.json`.
- **Resume does not occur** — the output or trace checksum/status is invalid;
  rerun with `reuse_valid` to recompute it safely.
- **Timeout/OOM** — the sample is reported in `run_manifest.json` as `timeout` or
  `oom`; no partial submission object is accepted. Synchronous model adapters are
  responsible for preemptive cancellation.
- **Docker unavailable** — start Docker Desktop’s Linux daemon, then use the
  container reproduction mode. The clean-directory mode remains local-only.

Position indexing and several scorer/schema details remain framework-v1 project
assumptions until organizer material is supplied. WHO and NLM terminology remain
subject to their declared licenses; the project-local alias artifact and model
license notes are in the inventory. Do not treat this README, local scorer, or
synthetic benchmark as organizer confirmation.
