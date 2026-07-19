"""Framework-neutral contracts for reproducible local model training."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Generic, Mapping, Protocol, TypeVar, runtime_checkable

from medlink_ie.provenance.manifest import ModelArtifact

_MAX_MODEL_PARAMETERS = 9_000_000_000
_SPLITS = frozenset({"train", "dev", "test"})
_LoadedModel = TypeVar("_LoadedModel")


def _frozen_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class DataloaderSettings:
    """Explicit settings required for reproducible data ordering."""

    worker_count: int = 0
    shuffle: bool = True
    persistent_workers: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.worker_count, bool) or self.worker_count < 0:
            raise ValueError("worker_count must be a non-negative integer")
        if self.persistent_workers and self.worker_count == 0:
            raise ValueError("persistent_workers requires at least one worker")


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    model_name: str
    seed: int
    code_commit: str
    output_directory: Path
    dataloader: DataloaderSettings = DataloaderSettings()
    resume_behavior: str = "never"
    parameter_count: int | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_name or not self.code_commit:
            raise ValueError("model_name and code_commit must be non-empty")
        if isinstance(self.seed, bool) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if self.resume_behavior not in {"never", "resume_required", "resume_if_available"}:
            raise ValueError("unsupported resume_behavior")
        if (
            self.parameter_count is not None
            and not 1 <= self.parameter_count <= _MAX_MODEL_PARAMETERS
        ):
            raise ValueError("parameter_count must be between 1 and 9B when declared")
        if not isinstance(self.dataloader, DataloaderSettings):
            raise TypeError("dataloader must be DataloaderSettings")
        object.__setattr__(self, "output_directory", Path(self.output_directory))
        object.__setattr__(self, "settings", _frozen_mapping(self.settings, "settings"))

    def snapshot(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "code_commit": self.code_commit,
                "dataloader": {
                    "persistent_workers": self.dataloader.persistent_workers,
                    "shuffle": self.dataloader.shuffle,
                    "worker_count": self.dataloader.worker_count,
                },
                "model_name": self.model_name,
                "output_directory": str(self.output_directory),
                "parameter_count": self.parameter_count,
                "resume_behavior": self.resume_behavior,
                "seed": self.seed,
                "settings": dict(self.settings),
            }
        )


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Checksummed split identity; IDs must be disjoint to prevent leakage."""

    split_checksums: Mapping[str, str]
    split_record_ids: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        checksums = dict(self.split_checksums)
        identifiers = {name: tuple(values) for name, values in self.split_record_ids.items()}
        if set(checksums) != _SPLITS or set(identifiers) != _SPLITS:
            raise ValueError("dataset manifest must define exactly train, dev, and test splits")
        if any(not isinstance(value, str) or not value for value in checksums.values()):
            raise ValueError("split checksums must be non-empty strings")
        seen: dict[str, str] = {}
        for split_name, values in identifiers.items():
            if len(set(values)) != len(values) or any(not item for item in values):
                raise ValueError(f"{split_name} record IDs must be unique non-empty strings")
            for record_id in values:
                previous = seen.setdefault(record_id, split_name)
                if previous != split_name:
                    raise ValueError(f"record ID {record_id!r} occurs in multiple splits")
        object.__setattr__(self, "split_checksums", MappingProxyType(checksums))
        object.__setattr__(self, "split_record_ids", MappingProxyType(identifiers))


