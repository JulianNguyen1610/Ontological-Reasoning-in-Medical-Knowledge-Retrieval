---
name: baseline-experiment
description: Build and compare ML/NLP baselines before implementing complex models. Use when creating the first reliable baseline or comparing a proposed model against simple baselines.
---
---

# Baseline Experiment Skill

Use this skill when creating the first reliable ML/NLP baseline or comparing a proposed model against simple baselines.

## Goal

Build a clean, reproducible baseline before adding complex models.

## Workflow

### 1. Define baseline objective

Clarify:

- Task type
- Dataset
- Input feature
- Target label
- Metric
- Split strategy

### 2. Select baselines

For classification:

- Majority class baseline
- Logistic Regression
- Linear SVM
- Random Forest or XGBoost for tabular data

For NLP:

- TF-IDF + Logistic Regression
- TF-IDF + Linear SVM
- Pretrained Transformer baseline when relevant

For regression:

- Mean predictor
- Linear Regression
- Ridge/Lasso/ElasticNet
- Random Forest Regressor

### 3. Enforce correct pipeline

Use the order:

1. Load data.
2. Split data.
3. Fit preprocessing on training only.
4. Transform validation/test.
5. Train baseline.
6. Tune on validation only.
7. Evaluate on test once.

### 4. Save artifacts

Save:

- config.yaml
- metrics.json
- predictions.csv
- confusion_matrix.png when useful
- classification_report.txt or report.json

### 5. Interpret results

Compare against trivial baseline.

State:

- What works.
- What fails.
- Which classes are confused.
- Whether the baseline is strong enough.
- What next experiment is justified.

## Output Format

```markdown
# Baseline Experiment Plan

## 1. Task and Metric
## 2. Baselines
## 3. Pipeline
## 4. Files to Modify
## 5. Commands
## 6. Expected Outputs
## 7. Interpretation Checklist
```


