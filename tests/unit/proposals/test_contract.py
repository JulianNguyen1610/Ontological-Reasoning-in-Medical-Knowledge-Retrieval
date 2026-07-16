from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from medlink_ie.domain import ProposalSource, SourceDocument, TextView
from medlink_ie.proposals import (
    DecisionTrace,
    DecisionTraceEvent,
    MockSpanProposer,
    ProposalContext,
    ProposalEvidence,
    SourceTrust,
    SourceTrustConfiguration,
    SpanProposal,
    SpanProposer,
    make_proposal_id,
)


@pytest.fixture
def context() -> ProposalContext:
    document = SourceDocument("note-1", b"BN ho", "BN ho", "utf-8", False, "none")
    raw_view = TextView("raw", document.raw_text, (0, 1, 2, 3, 4, 5))
    return ProposalContext(
        document=document,
        text_views={raw_view.name: raw_view},
        source_trust=SourceTrustConfiguration(
            {ProposalSource.SPAN_MODEL: SourceTrust(0.7, True)}
        ),
    )


def test_span_proposer_protocol_and_mock_are_view_relative(
    context: ProposalContext,
) -> None:
    evidence = ProposalEvidence("model_span", "tiny-span", "2026.07", {"window": 128})
    proposal = SpanProposal.create(
        context=context,
        source=ProposalSource.SPAN_MODEL,
        producer_version="tiny-span@2026.07",
        view_name="raw",
        view_start=3,
        view_end=5,
        score=0.8,
        evidence=(evidence,),
    )
    proposer = MockSpanProposer(
        name="integration-mock",
        source=ProposalSource.SPAN_MODEL,
        version="mock-1",
        proposals=(proposal,),
    )

    assert isinstance(proposer, SpanProposer)
    assert proposer.propose(context) == (proposal,)
    assert proposal.proposed_text == "ho"
    assert proposal.view_name == "raw"
    assert not hasattr(proposal, "raw_start")
    assert not hasattr(proposal, "proposed_type")


def test_proposal_id_is_deterministic_and_changes_with_provenance(
    context: ProposalContext,
) -> None:
    evidence = (ProposalEvidence("rule_match", "rule-42", "1.0", {"lexicon": "local"}),)
    first = make_proposal_id(
        context, ProposalSource.SPAN_MODEL, "model-1", "raw", 3, 5, evidence
    )
    second = make_proposal_id(
        context, ProposalSource.SPAN_MODEL, "model-1", "raw", 3, 5, evidence
    )
    changed = make_proposal_id(
        context, ProposalSource.SPAN_MODEL, "model-2", "raw", 3, 5, evidence
    )

    assert first == second
    assert first != changed


def test_contract_serialization_is_stable_and_privacy_safe(
    context: ProposalContext,
) -> None:
    evidence = ProposalEvidence("rule_match", "medication-token", "1.0", {"rule": "R1"})
    proposal = SpanProposal.create(
        context, ProposalSource.SPAN_MODEL, "model-1", "raw", 3, 5, 0.8, (evidence,)
    )
    trace = DecisionTrace().record(
        DecisionTraceEvent.create(
            subject_id=proposal.proposal_id,
            stage="proposal",
            action="kept",
            source=proposal.source,
            producer_version=proposal.producer_version,
            score=proposal.score,
            evidence=proposal.evidence,
            reason="valid_view_span",
        )
    )

    assert proposal.to_json() == proposal.to_json()
    assert trace.to_json() == trace.to_json()
    assert "BN ho" not in trace.to_json()
    assert "proposed_text" not in trace.to_json()
    with pytest.raises(ValueError, match="privacy-safe"):
        ProposalEvidence("rule_match", "rule-1", "1", {"raw_text": "BN ho"})
    with pytest.raises(FrozenInstanceError):
        proposal.score = 0.1  # type: ignore[misc]


def test_context_rejects_unknown_view_and_mock_rejects_wrong_source(
    context: ProposalContext,
) -> None:
    with pytest.raises(ValueError, match="unknown text view"):
        SpanProposal.create(
            context, ProposalSource.SPAN_MODEL, "model-1", "missing", 0, 1, 0.5, ()
        )

    proposal = SpanProposal.create(
        context, ProposalSource.SPAN_MODEL, "model-1", "raw", 3, 5, 0.5, ()
    )
    proposer = MockSpanProposer("mock", ProposalSource.LAB_RULES, "1", (proposal,))
    with pytest.raises(ValueError, match="source"):
        proposer.propose(context)
