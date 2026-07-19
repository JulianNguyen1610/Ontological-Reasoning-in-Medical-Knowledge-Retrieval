from __future__ import annotations

from medlink_ie.decoding.joint import (
    CalibratedEntityScores,
    CandidateRule,
    DecoderConfig,
    EntityTypeRule,
    JointDecoderInput,
    LabelRule,
    OverlapRelationship,
    UtilityWeights,
    decode_entities,
)
from medlink_ie.domain import AssertionLabel, DecisionTrace, EntityHypothesis, EntityType


def _config(**overrides: object) -> DecoderConfig:
    types = {
        entity_type: EntityTypeRule(
            entity_threshold=0.50,
            type_threshold=0.50,
            link_threshold=0.50,
            candidate_threshold=0.50,
        )
        for entity_type in EntityType
    }
    labels = {label: LabelRule(0.50) for label in AssertionLabel}
    values: dict[str, object] = {
        "utility": UtilityWeights(
            entity_reward=1.0,
            false_positive_penalty=1.0,
            type_reward=1.0,
            wrong_type_penalty=2.0,
            assertion_reward=1.0,
            assertion_false_positive_penalty=1.0,
            candidate_reward=1.0,
            extra_candidate_penalty=2.0,
        ),
        "type_rules": types,
        "label_rules": labels,
        "candidate_rule": CandidateRule(frozenset({EntityType.DIAGNOSIS, EntityType.MEDICATION})),
        "applicable_assertions": {
            entity_type: frozenset(AssertionLabel) for entity_type in EntityType
        },
        "minimum_keep_utility": 0.0,
    }
    values.update(overrides)
    return DecoderConfig(**values)  # type: ignore[arg-type]


def _input(
    identifier: str,
    *,
    span: float = 0.9,
    types: dict[EntityType, float] | None = None,
    assertions: dict[AssertionLabel, float] | None = None,
    link: float = 0.9,
    candidates: dict[str, float] | None = None,
) -> JointDecoderInput:
    entity_type_probabilities = types or {EntityType.DIAGNOSIS: 0.9}
    hypothesis = EntityHypothesis(
        0,
        4,
        "test",
        (),
        {},
        entity_type_probabilities,
        assertions or {},
        {},
        (),
        DecisionTrace(("input",)),
    )
    return JointDecoderInput(
        identifier,
        hypothesis,
        CalibratedEntityScores(
            span, entity_type_probabilities, assertions or {}, link, candidates or {}
        ),
    )


def test_low_type_confidence_abstains_by_dropping_entity() -> None:
    result = decode_entities((_input("low-type", types={EntityType.DIAGNOSIS: 0.49}),), _config())

    assert not result.decisions[0].kept
    assert result.decisions[0].reason == "no_type_meets_threshold"


def test_high_span_with_low_link_keeps_entity_and_abstains_from_candidates() -> None:
    result = decode_entities(
        (_input("weak-link", link=0.49, candidates={"ICD:A": 0.99}),), _config()
    )

    assert result.entities[0].candidates is None
    assert "candidate_abstained" in result.decisions[0].trace


def test_empty_assertions_are_valid_independent_abstention() -> None:
    result = decode_entities((_input("no-assertions"),), _config())

    assert result.entities[0].assertions == ()
    assert "assertions_empty" in result.decisions[0].trace


def test_extra_candidate_penalty_selects_only_positive_utility_candidates() -> None:
    result = decode_entities(
        (_input("candidates", candidates={"ICD:GOOD": 0.95, "ICD:EXTRA": 0.55}),), _config()
    )

    assert result.entities[0].candidates == ("ICD:GOOD",)
    assert result.decisions[0].utility.candidate_utility > 0.0


def test_conflicting_type_evidence_uses_configured_double_penalty() -> None:
    result = decode_entities(
        (
            _input(
                "conflict",
                types={EntityType.DIAGNOSIS: 0.60, EntityType.SYMPTOM: 0.59},
            ),
        ),
        _config(),
    )

    assert result.entities[0].type is EntityType.DIAGNOSIS
    assert "type_selected:CHẨN_ĐOÁN" in result.decisions[0].trace


def test_deterministic_ties_and_conflicting_overlaps() -> None:
    inputs = (_input("b"), _input("a"))
    overlap = (OverlapRelationship("a", "b", compatible=False),)

    first = decode_entities(inputs, _config(), overlap)
    second = decode_entities(tuple(reversed(inputs)), _config(), tuple(reversed(overlap)))

    assert first == second
    assert [decision.hypothesis_id for decision in first.decisions if decision.kept] == ["a"]
    assert (
        next(item for item in first.decisions if item.hypothesis_id == "b").reason
        == "overlap_conflict:a"
    )
