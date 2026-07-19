from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from medlink_ie.provenance.manifest import ModelArtifact
from medlink_ie.training import (
    CalibrationArtifact,
    DataloaderSettings,
    DatasetManifest,
    OfflineArtifactLoader,
    RawPredictions,
    TrainingArtifact,
    TrainingConfig,
    TrainingHarness,
)


@dataclass(frozen=True, slots=True)
class _TinyDeterministicModel:
    """A test double: its training result is fixed and needs no model framework."""

    artifact_path: Path

    def train(self, config: TrainingConfig, dataset_manifest: DatasetManifest) -> TrainingArtifact:
        del dataset_manifest
        self.artifact_path.write_bytes(b"tiny-deterministic-model-v1")
        artifact = ModelArtifact(
            model_name=config.model_name,
            parameter_count=3,
            path=self.artifact_path,
            checksum_sha256=sha256(self.artifact_path.read_bytes()).hexdigest(),
            training_config={"interface_version": "training-v1"},
            dataset_versions={"train": "train-sha", "dev": "dev-sha", "test": "test-sha"},
            code_commit=config.code_commit,
            seed=config.seed,
        )
        return TrainingArtifact.create(
            model_artifact=artifact,
            config=config,
            dataset_manifest=DatasetManifest(
                split_checksums={"train": "train-sha", "dev": "dev-sha", "test": "test-sha"},
                split_record_ids={"train": ("train-1",), "dev": ("dev-1",), "test": ("test-1",)},
            ),
            model_manifest={"format": "tiny-v1"},
        )

    def predict(self, batch: tuple[str, ...]) -> RawPredictions:
        return RawPredictions(
            "dev", {sample_id: {"positive": 1.0, "negative": -1.0} for sample_id in batch}
        )

    def calibrate(self, dev_predictions: RawPredictions) -> CalibrationArtifact:
        assert dev_predictions.split_name == "dev"
        return CalibrationArtifact("calibration-v1", {"positive": 1.0})


@dataclass(frozen=True, slots=True)
class _DatasetMismatchModel(_TinyDeterministicModel):
    def train(self, config: TrainingConfig, dataset_manifest: DatasetManifest) -> TrainingArtifact:
        artifact = _TinyDeterministicModel.train(self, config, dataset_manifest)
        model_artifact = ModelArtifact(
            artifact.model_artifact.model_name,
            artifact.model_artifact.parameter_count,
            artifact.model_artifact.path,
            artifact.model_artifact.checksum_sha256,
            artifact.model_artifact.training_config,
            {"train": "wrong", "dev": "dev-sha", "test": "test-sha"},
            artifact.model_artifact.code_commit,
            artifact.model_artifact.seed,
        )
        return TrainingArtifact.create(
            model_artifact, config, dataset_manifest, {"format": "tiny-v1"}
        )


def _dataset_manifest() -> DatasetManifest:
    return DatasetManifest(
        split_checksums={"train": "train-sha", "dev": "dev-sha", "test": "test-sha"},
        split_record_ids={"train": ("train-1",), "dev": ("dev-1",), "test": ("test-1",)},
    )


def _config(tmp_path: Path) -> TrainingConfig:
    return TrainingConfig(
        model_name="tiny-model",
        seed=13,
        code_commit="abc123",
        output_directory=tmp_path,
        dataloader=DataloaderSettings(worker_count=0, shuffle=True),
    )


def test_training_harness_snapshots_reproducibility_metadata_and_calibration(
    tmp_path: Path,
) -> None:
    model = _TinyDeterministicModel(tmp_path / "tiny.bin")
    harness = TrainingHarness(model)

    trained = harness.train(_config(tmp_path), _dataset_manifest())
    predictions = harness.predict(("dev-1",))
    calibration = harness.calibrate(predictions)

    assert trained.config_snapshot["seed"] == 13
    assert trained.code_manifest == {"commit": "abc123"}
    assert trained.model_manifest["parameter_count"] == 3
    assert trained.resume_behavior == "never"
    assert predictions.logits["dev-1"]["positive"] == 1.0
    assert calibration.parameters["positive"] == 1.0
    assert trained.model_artifact.parameter_count is not None
    assert trained.model_artifact.parameter_count <= 9_000_000_000


def test_dataset_manifest_rejects_cross_split_leakage() -> None:
    with pytest.raises(ValueError, match="multiple splits"):
        DatasetManifest(
            split_checksums={"train": "train", "dev": "dev", "test": "test"},
            split_record_ids={"train": ("shared",), "dev": ("shared",), "test": ("test-1",)},
        )


def test_training_harness_rejects_artifact_with_mismatched_data_provenance(tmp_path: Path) -> None:
    harness = TrainingHarness(_DatasetMismatchModel(tmp_path / "tiny.bin"))

    with pytest.raises(ValueError, match="dataset_versions"):
        harness.train(_config(tmp_path), _dataset_manifest())


def test_calibration_rejects_test_predictions(tmp_path: Path) -> None:
    harness = TrainingHarness(_TinyDeterministicModel(tmp_path / "tiny.bin"))

    with pytest.raises(ValueError, match="dev predictions only"):
        harness.calibrate(RawPredictions("test", {"test-1": {"positive": 1.0}}))


def test_offline_loader_verifies_checksum_and_never_downloads(tmp_path: Path) -> None:
    path = tmp_path / "tiny.bin"
    path.write_bytes(b"offline-only")
    artifact = ModelArtifact(
        "tiny-model",
        3,
        path,
        sha256(path.read_bytes()).hexdigest(),
        {"interface_version": "training-v1"},
        {"train": "train", "dev": "dev", "test": "test"},
        "abc123",
        1,
    )
    loader = OfflineArtifactLoader(lambda loaded: loaded.read_bytes())

    assert loader.load(artifact, "training-v1") == b"offline-only"
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        loader.load(artifact, "training-v1")
    with pytest.raises(FileNotFoundError, match="automatic download is disabled"):
        loader.load(
            ModelArtifact(
                "tiny-model",
                3,
                tmp_path / "missing.bin",
                "0" * 64,
                {"interface_version": "training-v1"},
                {"train": "train", "dev": "dev", "test": "test"},
                "abc123",
                1,
            ),
            "training-v1",
        )
