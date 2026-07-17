from __future__ import annotations

from medlink_ie.domain import GroundingMethod, SourceDocument, TextView
from medlink_ie.grounding import GroundingConfig, ground_proposal
from medlink_ie.normalization.text_views import build_text_views
from medlink_ie.proposals import ProposalContext, ProposalEvidence, SpanProposal


def _proposal(
    text: str, needle: str, start: int | None = None
) -> tuple[ProposalContext, SpanProposal]:
    document = SourceDocument("note", text.encode(), text, "utf-8", False, "none")
    context = ProposalContext(document, build_text_views(document))
    start = text.index(needle) if start is None else start
    proposal = SpanProposal.create(
        context,
        __import__("medlink_ie.domain", fromlist=["ProposalSource"]).ProposalSource.SPAN_MODEL,
        "test",
        "raw",
        start,
        start + len(needle),
        0.9,
        (ProposalEvidence("rule_match", "test-rule", "1", {}),),
    )
    return context, proposal


def test_unique_exact_and_repeated_mentions_preserve_raw_slice() -> None:
    context, proposal = _proposal("ho, rồi ho", "ho", 8)
    grounded = ground_proposal(proposal, context)
    assert grounded is not None
    assert grounded.method is GroundingMethod.EXACT_RAW
    assert grounded.text == context.document.raw_text[grounded.raw_start : grounded.raw_end]
    assert len(grounded.candidate_occurrences) == 2


def test_case_token_and_overlap_no_match_ambiguity_and_fuzzy_disabled() -> None:
    context, proposal = _proposal("Amlodipine 5 mg", "Amlodipine")
    context = ProposalContext(
        context.document,
        {
            "raw": TextView(
                "raw", context.document.raw_text, tuple(range(len(context.document.raw_text) + 1))
            )
        },
    )
    lower = SpanProposal.create(
        context,
        proposal.source,
        "test",
        "raw",
        0,
        10,
        0.9,
        (ProposalEvidence("rule_match", "test-rule", "1", {}),),
    )
    object.__setattr__(lower, "proposed_text", "amlodipine")
    assert ground_proposal(lower, context).method is GroundingMethod.CASE_INSENSITIVE
    assert ground_proposal(proposal, context, occupied=((0, 10),)) is None
    assert ground_proposal(lower, context, expected_position=None) is not None
    assert ground_proposal(lower, context, config=GroundingConfig()) is not None
