"""Run a configured local encoder training adapter; it never downloads a model."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Callable, Sequence

from medlink_ie.training import TrainingArtifact

TrainingRunner = Callable[[Path, Path, Path], TrainingArtifact]


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--adapter",
        required=True,
        help="local module:function accepting model-config, training-config, and dataset paths",
    )
    parser.add_argument("--model-config", required=True, type=Path)
    parser.add_argument("--training-config", required=True, type=Path)
    parser.add_argument(
        "--dataset", required=True, type=Path, help="local pickle-free adapter input"
    )
    parser.add_argument("--output", required=True, type=Path)
    parsed = parser.parse_args(arguments)
    artifact = _load_runner(parsed.adapter)(
        parsed.model_config, parsed.training_config, parsed.dataset
    )
    if not isinstance(artifact, TrainingArtifact):
        raise TypeError("configured training adapter must return TrainingArtifact")
    parsed.output.parent.mkdir(parents=True, exist_ok=True)
    if parsed.output.exists():
        raise FileExistsError(f"refusing to overwrite existing training artifact: {parsed.output}")
    parsed.output.write_text(_artifact_json(artifact), encoding="utf-8")
    return 0


def _load_runner(reference: str) -> TrainingRunner:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("adapter must use module:function syntax")
    runner = getattr(importlib.import_module(module_name), attribute)
    if not callable(runner):
        raise TypeError("adapter must be callable")
    return runner  # type: ignore[return-value]


def _artifact_json(artifact: TrainingArtifact) -> str:
    return (
        json.dumps(
            {
                "checksum_sha256": artifact.model_artifact.checksum_sha256,
                "model_name": artifact.model_artifact.model_name,
                "parameter_count": artifact.model_artifact.parameter_count,
                "seed": artifact.model_artifact.seed,
            },
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
