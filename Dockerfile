FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /workspace
COPY pyproject.toml requirements.lock README.md ./
COPY src ./src
COPY specs/artifact_inventory.yaml ./specs/artifact_inventory.yaml
RUN pip install --no-cache-dir -r requirements.lock .

# Artifacts and clinical inputs are intentionally mounted read-only at runtime.
ENTRYPOINT ["medlink-ie"]
