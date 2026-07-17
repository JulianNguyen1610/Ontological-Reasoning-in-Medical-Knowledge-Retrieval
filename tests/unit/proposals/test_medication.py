from __future__ import annotations

from medlink_ie.domain import SourceDocument, TextView
from medlink_ie.proposals.contract import ProposalContext
from medlink_ie.proposals.medication import (
    MedicationAlias,
    MedicationAliasLexicon,
    MedicationSpanProposer,
)
from medlink_ie.structure.analyzer import StructuralAnalyzer


def _context(text: str) -> ProposalContext:
    document = SourceDocument("med-note", text.encode(), text, "utf-8", False, "none")
    raw = TextView("raw", text, tuple(range(len(text) + 1)))
    return ProposalContext(document, {"raw": raw})


def _proposer(*aliases: str) -> MedicationSpanProposer:
    return MedicationSpanProposer(
        MedicationAliasLexicon(
            tuple(MedicationAlias(alias, alias.replace(" ", "-")) for alias in aliases)
        )
    )


def test_medication_proposer_assembles_framework_components_and_preserves_internal_colon() -> None:
    proposals = _proposer("clonazepam").propose(_context("Dùng clonazepam 0.5 mg po qam:prn.\n"))

    assert [proposal.proposed_text for proposal in proposals] == ["clonazepam 0.5 mg po qam:prn"]
    assert proposals[0].evidence[0].identifier == "med-001"
    assert proposals[0].evidence[0].metadata["component_kinds"] == [
        "strength",
        "route",
        "frequency",
    ]


def test_medication_proposer_keeps_combination_and_separate_strengths_positionally_distinct() -> (
    None
):
    text = "amoxicillin + clavulanate 875 mg po bid; clonazepam 0.5 mg, clonazepam 1 mg"
    proposals = _proposer("amoxicillin", "clavulanate", "clonazepam").propose(_context(text))

    assert [proposal.proposed_text for proposal in proposals] == [
        "amoxicillin + clavulanate 875 mg po bid",
        "clonazepam 0.5 mg",
        "clonazepam 1 mg",
    ]
    assert proposals[0].evidence[0].metadata["component_kinds"] == [
        "combination",
        "strength",
        "route",
        "frequency",
    ]


def test_medication_proposer_stops_before_indication() -> None:
    text = "0.5 mg; aspirin 81 mg để phòng đột quỵ."
    proposals = _proposer("aspirin").propose(_context(text))

    assert [proposal.proposed_text for proposal in proposals] == ["aspirin 81 mg"]


def test_medication_proposer_does_not_extend_across_newline() -> None:
    proposals = _proposer("aspirin").propose(_context("aspirin\n81 mg po bid"))

    assert [proposal.proposed_text for proposal in proposals] == ["aspirin"]


def test_medication_proposer_uses_list_item_content_and_evidence() -> None:
    text = "1. aspirin 81 mg po daily\n2. clonazepam 0.5 mg po qam:prn\n"
    document = SourceDocument("med-list", text.encode(), text, "utf-8", False, "lf")
    raw = TextView("raw", text, tuple(range(len(text) + 1)))
    context = ProposalContext(
        document, {"raw": raw}, structure=StructuralAnalyzer().analyze(document)
    )

    proposals = _proposer("aspirin", "clonazepam").propose(context)

    assert [proposal.proposed_text for proposal in proposals] == [
        "aspirin 81 mg po daily",
        "clonazepam 0.5 mg po qam:prn",
    ]
    assert [proposal.evidence[0].metadata["list_item_id"] for proposal in proposals] == [
        "list_item:0",
        "list_item:1",
    ]
    assert proposals[0].evidence[0].metadata["list_rule_ids"] == ["list.numbered"]


def test_medication_proposer_is_deterministic_and_uses_raw_view_coordinates() -> None:
    context = _context("- Amlodipine 10 mg po daily\r\n")
    proposer = _proposer("amlodipine")

    first = proposer.propose(context)
    second = proposer.propose(context)

    assert first == second
    assert first[0].view_name == "raw"
    assert first[0].proposed_text == "Amlodipine 10 mg po daily"
