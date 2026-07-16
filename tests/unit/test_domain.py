from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from medlink_ie.domain import (
    AssertionLabel,
    DecisionTrace,
    EntityHypothesis,
    EntityType,
    FinalEntity,
    GroundedSpan,
    GroundingMethod,
    ProposalSource,
    SourceDocument,
    SpanProposal,
    TextView,
)


@pytest.fixture
def document() -> SourceDocument:
    return SourceDocument("note-1", b"BN ho", "BN ho", "utf-8", False, "none")


def test_valid_construction_and_immutable_containers(document: SourceDocument) -> None:
    view = TextView("raw", document.raw_text, (0, 1, 2, 3, 4, 5))
    proposal = SpanProposal(
        "proposal-1",
        ProposalSource.MEDICATION_RULES,
        view.name,
        "ho",
        EntityType.SYMPTOM,
        3,
        5,
        3,
        5,
        "ho",
        0.8,
    )
    grounded = GroundedSpan("proposal-1", 3, 5, "ho", GroundingMethod.EXACT_RAW, 1.0)
    trace = DecisionTrace(("exact_grounded", "type_accepted"))
    hypothesis = EntityHypothesis(
        3,
        5,
        "ho",
        (ProposalSource.MEDICATION_RULES,),
        {ProposalSource.MEDICATION_RULES: 0.8},
        {EntityType.SYMPTOM: 0.9},
        {AssertionLabel.NEGATED: 0.1},
        {"section": "exam"},
        (),
        trace,
    )
    entity = FinalEntity("ho", EntityType.SYMPTOM, (3, 5), (), None)

    assert proposal.source is ProposalSource.MEDICATION_RULES
    assert grounded.method is GroundingMethod.EXACT_RAW
    assert hypothesis.decision_trace == trace
    entity.validate_semantics(document)
    with pytest.raises(FrozenInstanceError):
        entity.text = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        document.metadata["new"] = "value"


@pytest.mark.parametrize("interval", [(-1, 1), (0, -1), (2, 1), (1, 1)])
def test_all_invalid_interval_boundaries_are_rejected(interval: tuple[int, int]) -> None:
    start, end = interval
    with pytest.raises(ValueError):
        SpanProposal(
            "proposal-1",
            ProposalSource.SPAN_MODEL,
            "raw",
            "ho",
            None,
            start,
            end,
            None,
            None,
            None,
            0.5,
        )
    with pytest.raises(ValueError):
        GroundedSpan("proposal-1", start, end, "ho", GroundingMethod.EXACT_RAW, 0.5)
    with pytest.raises(ValueError):
        EntityHypothesis(start, end, "ho", (), {}, {}, {}, {}, (), DecisionTrace(()))
    with pytest.raises(ValueError):
        FinalEntity("ho", EntityType.SYMPTOM, interval, (), None)


def test_incomplete_optional_intervals_are_rejected() -> None:
    with pytest.raises(ValueError, match="both be set"):
        SpanProposal(
            "proposal-1",
            ProposalSource.SPAN_MODEL,
            "raw",
            "ho",
            None,
            0,
            None,
            None,
            None,
            None,
            0.5,
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_invalid_confidences_are_rejected(confidence: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        SpanProposal(
            "proposal-1",
            ProposalSource.SPAN_MODEL,
            "raw",
            "ho",
            None,
            None,
            None,
            None,
            None,
            None,
            confidence,
        )
    with pytest.raises(ValueError, match="between 0 and 1"):
        GroundedSpan("proposal-1", 0, 2, "ho", GroundingMethod.EXACT_RAW, confidence)
    with pytest.raises(ValueError, match="between 0 and 1"):
        EntityHypothesis(
            0,
            2,
            "ho",
            (),
            {ProposalSource.SPAN_MODEL: confidence},
            {},
            {},
            {},
            (),
            DecisionTrace(()),
        )


def test_unsupported_enum_labels_are_rejected() -> None:
    with pytest.raises(TypeError, match="ProposalSource"):
        SpanProposal("proposal-1", "span_model", "raw", "ho", None, None, None, None, None, None, 0.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="EntityType"):
        FinalEntity("ho", "TRIỆU_CHỨNG", (0, 2), (), None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AssertionLabel"):
        FinalEntity("ho", EntityType.SYMPTOM, (0, 2), ("isNegated",), None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="GroundingMethod"):
        GroundedSpan("proposal-1", 0, 2, "ho", "exact_raw", 1.0)  # type: ignore[arg-type]


def test_serialization_is_deterministic() -> None:
    left = EntityHypothesis(
        0,
        2,
        "ho",
        (ProposalSource.SPAN_MODEL, ProposalSource.LAB_RULES),
        {ProposalSource.SPAN_MODEL: 0.7, ProposalSource.LAB_RULES: 0.8},
        {EntityType.TEST_NAME: 0.1, EntityType.SYMPTOM: 0.9},
        {},
        {"z": 1, "a": 2},
        (),
        DecisionTrace(("exact_grounded",)),
    )
    right = EntityHypothesis(
        0,
        2,
        "ho",
        (ProposalSource.SPAN_MODEL, ProposalSource.LAB_RULES),
        {ProposalSource.LAB_RULES: 0.8, ProposalSource.SPAN_MODEL: 0.7},
        {EntityType.SYMPTOM: 0.9, EntityType.TEST_NAME: 0.1},
        {},
        {"a": 2, "z": 1},
        (),
        DecisionTrace(("exact_grounded",)),
    )

    assert left.to_dict() == right.to_dict()
    assert left.to_json() == right.to_json()
    assert FinalEntity("ho", EntityType.SYMPTOM, (0, 2), (), None).to_json() == (
        '{"assertions":[],"candidates":null,"position":[0,2],"text":"ho","type":"TRIỆU_CHỨNG"}'
    )


def test_final_entity_detects_semantic_span_mismatch(document: SourceDocument) -> None:
    entity = FinalEntity("ho", EntityType.SYMPTOM, (0, 2), (), None)

    with pytest.raises(ValueError, match="does not match"):
        entity.validate_semantics(document)
    with pytest.raises(ValueError, match="outside"):
        FinalEntity("ho", EntityType.SYMPTOM, (3, 6), (), None).validate_semantics(document)
