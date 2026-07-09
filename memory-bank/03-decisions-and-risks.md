# Decisions And Risks

## Current Working Assumptions

- the project is centered on synthetic Vietnamese clinical text generation
- offsets are a critical contract for downstream consumers
- cleanup is part of correctness, not just post-processing
- mock generation is important for fast local iteration

## Operational Risks

- LLM outputs may drift from prompt expectations
- entity offsets may become invalid after text normalization
- schema coverage can become imbalanced if config distributions drift
- local logs and generated artifacts can create noisy git status

## Repo-Specific Notes

- `.codegraph/` is local index state and is ignored by git
- there are existing uncommitted changes in generation code; do not revert them casually
- generated data folders can grow quickly and should be reviewed before committing

## Recommended Next Improvements

- add a short contributor guide for test and run conventions
- separate committed fixtures from generated output more clearly
- add a documented refresh flow for final cleaned datasets
- add stronger validation around offset relocation edge cases
