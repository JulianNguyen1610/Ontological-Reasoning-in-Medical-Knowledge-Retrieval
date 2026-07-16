# MedLink-IE v2

MedLink-IE is a deterministic, offline-capable framework for extracting,
normalizing, asserting, and linking medical entities in Vietnamese clinical text.

## Source of truth

Read these documents in order before changing the pipeline:

1. `specs/TASK_CONTRACT.md`
2. `specs/ANNOTATION_GUIDE.md`
3. `specs/terminology_manifest.yaml`
4. `docs/MedLink-IE_v2_Framework.md`
5. `tests/`
6. Current source code

## Layout

- `src/medlink_ie/`: new modular MedLink-IE implementation.
- `configs/`: runtime and threshold configuration.
- `specs/`: task, annotation, and terminology contracts.
- `data/`: current datasets plus `raw/`, `terminology/`, `synthetic/`, and `gold/` partitions.
- `tests/`: existing tests plus unit, integration, golden, and fixture locations.
- `artifacts/`, `outputs/`: generated indexes, models, reports, and submission output.

## Compatibility directories

The existing `data_generation/`, `document/`, `input/`, `scripts/`, and legacy
dataset files remain in place to preserve prior workflows and data. The prior
project README is retained at `docs/legacy/README_data_generation_legacy.md`.
