---
name: error-analysis
description: Analyze model mistakes and failure modes to convert predictions into actionable scientific insight. Use when model results are available and understanding errors is needed.
---
---

# Error Analysis Skill

Use this skill when model results are available and the user wants to understand mistakes, failure modes, or next improvements.

## Goal

Convert predictions into actionable scientific insight.

## Workflow

### 1. Load evaluation artifacts

Use:

- predictions.csv
- metrics.json
- classification report
- confusion matrix
- input samples if available

### 2. Segment errors

Analyze by:

- Class label
- Text length
- Domain/source
- Confidence score
- Ambiguous labels
- Rare classes
- Out-of-distribution samples
- Preprocessing artifacts

### 3. Identify error types

For NLP:

- Negation
- Sarcasm
- Ambiguous sentiment
- Long context truncation
- Code-switching
- Vietnamese diacritics
- Named entities
- Domain-specific terms
- Label noise

For ML:

- Outliers
- Feature sparsity
- Class overlap
- Distribution shift
- Threshold errors

### 4. Recommend next experiments

Each recommendation must include:

- Hypothesis
- Proposed change
- Expected benefit
- Possible failure mode
- Verification metric

### 5. Avoid

- Do not claim improvement without rerunning experiments.
- Do not tune on test data.
- Do not cherry-pick only successful examples.

## Output Format

```markdown
# Error Analysis Report

## 1. Overall Metrics
## 2. Confusion Patterns
## 3. Representative Errors
## 4. Failure Mode Taxonomy
## 5. Hypotheses
## 6. Recommended Experiments
```


