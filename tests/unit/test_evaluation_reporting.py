from __future__ import annotations

from medlink_ie.annotation.gold import GoldEntity, GoldSample
from medlink_ie.domain import AssertionLabel, EntityType
from medlink_ie.evaluation.reporting import (
    PredictionEntity,
    PredictionSample,
    RunManifest,
    compare_runs,
    evaluate_predictions,
)


def _gold() -> GoldSample:
    return GoldSample(
        "sample-1",
        "không ho amlodipine",
        None,
        (
            GoldEntity("ho", 6, 8, EntityType.SYMPTOM, (AssertionLabel.NEGATED,)),
            GoldEntity("amlodipine", 9, 19, EntityType.MEDICATION, (), ("rx-1",)),
        ),
    )


def _manifest(run_id: str) -> RunManifest:
    return RunManifest.create(
        run_id=run_id,
        config={"threshold": 0.5},
        data_manifests={"test": "data-sha"},
        model_artifacts={"model": "model-sha"},
        terminology_snapshot="terminology-sha",
        code_commit="abc123",
        seed=7,
        environment={"python": "3.11"},
        feature_flags={"rules": True},
    )


def test_evaluation_is_traceable_and_reports_metrics_without_text() -> None:
    prediction = PredictionSample(
        "sample-1",
        (
            PredictionEntity("ho", 6, 8, EntityType.SYMPTOM, ()),
            PredictionEntity(
                "amlodipine",
                9,
                19,
                EntityType.MEDICATION,
                (),
                ("rx-2",),
                ("rx-2", "rx-1"),
            ),
        ),
        latency_ms=12.5,
    )

    report = evaluate_predictions((_gold(),), (prediction,), _manifest("run-a"))

    assert report.extraction_by_type[EntityType.SYMPTOM.value].f1 == 1.0
    assert report.assertions.by_label["isNegated"].recall == 0.0
    assert report.linking.recall_at_k[2] == 1.0
    assert report.linking.mrr == 0.5
    assert report.system.failure_count == 0
    assert report.error_taxonomy["assertion_label_error"]
    assert report.error_taxonomy["linking_miss"]
    assert "không ho" not in report.to_markdown()
    assert report.to_dict()["scorer"]["traces"] == ["sample-1"]


def test_run_comparison_uses_paired_bootstrap_and_changed_error_buckets() -> None:
    gold = (_gold(),)
    baseline = evaluate_predictions(
        gold,
        (PredictionSample("sample-1", ()),),
        _manifest("baseline"),
    )
    candidate = evaluate_predictions(
        gold,
        (
            PredictionSample(
                "sample-1",
                (
                    PredictionEntity("ho", 6, 8, EntityType.SYMPTOM),
                    PredictionEntity(
                        "amlodipine", 9, 19, EntityType.MEDICATION, candidates=("rx-1",)
                    ),
                ),
            ),
        ),
        _manifest("candidate"),
    )

    comparison = compare_runs(baseline, candidate, bootstrap_samples=100, seed=3)

    assert comparison.delta_final_score > 0
    assert comparison.statistically_relevant
    assert comparison.changed_error_buckets["missing_entity"] < 0
