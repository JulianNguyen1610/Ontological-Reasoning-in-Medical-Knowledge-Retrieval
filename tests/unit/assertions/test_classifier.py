from __future__ import annotations

import pytest

from medlink_ie.assertions.classifier import (
    AssertionClassificationConfig,
    AssertionClassifierInput,
    AssertionDecisionEngine,
    CalibratedAssertionClassifier,
    CalibrationArtifact,
    DeterministicMockAssertionClassifier,
    HardMaskPolicy,
    RuleFeatures,
    WeightedRuleModelFusion,
    empty_ground_truth_risk,
)
from medlink_ie.domain import AssertionLabel, EntityType


def _input(entity_type: EntityType = EntityType.SYMPTOM) -> AssertionClassifierInput:
    return AssertionClassifierInput("không ho", 6, 8, entity_type)


def test_model_rule_disagreement_is_fused_with_a_trace() -> None:
    classifier = DeterministicMockAssertionClassifier({AssertionLabel.NEGATED: -2.0})
    engine = AssertionDecisionEngine(
        CalibratedAssertionClassifier(classifier, CalibrationArtifact.identity("test-v1")),
        WeightedRuleModelFusion(rule_weight=0.9),
        AssertionClassificationConfig(
            thresholds={AssertionLabel.NEGATED: 0.70}, minimum_evidence=0.0
        ),
    )

    result = engine.classify(_input(), RuleFeatures({AssertionLabel.NEGATED: 1.0}, ("cue-1",)))

    negated = result.by_label[AssertionLabel.NEGATED]
    assert negated.included
    assert any(trace.startswith("fusion:") for trace in negated.trace)
    assert result.raw_logits[AssertionLabel.NEGATED] == -2.0


def test_type_hard_mask_rejects_an_otherwise_high_label() -> None:
    classifier = DeterministicMockAssertionClassifier({AssertionLabel.NEGATED: 8.0})
    mask = HardMaskPolicy({EntityType.TEST_NAME: frozenset({AssertionLabel.NEGATED})})
    engine = AssertionDecisionEngine(
        CalibratedAssertionClassifier(classifier, CalibrationArtifact.identity("test-v1")),
        WeightedRuleModelFusion(),
        AssertionClassificationConfig(minimum_evidence=0.0),
        mask,
    )

    result = engine.classify(_input(EntityType.TEST_NAME), RuleFeatures())
    decision = result.by_label[AssertionLabel.NEGATED]
    assert not decision.included
    assert decision.reason == "hard_mask:type"
    assert result.assertions == ()


def test_missing_calibration_artifact_fails_explicitly(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        CalibrationArtifact.load(tmp_path / "missing-calibration.json")


def test_per_label_thresholds_are_applied_independently() -> None:
    classifier = DeterministicMockAssertionClassifier(
        {AssertionLabel.NEGATED: 1.0, AssertionLabel.HISTORICAL: 1.0}
    )
    config = AssertionClassificationConfig(
        thresholds={AssertionLabel.NEGATED: 0.70, AssertionLabel.HISTORICAL: 0.80},
        minimum_evidence=0.0,
    )
    engine = AssertionDecisionEngine(
        CalibratedAssertionClassifier(classifier, CalibrationArtifact.identity("test-v1")),
        WeightedRuleModelFusion(rule_weight=0.0),
        config,
    )

    result = engine.classify(_input(), RuleFeatures())
    assert AssertionLabel.NEGATED in result.assertions
    assert AssertionLabel.HISTORICAL not in result.assertions
    assert result.by_label[AssertionLabel.HISTORICAL].reason == "below_threshold"


def test_mock_inference_is_deterministic_and_empty_risk_is_measured() -> None:
    classifier = DeterministicMockAssertionClassifier({AssertionLabel.FAMILY: 0.5})
    assert classifier.predict_logits(_input()) == classifier.predict_logits(_input())

    risk = empty_ground_truth_risk(((), (AssertionLabel.NEGATED,)), ((AssertionLabel.FAMILY,), ()))
    assert risk.empty_gold_count == 1
    assert risk.false_positive_on_empty_gold == 1
    assert risk.rate == 1.0


def test_insufficient_evidence_abstains_with_a_rejection_trace_for_every_label() -> None:
    engine = AssertionDecisionEngine(
        CalibratedAssertionClassifier(
            DeterministicMockAssertionClassifier(), CalibrationArtifact.identity("test-v1")
        ),
        WeightedRuleModelFusion(),
    )

    result = engine.classify(_input())

    assert result.assertions == ()
    assert result.trace == ("abstained:insufficient_evidence",)
    assert all(item.reason == "abstain:insufficient_evidence" for item in result.by_label.values())
