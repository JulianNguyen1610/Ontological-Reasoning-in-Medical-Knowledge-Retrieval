from __future__ import annotations

from medlink_ie.domain import SourceDocument
from medlink_ie.normalization.text_views import build_text_views
from medlink_ie.proposals import ProposalContext
from medlink_ie.proposals.concepts import (
    ApprovedConceptAlias,
    ConceptSpanProposer,
    FrozenConceptAliasLexicon,
)
from medlink_ie.structure.analyzer import StructuralAnalyzer

LEXICON = FrozenConceptAliasLexicon(
    version="test-1",
    aliases=(
        ApprovedConceptAlias("chest-pain", "đau ngực", ("symptom",)),
        ApprovedConceptAlias("hypertension", "tăng huyết áp", ("diagnosis",)),
        ApprovedConceptAlias("diabetes", "đái tháo đường", ("diagnosis",)),
        ApprovedConceptAlias("shortness-of-breath", "khó thở", ("symptom",)),
        ApprovedConceptAlias("htn", "THA", ("diagnosis",)),
        ApprovedConceptAlias("ambiguous-pain", "đau", ("symptom", "diagnosis")),
    ),
)


def _propose(text: str):
    document = SourceDocument("concept-note", text.encode(), text, "utf-8", False, "none")
    structure = StructuralAnalyzer().analyze(document)
    return ConceptSpanProposer(LEXICON).propose(
        ProposalContext(document, build_text_views(document), structure=structure)
    )


def _distribution(proposal):
    return proposal.evidence[0].metadata["provisional_type_distribution"]


def test_symptom_diagnosis_minimal_pair_uses_reversible_evidence() -> None:
    proposals = _propose("BN đau ngực. Được chẩn đoán tăng huyết áp.")

    assert [proposal.proposed_text for proposal in proposals] == ["đau ngực", "tăng huyết áp"]
    assert _distribution(proposals[0])["symptom"] > _distribution(proposals[0])["diagnosis"]
    assert _distribution(proposals[1])["diagnosis"] > _distribution(proposals[1])["symptom"]
    assert not hasattr(proposals[1], "final_type")


def test_diagnosis_trigger_and_complaint_context_are_recorded() -> None:
    proposals = _propose("Lý do nhập viện: đau ngực. BN được chẩn đoán tăng huyết áp.")

    diagnosis = proposals[1]
    assert diagnosis.evidence[0].metadata["trigger_spans"]
    assert diagnosis.evidence[0].metadata["local_context_ids"]["clause_id"]


def test_family_and_rule_out_mentions_are_retained_without_assertions() -> None:
    proposals = _propose("Family history\nmẹ bị đái tháo đường. Không loại trừ tăng huyết áp.")

    assert [proposal.proposed_text for proposal in proposals] == ["đái tháo đường", "tăng huyết áp"]
    assert proposals[0].evidence[0].metadata["local_context_ids"]["section_id"]
    assert "assertion" not in proposals[0].evidence[0].metadata


def test_repeated_aliases_abbreviations_and_punctuation_are_positionally_distinct() -> None:
    proposals = _propose("THA, sau đó tăng huyết áp; THA.")

    assert [proposal.proposed_text for proposal in proposals] == ["THA", "tăng huyết áp", "THA"]
    assert len({proposal.proposal_id for proposal in proposals}) == 3


def test_headings_and_administrative_phrases_are_not_proposed() -> None:
    assert _propose("Diagnosis\nPatient administration\n") == ()
