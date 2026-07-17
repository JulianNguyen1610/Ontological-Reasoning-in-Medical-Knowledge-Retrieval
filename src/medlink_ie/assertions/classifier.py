"""Classifier contracts and deterministic post-processing for assertion labels.

This module deliberately separates model logits, calibration, fusion, and thresholding.
It does not train or load a model artifact.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from medlink_ie.domain import AssertionLabel, EntityType


def _frozen_labels(values: Mapping[AssertionLabel, float]) -> Mapping[AssertionLabel, float]:
    copied = dict(values)
    for label, value in copied.items():
        if not isinstance(label, AssertionLabel):
            raise TypeError("label scores must use AssertionLabel keys")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("label scores must be finite numbers")
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class AssertionClassifierInput:
    raw_text: str
    entity_start: int
    entity_end: int
    entity_type: EntityType

    def __post_init__(self) -> None:
        if not 0 <= self.entity_start < self.entity_end <= len(self.raw_text):
            raise ValueError("entity interval must be a non-empty raw-text interval")


@runtime_checkable
class AssertionClassifier(Protocol):
    """A model interface that emits uncalibrated, independent per-label logits."""

    def predict_logits(self, item: AssertionClassifierInput) -> Mapping[AssertionLabel, float]:
        """Return raw logits; callers must not treat these as probabilities."""


@dataclass(frozen=True, slots=True)
class DeterministicMockAssertionClassifier:
    """Fixed-logit test double; unspecified labels receive a neutral zero logit."""

    logits: Mapping[AssertionLabel, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "logits", _frozen_labels(self.logits))

    def predict_logits(self, item: AssertionClassifierInput) -> Mapping[AssertionLabel, float]:
        del item
        return MappingProxyType(
            {label: float(self.logits.get(label, 0.0)) for label in AssertionLabel}
        )


@dataclass(frozen=True, slots=True)
class CalibrationArtifact:
    """Versioned temperature/bias snapshot applied independently to each label."""

    version: str
    temperatures: Mapping[AssertionLabel, float] = field(default_factory=dict)
    biases: Mapping[AssertionLabel, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("calibration version must be non-empty")
        temperatures = _frozen_labels(self.temperatures)
        biases = _frozen_labels(self.biases)
        if any(value <= 0.0 for value in temperatures.values()):
            raise ValueError("calibration temperatures must be positive")
        object.__setattr__(self, "temperatures", temperatures)
        object.__setattr__(self, "biases", biases)

    @classmethod
    def identity(cls, version: str) -> "CalibrationArtifact":
        return cls(version)

    @classmethod
    def load(cls, path: Path) -> "CalibrationArtifact":
        if not path.is_file():
            raise FileNotFoundError(f"calibration artifact does not exist: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("version"), str):
            raise ValueError("calibration artifact must contain a string version")
        return cls(
            value["version"],
            _label_mapping(value.get("temperatures", {}), "temperatures"),
            _label_mapping(value.get("biases", {}), "biases"),
        )

    def calibrate(self, label: AssertionLabel, logit: float) -> float:
        temperature = self.temperatures.get(label, 1.0)
        bias = self.biases.get(label, 0.0)
        return _sigmoid(logit / temperature + bias)


class CalibratedAssertionClassifier:
    def __init__(self, classifier: AssertionClassifier, artifact: CalibrationArtifact) -> None:
        if not isinstance(classifier, AssertionClassifier):
            raise TypeError("classifier must implement AssertionClassifier")
        if not isinstance(artifact, CalibrationArtifact):
            raise TypeError("artifact must be a CalibrationArtifact")
        self.classifier = classifier
        self.artifact = artifact

    def predict_logits(self, item: AssertionClassifierInput) -> Mapping[AssertionLabel, float]:
        return _complete_logits(self.classifier.predict_logits(item))

    def predict_probabilities(
        self, logits: Mapping[AssertionLabel, float]
    ) -> Mapping[AssertionLabel, float]:
        return MappingProxyType(
            {
                label: self.artifact.calibrate(label, logit)
                for label, logit in _complete_logits(logits).items()
            }
        )


@dataclass(frozen=True, slots=True)
class RuleFeatures:
    probabilities: Mapping[AssertionLabel, float] = field(default_factory=dict)
    trace_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        values = _frozen_labels(self.probabilities)
        if any(not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("rule probabilities must be in [0, 1]")
        object.__setattr__(self, "probabilities", values)
        object.__setattr__(self, "trace_ids", tuple(self.trace_ids))


@runtime_checkable
class RuleModelFusion(Protocol):
    def fuse(
        self, model_logits: Mapping[AssertionLabel, float], rules: RuleFeatures
    ) -> Mapping[AssertionLabel, float]:
        """Combine rule features with raw model logits without applying calibration."""


@dataclass(frozen=True, slots=True)
class WeightedRuleModelFusion:
    rule_weight: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.rule_weight <= 1.0:
            raise ValueError("rule_weight must be in [0, 1]")

    def fuse(
        self, model_logits: Mapping[AssertionLabel, float], rules: RuleFeatures
    ) -> Mapping[AssertionLabel, float]:
        complete = _complete_logits(model_logits)
        fused: dict[AssertionLabel, float] = {}
        for label, model_logit in complete.items():
            rule_probability = rules.probabilities.get(label)
            if rule_probability is None:
                fused[label] = model_logit
            else:
                fused[label] = (
                    self.rule_weight * _logit(rule_probability)
                    + (1.0 - self.rule_weight) * model_logit
                )
        return MappingProxyType(fused)


@dataclass(frozen=True, slots=True)
class HardMaskPolicy:
    masked_by_type: Mapping[EntityType, frozenset[AssertionLabel]] = field(default_factory=dict)
    rule_id: str = "contract.C012.configured_hard_mask"

    def __post_init__(self) -> None:
        copied = {kind: frozenset(labels) for kind, labels in self.masked_by_type.items()}
        if any(not isinstance(kind, EntityType) for kind in copied):
            raise TypeError("hard masks must use EntityType keys")
        if any(
            any(not isinstance(label, AssertionLabel) for label in labels)
            for labels in copied.values()
        ):
            raise TypeError("hard masks must contain AssertionLabel values")
        object.__setattr__(self, "masked_by_type", MappingProxyType(copied))

    def masks(self, entity_type: EntityType, label: AssertionLabel) -> bool:
        return label in self.masked_by_type.get(entity_type, frozenset())


@dataclass(frozen=True, slots=True)
class AssertionClassificationConfig:
    thresholds: Mapping[AssertionLabel, float] = field(
        default_factory=lambda: {
            AssertionLabel.NEGATED: 0.90,
            AssertionLabel.HISTORICAL: 0.90,
            AssertionLabel.FAMILY: 0.95,
        }
    )
    minimum_evidence: float = 0.10

    def __post_init__(self) -> None:
        defaults = {
            AssertionLabel.NEGATED: 0.90,
            AssertionLabel.HISTORICAL: 0.90,
            AssertionLabel.FAMILY: 0.95,
        }
        defaults.update(_frozen_labels(self.thresholds))
        thresholds = _frozen_labels(defaults)
        if any(not 0.0 <= value <= 1.0 for value in thresholds.values()):
            raise ValueError("thresholds must be in [0, 1]")
        if not 0.0 <= self.minimum_evidence <= 1.0:
            raise ValueError("minimum_evidence must be in [0, 1]")
        object.__setattr__(self, "thresholds", thresholds)


@dataclass(frozen=True, slots=True)
class LabelThresholdDecision:
    label: AssertionLabel
    probability: float
    threshold: float
    included: bool
    reason: str
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssertionClassificationResult:
    raw_logits: Mapping[AssertionLabel, float]
    calibrated_probabilities: Mapping[AssertionLabel, float]
    assertions: tuple[AssertionLabel, ...]
    by_label: Mapping[AssertionLabel, LabelThresholdDecision]
    trace: tuple[str, ...]


class AssertionDecisionEngine:
    def __init__(
        self,
        classifier: CalibratedAssertionClassifier,
        fusion: RuleModelFusion,
        config: AssertionClassificationConfig = AssertionClassificationConfig(),
        hard_masks: HardMaskPolicy = HardMaskPolicy(),
    ) -> None:
        self.classifier = classifier
        self.fusion = fusion
        self.config = config
        self.hard_masks = hard_masks

    def classify(
        self, item: AssertionClassifierInput, rules: RuleFeatures = RuleFeatures()
    ) -> AssertionClassificationResult:
        raw_logits = self.classifier.predict_logits(item)
        fused_logits = self.fusion.fuse(raw_logits, rules)
        probabilities = self.classifier.predict_probabilities(fused_logits)
        evidence = max(
            [
                *rules.probabilities.values(),
                *(max(0.0, value - 0.5) * 2.0 for value in probabilities.values()),
            ],
            default=0.0,
        )
        decisions: dict[AssertionLabel, LabelThresholdDecision] = {}
        for label in AssertionLabel:
            probability = probabilities[label]
            threshold = self.config.thresholds[label]
            trace = (
                f"raw_logit:{raw_logits[label]:.6f}",
                f"calibration:{self.classifier.artifact.version}",
                f"fusion:{type(self.fusion).__name__}",
                *tuple(f"rule:{value}" for value in rules.trace_ids),
            )
            if self.hard_masks.masks(item.entity_type, label):
                decisions[label] = LabelThresholdDecision(
                    label,
                    probability,
                    threshold,
                    False,
                    "hard_mask:type",
                    trace + (self.hard_masks.rule_id,),
                )
            elif evidence < self.config.minimum_evidence:
                decisions[label] = LabelThresholdDecision(
                    label, probability, threshold, False, "abstain:insufficient_evidence", trace
                )
            elif probability >= threshold:
                decisions[label] = LabelThresholdDecision(
                    label, probability, threshold, True, "included:threshold", trace
                )
            else:
                decisions[label] = LabelThresholdDecision(
                    label, probability, threshold, False, "below_threshold", trace
                )
        assertions = tuple(label for label in AssertionLabel if decisions[label].included)
        trace = (
            ("abstained:insufficient_evidence",)
            if not assertions and evidence < self.config.minimum_evidence
            else ()
        )
        return AssertionClassificationResult(
            raw_logits, probabilities, assertions, MappingProxyType(decisions), trace
        )


@dataclass(frozen=True, slots=True)
class EmptyGroundTruthRisk:
    empty_gold_count: int
    false_positive_on_empty_gold: int
    rate: float


def empty_ground_truth_risk(
    gold: Sequence[Sequence[AssertionLabel]], predictions: Sequence[Sequence[AssertionLabel]]
) -> EmptyGroundTruthRisk:
    if len(gold) != len(predictions):
        raise ValueError("gold and predictions must have the same length")
    empty_gold = [index for index, labels in enumerate(gold) if not labels]
    false_positive = sum(bool(predictions[index]) for index in empty_gold)
    rate = false_positive / len(empty_gold) if empty_gold else 0.0
    return EmptyGroundTruthRisk(len(empty_gold), false_positive, rate)


def _complete_logits(values: Mapping[AssertionLabel, float]) -> Mapping[AssertionLabel, float]:
    frozen = _frozen_labels(values)
    return MappingProxyType({label: float(frozen.get(label, 0.0)) for label in AssertionLabel})


def _label_mapping(value: object, name: str) -> Mapping[AssertionLabel, float]:
    if not isinstance(value, dict):
        raise ValueError(f"calibration {name} must be an object")
    return {AssertionLabel(label): float(score) for label, score in value.items()}


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _logit(probability: float) -> float:
    bounded = min(max(probability, 1e-6), 1.0 - 1e-6)
    return math.log(bounded / (1.0 - bounded))
