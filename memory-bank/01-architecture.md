# Architecture

## Top-Level Structure

- `data_generation/`: generation pipeline source code
- `data/`: cleaned and final output artifacts
- `scripts/`: helper scripts, especially mock runs
- `tests/`: smoke and pipeline tests
- `document/`: reference docs

## Main Pipeline Components

### `data_generation/pipeline.py`

Owns the end-to-end orchestration through `DataGenerationPipeline`:

- selects scenario complexity
- extracts topics from seeds
- generates text via LLM
- validates or auto-fixes entities through critic review
- runs cleanup filtering
- saves final outputs and stats

### `data_generation/config.py`

Holds generation policy and schema-related settings:

- sample count
- entity distribution
- assertion distribution
- scenario distribution
- noise configuration
- retry / pacing knobs

### `data_generation/llm_client.py`

Wraps model access for generation and review steps.

### `data_generation/generators/`

The multi-agent generation stages live here:

- `topic_extractor.py`: selects medically coherent scenarios from seeds
- `style_director.py`: injects clinical writing style and noise patterns
- `text_generator.py`: creates text and entity annotations
- `critic_agent.py`: validates results and attempts auto-fixes

### `data_generation/utils/`

- `cleanup.py`: schema filtering, offset relocation, deduplication
- `text_utils.py`: Unicode and fuzzy matching helpers

## Key Data Flow

1. Seeds are loaded.
2. A scenario is sampled.
3. Text and entities are generated.
4. Critic review checks validity.
5. Cleanup normalizes and filters entities.
6. Outputs and stats are persisted.
