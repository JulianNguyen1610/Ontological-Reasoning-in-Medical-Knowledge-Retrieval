from __future__ import annotations

from medlink_ie.domain import EntityType
from medlink_ie.linking.candidate_fusion import FusedCandidate, StructuredFeatures
from medlink_ie.linking.ontology import (
    GateConfig,
    OntologyConcept,
    OntologyMode,
    OntologyRequest,
    OntologyReranker,
    OntologyRerankerConfig,
    OntologySnapshot,
    ScoreAdjustments,
)


def _candidate(concept_id: str, score: float) -> FusedCandidate:
    return FusedCandidate("RxNorm", concept_id, {}, score, (), {})


def _config(mode: OntologyMode) -> OntologyRerankerConfig:
    return OntologyRerankerConfig(
        enabled=True,
        mode=mode,
        gate=GateConfig(
            max_simple_candidates=1,
            minimum_simple_margin=0.30,
            maximum_simple_aliases=1,
            maximum_simple_uncertainty=0.20,
        ),
        adjustments=ScoreAdjustments(
            compatible_type_bonus=0.05,
            hierarchy_conflict_penalty=0.10,
            medication_match_bonus=0.20,
            medication_mismatch_penalty=0.30,
            hard_medication_ingredient_match=True,
        ),
    )


def _snapshot() -> OntologySnapshot:
    return OntologySnapshot(
        {
            ("RxNorm", "good"): OntologyConcept(
                "RxNorm", "good", ingredient="clonazepam", strength="0.5 mg", dose_form="tablet"
            ),
            ("RxNorm", "wrong"): OntologyConcept(
                "RxNorm", "wrong", ingredient="diazepam", strength="5 mg", dose_form="tablet"
            ),
        }
    )


def test_gate_is_off_for_unique_exact_match_and_high_margin_simple_case() -> None:
    request = OntologyRequest(
        EntityType.MEDICATION,
        (_candidate("good", 0.9),),
        exact_match=True,
        alias_ambiguity=1,
        hierarchy_conflict=False,
        structured_features=StructuredFeatures.empty(),
        model_uncertainty=0.1,
    )

    result = OntologyReranker(_snapshot(), _config(OntologyMode.GATED)).rerank(request)

    assert not result.applied
    assert result.gate_reason == "unique_exact_match"
    assert result.candidates == request.candidates


def test_gated_reranker_hard_filters_only_safe_medication_ingredient_mismatch() -> None:
    request = OntologyRequest(
        EntityType.MEDICATION,
        (_candidate("wrong", 0.9), _candidate("good", 0.7)),
        exact_match=False,
        alias_ambiguity=2,
        hierarchy_conflict=False,
        structured_features=StructuredFeatures(
            "medication", {"ingredient": ("clonazepam",), "strength": ("0.5 mg",)}
        ),
        model_uncertainty=0.5,
    )

    result = OntologyReranker(_snapshot(), _config(OntologyMode.GATED)).rerank(request)

    assert [candidate.concept_id for candidate in result.candidates] == ["good"]
    assert result.adjustments[0].reason == "hard_ingredient_mismatch"
    assert result.adjustments[-1].reason == "medication_feature_match"


def test_off_mode_is_a_no_ontology_fallback_and_snapshot_never_invents_candidates() -> None:
    request = OntologyRequest(
        EntityType.MEDICATION,
        (_candidate("good", 0.8),),
        exact_match=False,
        alias_ambiguity=2,
        hierarchy_conflict=False,
        structured_features=StructuredFeatures.empty(),
        model_uncertainty=0.8,
    )

    result = OntologyReranker(_snapshot(), _config(OntologyMode.OFF)).rerank(request)

    assert result.candidates == request.candidates
    assert result.adjustments == ()
