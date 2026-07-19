from __future__ import annotations

from medlink_ie.domain import EntityType
from medlink_ie.evaluation.ontology_ablation import (
    AblationCase,
    AblationConfig,
    run_ontology_ablation,
)
from medlink_ie.linking.candidate_fusion import FusedCandidate, StructuredFeatures
from medlink_ie.linking.ontology import (
    GateConfig,
    OntologyConcept,
    OntologyRequest,
    OntologyRerankerConfig,
    OntologySnapshot,
    ScoreAdjustments,
)


def test_ablation_compares_all_variants_and_keeps_feature_disabled_without_stable_gain() -> None:
    candidate = FusedCandidate("RxNorm", "good", {}, 0.9, (), {})
    request = OntologyRequest(
        EntityType.MEDICATION,
        (candidate,),
        exact_match=True,
        alias_ambiguity=1,
        hierarchy_conflict=False,
        structured_features=StructuredFeatures.empty(),
        model_uncertainty=0.1,
    )
    config = OntologyRerankerConfig(
        True,
        "gated",
        GateConfig(1, 0.2, 1, 0.2),
        ScoreAdjustments(0.0, 0.0, 0.0, 0.0, False),
    )
    case = AblationCase(
        "case",
        (
            {
                "text": "drug",
                "type": EntityType.MEDICATION.value,
                "position": [0, 4],
                "candidates": ["good"],
            },
        ),
        (
            {
                "text": "drug",
                "type": EntityType.MEDICATION.value,
                "position": [0, 4],
                "candidates": ["good"],
            },
        ),
        0,
        request,
    )

    report = run_ontology_ablation(
        (case,),
        OntologySnapshot({("RxNorm", "good"): OntologyConcept("RxNorm", "good")}),
        config,
        AblationConfig(minimum_score_delta=0.001, latency_penalty_per_ms=0.0),
    )

    assert {variant.name for variant in report.variants} == {"off", "always_on", "gated_on"}
    assert not report.merge.enabled
    assert report.merge.reason == "insufficient_stable_score_delta"
