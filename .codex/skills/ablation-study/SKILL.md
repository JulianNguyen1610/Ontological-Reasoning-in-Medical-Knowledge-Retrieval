---
name: ablation-study
description: Design and run fair ablation studies to evaluate which components of a model or pipeline contribute to performance. Use when evaluating component contributions.
---
---

# Ablation Study Skill

Use this skill when evaluating which components of a proposed model or pipeline actually contribute to performance.

## Goal

Design and run a fair ablation study.

## Workflow

### 1. Identify components

List all removable components:

- Preprocessing step
- Feature group
- Model module
- Loss term
- Data augmentation
- Retrieval step
- Ensemble component
- Thresholding method

### 2. Define full system

Record the full proposed method as the reference system.

### 3. Define ablations

For each component:

- Remove exactly one component.
- Keep all other settings unchanged.
- Use the same dataset split.
- Use the same metric.
- Use the same seed or multiple seeds.

### 4. Run controlled experiments

Save:

- Config for each ablation.
- Metrics.
- Predictions.
- Difference from full system.
- Notes on runtime and memory.

### 5. Interpret

A component is useful only if:

- It improves relevant metrics consistently.
- It does not harm critical minority classes.
- The gain is larger than random variation.
- The added complexity is justified.

## Output Format

```markdown
# Ablation Study Plan

| Variant | Removed Component | Hypothesis | Metric | Expected Effect |
|---|---|---|---|---|

## Execution Commands
## Result Table
## Interpretation
## Decision
```


