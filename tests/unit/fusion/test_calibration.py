from __future__ import annotations

from pathlib import Path

import pytest

from medlink_ie.domain import EntityType, ProposalSource
from medlink_ie.fusion.calibration import (
    CalibrationConfig,
    CalibrationMethod,
    CalibrationPoint,
    FusionConfig,
    FusionInput,
    SourceAwareFusion,
    evaluate_calibration,
    fit_calibration,
    load_calibration_artifact,
    write_calibration_artifact,
)


def _points() -> tuple[CalibrationPoint, ...]:
    return tuple(
        CalibrationPoint(
            f"p{index}",
            f"g{index}",
            "oof",
            ProposalSource.SPAN_MODEL,
            EntityType.SYMPTOM,
            logit,
            label,
        )
        for index, (logit, label) in enumerate(((-3.0, 0), (-1.0, 0), (1.0, 1), (3.0, 1)))
    )


def _held_out_points() -> tuple[CalibrationPoint, ...]:
    return tuple(
        CalibrationPoint(
            f"held-{index}",
            f"held-group-{index}",
            "dev",
            ProposalSource.SPAN_MODEL,
            EntityType.SYMPTOM,
            logit,
            label,
        )
        for index, (logit, label) in enumerate(((-2.0, 0), (2.0, 1)))
    )


@pytest.mark.parametrize("method", tuple(CalibrationMethod))
def test_oof_calibrators_create_reliable_artifacts_and_reject_seen_groups(
    method: CalibrationMethod, tmp_path: Path
) -> None:
    artifact = fit_calibration(_points(), CalibrationConfig(method=method, version="v1"))
    value = artifact.calibrate(ProposalSource.SPAN_MODEL, EntityType.SYMPTOM, 2.0)
    report = evaluate_calibration(artifact, _held_out_points(), bins=2)

    assert 0.0 <= value <= 1.0
    assert report.expected_calibration_error >= 0.0
    with pytest.raises(ValueError, match="used to fit"):
        evaluate_calibration(artifact, (_points()[0],), bins=2)
    path = write_calibration_artifact(tmp_path / "calibration.json", artifact)
    assert load_calibration_artifact(path) == artifact
    path.write_text(path.read_text(encoding="utf-8").replace("v1", "v2"), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_calibration_artifact(path)


def test_calibration_rejects_train_test_group_leakage_and_single_class() -> None:
    with pytest.raises(ValueError, match="dev or oof"):
        fit_calibration(
            (
                CalibrationPoint(
                    "x", "g", "test", ProposalSource.SPAN_MODEL, EntityType.SYMPTOM, 0.0, 1
                ),
            ),
            CalibrationConfig(),
        )
    with pytest.raises(ValueError, match="both positive and negative"):
        fit_calibration(
            tuple(
                CalibrationPoint(
                    str(index),
                    f"g{index}",
                    "dev",
                    ProposalSource.SPAN_MODEL,
                    EntityType.SYMPTOM,
                    1.0,
                    1,
                )
                for index in range(2)
            ),
            CalibrationConfig(),
        )


def test_source_aware_rule_fusion_handles_missing_scores_and_per_type_thresholds() -> None:
    artifact = fit_calibration(_points(), CalibrationConfig(method=CalibrationMethod.TEMPERATURE))
    fusion = SourceAwareFusion(
        artifact,
        FusionConfig(
            implementation_key="rule",
            source_weights={ProposalSource.SPAN_MODEL: 1.0, ProposalSource.LLM_PROPOSER: 0.5},
            per_type_thresholds={EntityType.SYMPTOM: 0.4},
            missing_source_policy="zero",
        ),
    )
    result = fusion.fuse(
        FusionInput(
            "candidate-1",
            EntityType.SYMPTOM,
            {ProposalSource.SPAN_MODEL: 2.0, ProposalSource.LLM_PROPOSER: None},
        )
    )

    assert result.missing_sources == (ProposalSource.LLM_PROPOSER,)
    assert result.accepted is True
    assert result.source_reliability[ProposalSource.SPAN_MODEL] > 0.0
    missing_class = fusion.fuse(
        FusionInput("candidate-2", EntityType.TEST_NAME, {ProposalSource.SPAN_MODEL: 2.0})
    )
    assert missing_class.source_reliability == {}
    assert missing_class.missing_sources == (ProposalSource.SPAN_MODEL,)


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_fusion_rejects_non_finite_weights_and_logits(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        FusionConfig(source_weights={ProposalSource.SPAN_MODEL: value})
    with pytest.raises(ValueError, match="finite"):
        FusionInput("candidate", EntityType.SYMPTOM, {ProposalSource.SPAN_MODEL: value})
