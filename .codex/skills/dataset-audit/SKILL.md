---
name: dataset-audit
description: Inspect, clean, split, and validate datasets for ML/NLP experiments. Use when working with data quality, leakage detection, class imbalance, or split strategy.
---
---

# Dataset Audit Skill

Use this skill when inspecting, cleaning, splitting, or validating a dataset for ML/NLP experiments.

## Goal

Detect data quality problems, data leakage risks, class imbalance, annotation issues, and reproducibility gaps before model training.

## Workflow

### 1. Inspect dataset schema

Check:

- Number of samples
- Column names
- Target label
- Feature columns
- Data types
- Missing values
- Duplicate samples
- Unique labels
- Example samples per class

### 2. Check task validity

Clarify:

- Task type: classification, regression, sequence labeling, retrieval, generation.
- Input format.
- Output format.
- Label semantics.
- Evaluation metric.

### 3. Detect leakage

Check:

- Duplicate or near-duplicate samples across splits.
- Target leakage features.
- Future information in temporal data.
- Preprocessing fitted before split.
- IDs or filenames encoding labels.
- Same author/source appearing across splits when group split is needed.

### 4. Analyze distribution

For classification:

- Label distribution.
- Minority class count.
- Stratification need.
- Macro-F1 suitability.

For NLP:

- Text length distribution.
- Empty/very short texts.
- Unicode normalization issues.
- Language/domain mixture.
- Repeated templates.
- Label-text artifacts.

### 5. Recommend split strategy

Choose:

- Random split
- Stratified split
- Group split
- Time-based split
- Cross-validation

Explain why.

### 6. Produce audit report

Create a report with:

- Findings
- Risks
- Required fixes
- Suggested preprocessing
- Split protocol
- Reproducibility settings

## Output Format

```markdown
# Dataset Audit Report

## 1. Dataset Overview
## 2. Schema and Labels
## 3. Quality Issues
## 4. Leakage Risks
## 5. Distribution Analysis
## 6. Recommended Split
## 7. Required Fixes Before Training
```


