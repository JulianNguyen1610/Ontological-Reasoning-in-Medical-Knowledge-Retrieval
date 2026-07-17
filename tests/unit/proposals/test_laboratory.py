from __future__ import annotations

from medlink_ie.domain import SourceDocument
from medlink_ie.normalization.text_views import build_text_views
from medlink_ie.proposals import ProposalContext
from medlink_ie.proposals.laboratory import (
    FrozenLaboratoryTestLexicon,
    LaboratoryResultProposer,
    LaboratorySpanProposer,
    LaboratoryTest,
    LaboratoryTestNameProposer,
)
from medlink_ie.structure.analyzer import StructuralAnalyzer

LEXICON = FrozenLaboratoryTestLexicon(
    version="test-1",
    tests=(
        LaboratoryTest("glucose", "Glucose"),
        LaboratoryTest("sodium", "Na"),
        LaboratoryTest("potassium", "K"),
        LaboratoryTest("wbc", "WBC"),
        LaboratoryTest("covid-pcr", "SARS-CoV-2 PCR"),
    ),
)


def _propose(text: str):
    document = SourceDocument("lab-note", text.encode(), text, "utf-8", False, "none")
    structure = StructuralAnalyzer().analyze(document)
    return LaboratorySpanProposer(LEXICON).propose(
        ProposalContext(document, build_text_views(document), structure=structure)
    )


def _of_kind(proposals, kind: str):
    return [p for p in proposals if p.evidence[0].metadata["proposal_kind"] == kind]


def test_single_test_and_decimal_value_with_unit() -> None:
    proposals = _propose("Glucose: 5.4 mmol/L H")

    assert [proposal.proposed_text for proposal in _of_kind(proposals, "test_name")] == ["Glucose"]
    result = _of_kind(proposals, "test_result")[0]
    assert result.proposed_text == "5.4 mmol/L H"
    assert result.evidence[0].metadata["has_result_test_proposal_id"]


def test_test_name_and_result_proposers_emit_separate_proposal_kinds() -> None:
    text = "Glucose: 5.4 mmol/L"
    document = SourceDocument("lab-note", text.encode(), text, "utf-8", False, "none")
    context = ProposalContext(
        document, build_text_views(document), structure=StructuralAnalyzer().analyze(document)
    )

    assert [p.proposed_text for p in LaboratoryTestNameProposer(LEXICON).propose(context)] == [
        "Glucose"
    ]
    assert [p.proposed_text for p in LaboratoryResultProposer(LEXICON).propose(context)] == [
        "5.4 mmol/L"
    ]


def test_multiple_tests_one_line_and_multiple_lines_pair_locally() -> None:
    proposals = _propose("Na 140 mmol/L; K 4,2 mmol/L\nWBC 12.0 G/L L")

    assert [proposal.proposed_text for proposal in _of_kind(proposals, "test_name")] == [
        "Na",
        "K",
        "WBC",
    ]
    assert [proposal.proposed_text for proposal in _of_kind(proposals, "test_result")] == [
        "140 mmol/L",
        "4,2 mmol/L",
        "12.0 G/L L",
    ]


def test_qualitative_and_unitless_results_are_proposed() -> None:
    proposals = _propose("SARS-CoV-2 PCR: không phát hiện\nGlucose cao")

    assert [proposal.proposed_text for proposal in _of_kind(proposals, "test_result")] == [
        "không phát hiện",
        "cao",
    ]


def test_ranges_and_inequalities_are_single_result_spans() -> None:
    proposals = _propose("Glucose >= 7,0 mmol/L; Na 135-145 mmol/L")

    assert [proposal.proposed_text for proposal in _of_kind(proposals, "test_result")] == [
        ">= 7,0 mmol/L",
        "135-145 mmol/L",
    ]


def test_units_without_test_and_medication_dosage_are_negative() -> None:
    assert _of_kind(_propose("5.4 mmol/L; amlodipine 5 mg po daily"), "test_result") == []


def test_parenthesized_reference_range_is_excluded_by_framework_policy() -> None:
    proposals = _propose("Glucose 5.4 mmol/L (3.9-5.6)")

    assert [proposal.proposed_text for proposal in _of_kind(proposals, "test_result")] == [
        "5.4 mmol/L"
    ]


def test_ambiguous_nearest_neighbor_is_deterministic() -> None:
    proposals = _propose("Na K 140 mmol/L")
    tests = _of_kind(proposals, "test_name")
    result = _of_kind(proposals, "test_result")[0]

    assert result.evidence[0].metadata["has_result_test_proposal_id"] == tests[1].proposal_id
    assert "lab.pair.nearest" in result.evidence[0].metadata["rule_ids"]
