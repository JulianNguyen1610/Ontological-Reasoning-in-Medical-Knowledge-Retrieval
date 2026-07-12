---
name: research-ai-ml-nlp
description: >
  Core skill for AI/ML/NLP research repository in Legal Domain (Vietnamese & English).
  Use when the user is working on research experiments, codebase changes, model training,
  evaluation, dataset handling, or any scientific computing task in this repository.
---

# Research AI/ML/NLP - Core Skill

This skill provides the foundational knowledge and rules for all work in this repository.

## Project Context

- **Research Topic**: Multi-Agent Courtroom Simulation Framework (Legal Domain)
- **Target Task**: Courtroom Simulation, Legal Debate, Legal Reasoning & Defense, Legal Judgment Prediction
- **Target Language/Domain**: Vietnamese & English Legal Documents, Court Cases, Criminal/Civil Laws
- **Primary Goals**:
  - Build reproducible experiments
  - Compare strong baselines with proposed methods
  - Maintain clean separation between data processing, modeling, evaluation, and reporting
  - Produce code, figures, tables, documentation suitable for academic report or paper

## Core Principles (Always Apply)

- Do not introduce data leakage.
- Do not tune hyperparameters on the test set.
- Do not fit preprocessing on validation or test data.
- Do not overwrite experiment results unless explicitly requested.
- Do not delete datasets, logs, checkpoints, notebooks, reports, or figures unless explicitly instructed.
- Do not make broad refactors when a targeted fix is sufficient.
- Do not claim model improvement without metric evidence.
- When proposing a change, state: assumption, expected benefit, possible failure mode, and how to verify empirically.

## Memory Bank

Read `memory-bank/` files at the start of every task if they exist:
- `projectbrief.md` - research goals and scope
- `researchContext.md` - problem, methods, dataset, related work
- `techContext.md` - dependencies, hardware, environment
- `systemPatterns.md` - architecture, pipeline, naming conventions
- `activeContext.md` - current focus, recent decisions
- `progress.md` - completed experiments, known issues, results

## Repository Structure Convention

- `src/` - source code (modules, not notebooks)
- `notebooks/` - exploratory notebooks (numbered: 01, 02, ...)
- `data/` - raw and processed data (not committed)
- `configs/` - configuration files (YAML, JSON)
- `scripts/` - executable scripts for training, evaluation
- `experiments/` - experiment outputs, logs, checkpoints
- `reports/` - figures, tables, LaTeX, markdown reports
- `tests/` - unit tests and integration tests
- `requirements.txt` / `pyproject.toml` - dependencies

## Scientific Claim Discipline

Use cautious language. Do not write `'`This model is better`'` without evidence.
Prefer: "The results suggest...", "Under this experimental setup...", "On this dataset split..."

For every proposed method, discuss: overfitting, data leakage, domain shift, class imbalance, label noise, unstable random seed, metric mismatch, computational cost.

## Related Sub-Skills

- `paper-summarization` - quick summary of an AI/ML paper in Vietnamese
- `baseline-experiment` - build baselines before complex models
- `ablation-study` - evaluate which components contribute to performance
- `dataset-audit` - inspect, clean, split, validate datasets
- `error Reno` - analyze model mistakes and failure modes
- `experiment-tracking` - logging, configs, metrics storage
- `literature-review-matrix` - compare multiple papers
- `ml-code-review` - review ML code for correctness
- `model-training-debugging` - debug training issues
- `paper-review-and-implementation` - detailed paper analysis + implementation plan
