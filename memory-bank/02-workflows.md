# Workflows

## Environment Setup

Install dependencies:

```bash
pip install -r data_generation/requirements.txt
```

Configure real-model access in:

- `data_generation/.env`

## Common Commands

Mock generation:

```bash
python scripts/run_generation.py
```

Real generation:

```bash
python data_generation/run_pipeline.py
```

Run tests:

```bash
pytest
```

Rebuild CodeGraph index:

```bash
codegraph index .
```

Check CodeGraph status:

```bash
codegraph status .
```

Explore code after indexing:

```bash
codegraph explore "DataGenerationPipeline TextGenerator CriticAgent"
```

## Typical Debug Path

If generated samples are invalid:

1. inspect `data_generation/pipeline.py`
2. inspect `data_generation/generators/text_generator.py`
3. inspect `data_generation/generators/critic_agent.py`
4. inspect `data_generation/utils/cleanup.py`

## Test Focus

The repo already contains:

- smoke coverage
- pipeline-oriented tests

When changing generation logic, verify both output format and entity span integrity.
