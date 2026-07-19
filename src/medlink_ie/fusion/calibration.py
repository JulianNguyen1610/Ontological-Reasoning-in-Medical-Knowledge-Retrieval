"""Leakage-safe OOF calibration and configurable source-aware proposal fusion."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from medlink_ie.domain import EntityType, ProposalSource


class CalibrationMethod(str, Enum):
    TEMPERATURE = "temperature"
    PLATT = "platt"
    ISOTONIC = "isotonic"


@dataclass(frozen=True, slots=True)
class CalibrationPoint:
    example_id: str
    group_id: str
    split: str
    source: ProposalSource
    entity_type: EntityType
    logit: float
    label: int

    def __post_init__(self) -> None:
        if not self.example_id or not self.group_id or self.split not in {"dev", "oof"}:
            raise ValueError("calibration points require IDs and a dev or oof split")
        if not math.isfinite(self.logit) or self.label not in {0, 1}:
            raise ValueError("calibration logits must be finite and labels binary")


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    method: CalibrationMethod = CalibrationMethod.TEMPERATURE
    version: str = "fusion-calibration-v1"


@dataclass(frozen=True, slots=True)
class CalibratorModel:
    method: CalibrationMethod
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def apply(self, logit: float) -> float:
        if self.method is CalibrationMethod.TEMPERATURE:
            return _sigmoid(logit / float(self.parameters["temperature"]))
        if self.method is CalibrationMethod.PLATT:
            return _sigmoid(float(self.parameters["a"]) * logit + float(self.parameters["b"]))
        thresholds = tuple((float(x), float(y)) for x, y in self.parameters["steps"])
        return next(
            (value for threshold, value in thresholds if logit <= threshold), thresholds[-1][1]
        )


@dataclass(frozen=True, slots=True)
class FusionCalibrationArtifact:
    version: str
    models: Mapping[str, CalibratorModel]
    fit_group_ids: frozenset[str]
    checksum_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.version or not self.fit_group_ids:
            raise ValueError("calibration artifact requires version and fit group IDs")
        models = dict(self.models)
        if not models or any(not isinstance(item, CalibratorModel) for item in models.values()):
            raise ValueError("calibration artifact requires models")
        object.__setattr__(self, "models", MappingProxyType(models))
        expected = _checksum(self._body())
        if self.checksum_sha256 and self.checksum_sha256 != expected:
            raise ValueError("calibration artifact checksum mismatch")
        object.__setattr__(self, "checksum_sha256", expected)

    def calibrate(self, source: ProposalSource, entity_type: EntityType, logit: float) -> float:
        return self.models[_model_key(source, entity_type)].apply(logit)

    def _body(self) -> dict[str, Any]:
        return {
            "fit_group_ids": sorted(self.fit_group_ids),
            "models": {
                key: {"method": model.method.value, "parameters": dict(model.parameters)}
                for key, model in sorted(self.models.items())
            },
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "checksum_sha256": self.checksum_sha256}


def fit_calibration(
    points: tuple[CalibrationPoint, ...], config: CalibrationConfig = CalibrationConfig()
) -> FusionCalibrationArtifact:
    """Fit only on designated grouped dev/OOF predictions, never train/test scores."""
    if not points:
        raise ValueError("calibration requires points")
    _validate_groups(points)
    grouped: dict[str, list[CalibrationPoint]] = {}
    for point in points:
        grouped.setdefault(_model_key(point.source, point.entity_type), []).append(point)
    models = {
        key: _fit_model(tuple(sorted(items, key=lambda item: item.example_id)), config.method)
        for key, items in grouped.items()
    }
    return FusionCalibrationArtifact(
        config.version, models, frozenset(point.group_id for point in points)
    )


def write_calibration_artifact(path: Path, artifact: FusionCalibrationArtifact) -> Path:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite calibration artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def load_calibration_artifact(path: Path) -> FusionCalibrationArtifact:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("calibration artifact must be an object")
    models_value = value.get("models")
    if not isinstance(models_value, Mapping):
        raise ValueError("calibration artifact models must be an object")
    models = {
        str(key): CalibratorModel(CalibrationMethod(item["method"]), item["parameters"])
        for key, item in models_value.items()
        if isinstance(item, Mapping) and isinstance(item.get("parameters"), Mapping)
    }
    return FusionCalibrationArtifact(
        str(value.get("version")),
        models,
        frozenset(str(item) for item in value.get("fit_group_ids", [])),
        str(value.get("checksum_sha256", "")),
    )


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_prediction: float
    empirical_frequency: float


@dataclass(frozen=True, slots=True)
class ReliabilityReport:
    bins: tuple[ReliabilityBin, ...]
    expected_calibration_error: float

    def to_markdown(self) -> str:
        """Render a deterministic reliability table suitable for experiment reports."""
        rows = ["| range | count | mean prediction | observed |", "|---|---:|---:|---:|"]
        rows.extend(
            f"| [{item.lower:.2f}, {item.upper:.2f}] | {item.count} | "
            f"{item.mean_prediction:.4f} | {item.empirical_frequency:.4f} |"
            for item in self.bins
        )
        rows.append(f"\nECE: {self.expected_calibration_error:.6f}")
        return "\n".join(rows) + "\n"


def evaluate_calibration(
    artifact: FusionCalibrationArtifact, points: tuple[CalibrationPoint, ...], bins: int = 10
) -> ReliabilityReport:
    """Evaluate held-out groups only; fitting groups are rejected to prevent leakage."""
    if bins < 1 or artifact.fit_group_ids & {point.group_id for point in points}:
        raise ValueError("cannot evaluate calibration on examples used to fit it")
    values = [
        (artifact.calibrate(point.source, point.entity_type, point.logit), point.label)
        for point in points
    ]
    contents: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for probability, label in values:
        contents[min(int(probability * bins), bins - 1)].append((probability, label))
    table = tuple(
        ReliabilityBin(
            index / bins,
            (index + 1) / bins,
            len(items),
            _mean([item[0] for item in items]),
            _mean([float(item[1]) for item in items]),
        )
        for index, items in enumerate(contents)
    )
    total = len(values) or 1
    ece = sum(
        bin.count / total * abs(bin.mean_prediction - bin.empirical_frequency) for bin in table
    )
    return ReliabilityReport(table, ece)


@dataclass(frozen=True, slots=True)
class FusionConfig:
    implementation_key: str = "rule"
    source_weights: Mapping[ProposalSource, float] = field(default_factory=dict)
    per_type_thresholds: Mapping[EntityType, float] = field(default_factory=dict)
    missing_source_policy: str = "ignore"
    meta_bias: float = 0.0

    def __post_init__(self) -> None:
        if self.implementation_key not in {"rule", "meta_classifier"}:
            raise ValueError("fusion implementation must be rule or meta_classifier")
        if self.missing_source_policy not in {"ignore", "zero"}:
            raise ValueError("missing_source_policy must be ignore or zero")
        if any(not math.isfinite(value) or value < 0 for value in self.source_weights.values()):
            raise ValueError("source weights must be finite non-negative values")
        if any(not 0 <= value <= 1 for value in self.per_type_thresholds.values()):
            raise ValueError("per-type thresholds must be in [0, 1]")
        if not math.isfinite(self.meta_bias):
            raise ValueError("meta_bias must be finite")
        object.__setattr__(self, "source_weights", MappingProxyType(dict(self.source_weights)))
        object.__setattr__(
            self, "per_type_thresholds", MappingProxyType(dict(self.per_type_thresholds))
        )


@dataclass(frozen=True, slots=True)
class FusionInput:
    candidate_id: str
    entity_type: EntityType
    source_logits: Mapping[ProposalSource, float | None]

    def __post_init__(self) -> None:
        if not self.candidate_id or not isinstance(self.entity_type, EntityType):
            raise ValueError("fusion input requires candidate ID and entity type")
        logits = dict(self.source_logits)
        if any(
            not isinstance(source, ProposalSource)
            or (value is not None and (isinstance(value, bool) or not math.isfinite(value)))
            for source, value in logits.items()
        ):
            raise ValueError("source logits must be finite numbers or None")
        object.__setattr__(self, "source_logits", MappingProxyType(logits))


@dataclass(frozen=True, slots=True)
class FusionResult:
    candidate_id: str
    entity_type: EntityType
    probability: float
    accepted: bool
    source_reliability: Mapping[ProposalSource, float]
    missing_sources: tuple[ProposalSource, ...]


class SourceAwareFusion:
    def __init__(
        self, artifact: FusionCalibrationArtifact, config: FusionConfig = FusionConfig()
    ) -> None:
        self.artifact, self.config = artifact, config

    def fuse(self, item: FusionInput) -> FusionResult:
        available: dict[ProposalSource, float] = {}
        missing: list[ProposalSource] = []
        for source, logit in sorted(item.source_logits.items(), key=lambda pair: pair[0].value):
            if logit is None:
                missing.append(source)
                if self.config.missing_source_policy == "zero":
                    available[source] = 0.0
                continue
            key = _model_key(source, item.entity_type)
            if key not in self.artifact.models:
                missing.append(source)
                continue
            available[source] = self.artifact.calibrate(source, item.entity_type, logit)
        weighted = [
            (self.config.source_weights.get(source, 1.0), value)
            for source, value in available.items()
        ]
        if self.config.implementation_key == "meta_classifier":
            probability = _sigmoid(
                self.config.meta_bias + sum(weight * value for weight, value in weighted)
            )
        else:
            denominator = sum(weight for weight, _ in weighted)
            probability = (
                0.0
                if denominator == 0
                else sum(weight * value for weight, value in weighted) / denominator
            )
        threshold = self.config.per_type_thresholds.get(item.entity_type, 1.0)
        return FusionResult(
            item.candidate_id,
            item.entity_type,
            probability,
            probability >= threshold,
            MappingProxyType(available),
            tuple(missing),
        )


def _fit_model(points: tuple[CalibrationPoint, ...], method: CalibrationMethod) -> CalibratorModel:
    labels = {point.label for point in points}
    if labels != {0, 1}:
        raise ValueError("each calibrator requires both positive and negative examples")
    if method is CalibrationMethod.TEMPERATURE:
        temperature = min(
            (index / 10 for index in range(1, 101)),
            key=lambda value: _loss(points, lambda x: _sigmoid(x / value)),
        )
        return CalibratorModel(method, {"temperature": temperature})
    if method is CalibrationMethod.PLATT:
        a, b = 1.0, 0.0
        for _ in range(500):
            gradients = [
                (_sigmoid(a * point.logit + b) - point.label, point.logit) for point in points
            ]
            a -= 0.05 * _mean([error * score for error, score in gradients])
            b -= 0.05 * _mean([error for error, _ in gradients])
        return CalibratorModel(method, {"a": a, "b": b})
    blocks = [
        [point.logit, point.logit, float(point.label), 1]
        for point in sorted(points, key=lambda point: point.logit)
    ]
    merged: list[list[float | int]] = []
    for block in blocks:
        merged.append(block)
        while len(merged) > 1 and float(merged[-2][2]) / int(merged[-2][3]) > float(
            merged[-1][2]
        ) / int(merged[-1][3]):
            right, left = merged.pop(), merged.pop()
            merged.append(
                [left[0], right[1], float(left[2]) + float(right[2]), int(left[3]) + int(right[3])]
            )
    return CalibratorModel(
        method, {"steps": [[block[1], float(block[2]) / int(block[3])] for block in merged]}
    )


def _validate_groups(points: tuple[CalibrationPoint, ...]) -> None:
    groups: dict[str, str] = {}
    for point in points:
        previous = groups.setdefault(point.group_id, point.split)
        if previous != point.split:
            raise ValueError("dataset group IDs must not cross calibration splits")


def _model_key(source: ProposalSource, entity_type: EntityType) -> str:
    return f"{source.value}:{entity_type.value}"


def _checksum(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, value))))


def _loss(points: tuple[CalibrationPoint, ...], transform: Any) -> float:
    return -sum(
        point.label * math.log(max(transform(point.logit), 1e-12))
        + (1 - point.label) * math.log(max(1 - transform(point.logit), 1e-12))
        for point in points
    )


def _mean(values: list[float]) -> float:
    return 0.0 if not values else sum(values) / len(values)
