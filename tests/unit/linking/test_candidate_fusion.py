from __future__ import annotations

import json
from pathlib import Path

from medlink_ie.linking.candidate_fusion import (
    CandidateInput,
    CandidateSetOracleObservation,
    FusionConfig,
    StructuredFeatures,
    evaluate_candidate_set_oracle,
    fuse_and_select,
    generate_hard_negatives,
)


def _config() -> FusionConfig:
    return FusionConfig(
        {"exact_alias": 0.7, "bm25": 0.1, "ngram": 0.1, "dense": 0.05, "reranker": 0.05},
        minimum_confidence=0.3,
        artifact_checksum="fixture",
    )


def test_unique_and_ambiguous_aliases_preserve_channel_scores() -> None:
    unique = CandidateInput("ICD-10", "A", {"exact_alias": 1.0, "bm25": 0.5}, {}, ("exact",))
    selected = fuse_and_select((unique,), _config(), StructuredFeatures.empty())
    assert [candidate.concept_id for candidate in selected.candidates] == ["A"]
    assert selected.candidates[0].channel_scores == {"exact_alias": 1.0, "bm25": 0.5}

    ambiguous = (
        CandidateInput("ICD-10", "A", {"exact_alias": 0.8}, {}, ("exact",)),
        CandidateInput("ICD-10", "B", {"exact_alias": 0.8}, {}, ("exact",)),
    )
    selected = fuse_and_select(ambiguous, _config(), StructuredFeatures.empty())
    assert [candidate.concept_id for candidate in selected.candidates] == ["A", "B"]


def test_missing_strength_does_not_filter_but_explicit_conflict_does() -> None:
    candidates = (
        CandidateInput(
            "RXNORM",
            "five",
            {"exact_alias": 0.9},
            {"ingredients": ["drug"], "strengths": ["5"]},
            (),
        ),
        CandidateInput(
            "RXNORM",
            "ten",
            {"exact_alias": 0.9},
            {"ingredients": ["drug"], "strengths": ["10"]},
            (),
        ),
    )
    missing = fuse_and_select(
        candidates, _config(), StructuredFeatures("medication", {"ingredients": ["drug"]})
    )
    assert [item.concept_id for item in missing.candidates] == ["five", "ten"]

    explicit = fuse_and_select(
        candidates,
        _config(),
        StructuredFeatures("medication", {"ingredients": ["drug"], "strengths": ["5"]}),
    )
    assert [item.concept_id for item in explicit.candidates] == ["five"]
    assert explicit.rejected[0].concept_id == "ten"


def test_combination_extra_jaccard_penalty_and_abstention() -> None:
    candidates = (
        CandidateInput("RXNORM", "combo", {"exact_alias": 0.9}, {"ingredients": ["a", "b"]}, ()),
        CandidateInput("RXNORM", "single", {"exact_alias": 0.9}, {"ingredients": ["a"]}, ()),
        CandidateInput("RXNORM", "extra", {"exact_alias": 0.1}, {"ingredients": ["a", "b"]}, ()),
    )
    selected = fuse_and_select(
        candidates, _config(), StructuredFeatures("medication", {"ingredients": ["a", "b"]})
    )
    assert [item.concept_id for item in selected.candidates] == ["combo"]
    assert selected.utility > 0

    abstained = fuse_and_select(
        (CandidateInput("ICD-10", "low", {"bm25": 0.1}, {}, ()),),
        _config(),
        StructuredFeatures.empty(),
    )
    assert abstained.candidates == ()


def test_config_artifact_and_hard_negatives(tmp_path: Path) -> None:
    path = tmp_path / "fusion.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "weights": {"exact_alias": 1.0}, "minimum_confidence": 0.2}
        ),
        encoding="utf-8",
    )
    assert FusionConfig.load(path).artifact_checksum
    catalog = (
        CandidateInput("ICD-10", "parent", {}, {"parent_id": None}, ()),
        CandidateInput("ICD-10", "gold", {}, {"parent_id": "parent"}, ()),
        CandidateInput("ICD-10", "sibling", {}, {"parent_id": "parent"}, ()),
        CandidateInput("ICD-10", "child", {}, {"parent_id": "gold"}, ()),
        CandidateInput(
            "RXNORM",
            "rx_gold",
            {},
            {"ingredients": ["a"], "strengths": ["5"], "forms": ["tab"]},
            (),
        ),
        CandidateInput(
            "RXNORM",
            "rx_strength",
            {},
            {"ingredients": ["a"], "strengths": ["10"], "forms": ["tab"]},
            (),
        ),
    )
    negatives = generate_hard_negatives((("ICD-10", "gold"), ("RXNORM", "rx_gold")), catalog)
    assert [item.concept_id for item in negatives] == ["child", "parent", "sibling", "rx_strength"]


def test_oracle_analysis_separates_pool_coverage_from_final_set_jaccard() -> None:
    candidates = (
        CandidateInput("RXNORM", "right", {"exact_alias": 0.9}, {}, ()),
        CandidateInput("RXNORM", "extra", {"exact_alias": 0.8}, {}, ()),
    )
    selection = fuse_and_select(candidates, _config(), StructuredFeatures.empty())
    analysis = evaluate_candidate_set_oracle(
        (
            CandidateSetOracleObservation(
                "one",
                (("RXNORM", "right"),),
                selection,
            ),
            CandidateSetOracleObservation("two", (), selection),
        )
    )
    assert analysis.sample_count == 2
    assert analysis.retrieval_oracle_recall == 1.0
    assert analysis.final_candidate_jaccard == 0.25
    assert analysis.exact_set_rate == 0.0


def test_hard_negative_identity_keeps_same_id_in_another_terminology() -> None:
    catalog = (
        CandidateInput("ICD-10", "shared", {}, {"parent_id": "root"}, ()),
        CandidateInput("ICD-10", "sibling", {}, {"parent_id": "root"}, ()),
        CandidateInput("RXNORM", "shared", {}, {"ingredients": ["drug"]}, ()),
    )
    negatives = generate_hard_negatives((("ICD-10", "shared"),), catalog)
    assert [(item.terminology, item.concept_id) for item in negatives] == [("ICD-10", "sibling")]
