"""Public contract for pluggable span proposal sources."""

from medlink_ie.proposals.contract import (
    MockSpanProposer,
    ProposalContext,
    ProposalEvidence,
    SourceTrust,
    SourceTrustConfiguration,
    SpanProposal,
    SpanProposer,
    make_proposal_id,
)
from medlink_ie.proposals.tracing import DecisionTrace, DecisionTraceEvent

__all__ = [
    "DecisionTrace",
    "DecisionTraceEvent",
    "MockSpanProposer",
    "ProposalContext",
    "ProposalEvidence",
    "SourceTrust",
    "SourceTrustConfiguration",
    "SpanProposal",
    "SpanProposer",
    "make_proposal_id",
]
