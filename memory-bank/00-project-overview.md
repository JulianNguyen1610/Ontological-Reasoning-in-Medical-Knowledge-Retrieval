# Project Overview

## Purpose

This repository generates synthetic Vietnamese clinical text for downstream medical NLP tasks:

- named entity recognition
- assertion detection
- entity linking / medical coding

The project focuses on realistic clinical note generation guided by medical knowledge seeds such as ICD-10, RxNorm, symptoms, and lab tests.

## Main Inputs

- `data_generation/knowledge_seeds/*.json`: structured domain seeds
- `input/*.txt`: sample source material / reference inputs
- `data_generation/.env`: API configuration for real LLM runs
- `data_generation/config.py`: generation settings and distributions

## Main Outputs

- `data/raw_generated/`: raw or mock-generated datasets
- `data_generation/output/`: timestamped pipeline outputs and stats
- `data/`: cleaned final datasets and summary stats

## Core Runtime Modes

- Mock mode: `python scripts/run_generation.py`
- Real LLM mode: `python data_generation/run_pipeline.py`
- Cleanup-only flow: `python data_generation/utils/cleanup.py`

## What Success Looks Like

- generated samples contain valid entity spans
- entity types stay within the allowed schema
- offsets match the final text
- outputs are saved as JSON and JSONL
- stats are produced for coverage and validation
