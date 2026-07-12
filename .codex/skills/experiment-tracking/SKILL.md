---
name: experiment-tracking
description: Create or refactor experiment logging, configs, metrics storage, and output directory structure. Use when setting up reproducible experiment tracking.
---
---

# Experiment Tracking Skill

Use this skill when creating or refactoring experiment logging, configs, metrics storage, or output directories.

## Goal

Make every experiment reproducible and comparable.

## Required Output Structure

```text
outputs/
  <experiment_name>/
    config.yaml
    metrics.json
    predictions.csv
    plots/
    checkpoints/
    logs/
```

## Workflow

### 1. Define experiment identity

Record:

- Experiment name
- Timestamp
- Git commit if available
- Dataset version
- Model
- Seed
- Split strategy

### 2. Define config

Config should include:

- Data paths
- Preprocessing parameters
- Feature settings
- Model hyperparameters
- Training parameters
- Metric definitions
- Output directory

### 3. Define metrics schema

Use JSON for single runs:

```json
{
  "experiment_name": "...",
  "seed": 42,
  "metrics": {
    "accuracy": 0.0,
    "macro_f1": 0.0
  }
}
```

Use CSV for multi-run comparison.

### 4. Save predictions

Predictions should include:

- sample_id if available
- true label
- predicted label
- predicted probability/logit when useful
- text/input reference when privacy allows

### 5. Prevent overwrite

Do not overwrite previous experiment outputs unless explicitly requested.

## Verification

After implementation, verify:

- Config is saved.
- Metrics are saved.
- Predictions are saved.
- Output paths are deterministic or timestamped.
- Re-running does not destroy previous results.