@dataclass(frozen=True, slots=True)
class RawPredictions:
    """Uncalibrated logits only; callers apply calibration and thresholds later."""

    split_name: str
    logits: Mapping[str, Mapping[str, float]]

    def __post_init__(self) -> None:
        if self.split_name not in _SPLITS:
            raise ValueError("split_name must be train, dev, or test")
        copied = {
            sample_id: MappingProxyType(dict(values)) for sample_id, values in self.logits.items()
        }
        if any(not sample_id or not values for sample_id, values in copied.items()):
            raise ValueError("raw predictions require non-empty sample IDs and logits")
        if any(
            not isinstance(logit, (int, float)) or isinstance(logit, bool)
            for values in copied.values()
            for logit in values.values()
        ):
            raise TypeError("logits must be numeric")
        object.__setattr__(self, "logits", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class CalibrationArtifact:
    """Calibration parameters, deliberately separate from raw model logits."""

    version: str
    parameters: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("calibration version must be non-empty")
        copied = dict(self.parameters)
        if any(not label or not isinstance(value, (int, float)) for label, value in copied.items()):
            raise ValueError("calibration parameters must have non-empty labels and numeric values")
        object.__setattr__(self, "parameters", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class TrainingArtifact:
    model_artifact: ModelArtifact
    config_snapshot: Mapping[str, Any]
    dataset_manifest: DatasetManifest
    code_manifest: Mapping[str, str]
    model_manifest: Mapping[str, Any]
    resume_behavior: str

    @classmethod
    def create(
        cls,
        model_artifact: ModelArtifact,
        config: TrainingConfig,
        dataset_manifest: DatasetManifest,
        model_manifest: Mapping[str, Any],
    ) -> "TrainingArtifact":
        return cls(
            model_artifact,
            config.snapshot(),
            dataset_manifest,
            {"commit": config.code_commit},
            {**dict(model_manifest), "parameter_count": model_artifact.parameter_count},
            config.resume_behavior,
        )

    def __post_init__(self) -> None:
        self.model_artifact.validate(verify_path=True)
        if (
            self.model_artifact.parameter_count is not None
            and self.model_artifact.parameter_count > _MAX_MODEL_PARAMETERS
        ):
            raise ValueError("model artifact exceeds the 9B parameter limit")
        if self.resume_behavior not in {"never", "resume_required", "resume_if_available"}:
            raise ValueError("unsupported resume_behavior")
        object.__setattr__(
            self, "config_snapshot", _frozen_mapping(self.config_snapshot, "config_snapshot")
        )
        object.__setattr__(
            self, "code_manifest", _frozen_mapping(self.code_manifest, "code_manifest")
        )
        object.__setattr__(
            self, "model_manifest", _frozen_mapping(self.model_manifest, "model_manifest")
        )


@runtime_checkable
class TrainableModel(Protocol):
    def train(
        self, config: TrainingConfig, dataset_manifest: DatasetManifest
    ) -> TrainingArtifact: ...

    def predict(self, batch: tuple[str, ...]) -> RawPredictions: ...

    def calibrate(self, dev_predictions: RawPredictions) -> CalibrationArtifact: ...


class TrainingHarness:
    """Applies deterministic process settings before delegating model-specific work."""

    def __init__(self, model: TrainableModel) -> None:
        if not isinstance(model, TrainableModel):
            raise TypeError("model must implement TrainableModel")
        self._model = model

    def train(self, config: TrainingConfig, dataset_manifest: DatasetManifest) -> TrainingArtifact:
        _seed_runtime(config.seed)
        artifact = self._model.train(config, dataset_manifest)
        if artifact.dataset_manifest != dataset_manifest:
            raise ValueError(
                "training artifact dataset manifest differs from the requested manifest"
            )
        if dict(artifact.model_artifact.dataset_versions) != dict(dataset_manifest.split_checksums):
            raise ValueError(
                "model artifact dataset_versions differs from the requested dataset manifest"
            )
        if artifact.model_artifact.model_name != config.model_name:
            raise ValueError("training artifact model_name differs from the requested config")
        if artifact.model_artifact.code_commit != config.code_commit:
            raise ValueError("training artifact code_commit differs from the requested config")
        if artifact.model_artifact.seed != config.seed:
            raise ValueError("training artifact seed differs from the requested config")
        if (
            config.parameter_count is not None
            and artifact.model_artifact.parameter_count != config.parameter_count
        ):
            raise ValueError("training artifact parameter_count differs from the requested config")
        return artifact

    def predict(self, batch: tuple[str, ...]) -> RawPredictions:
        return self._model.predict(tuple(batch))

    def calibrate(self, dev_predictions: RawPredictions) -> CalibrationArtifact:
        if dev_predictions.split_name != "dev":
            raise ValueError(
                "calibration accepts dev predictions only; test predictions are prohibited"
            )
        return self._model.calibrate(dev_predictions)


class OfflineArtifactLoader(Generic[_LoadedModel]):
    """Loads a local, checksum-verified model artifact without network fallback."""

    def __init__(self, deserialize: Callable[[Path], _LoadedModel]) -> None:
        self._deserialize = deserialize

    def load(self, artifact: ModelArtifact, required_interface_version: str) -> _LoadedModel:
        if not required_interface_version:
            raise ValueError("required_interface_version must be non-empty")
        if not artifact.path.is_file():
            raise FileNotFoundError(
                f"artifact is missing; automatic download is disabled: {artifact.path}"
            )
        artifact.validate(verify_path=True)
        if artifact.training_config.get("interface_version") != required_interface_version:
            raise ValueError("unsupported artifact interface version")
        return self._deserialize(artifact.path)


def _seed_runtime(seed: int) -> None:
    """Seed standard-library randomness and record hash behavior before model setup."""

    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
