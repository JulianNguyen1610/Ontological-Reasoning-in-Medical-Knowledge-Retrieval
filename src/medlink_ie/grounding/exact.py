"""Exact-first grounding with deterministic ambiguity abstention."""

from __future__ import annotations

import re
from dataclasses import dataclass

from medlink_ie.domain import GroundedSpan, GroundingCandidate, GroundingMethod
from medlink_ie.normalization.boundary_map import map_view_span
from medlink_ie.proposals.contract import ProposalContext, SpanProposal


@dataclass(frozen=True, slots=True)
class GroundingConfig:
    enable_fuzzy: bool = False


def ground_proposal(
    proposal: SpanProposal,
    context: ProposalContext,
    *,
    expected_position: tuple[int, int] | None = None,
    proposal_order: int = 0,
    occupied: tuple[tuple[int, int], ...] = (),
    config: GroundingConfig = GroundingConfig(),
) -> GroundedSpan | None:
    """Ground one proposal, abstaining when the best occurrence is not unique."""
    raw = context.document.raw_text
    expected = expected_position or map_view_span(
        context.view_for(proposal.view_name), proposal.view_start, proposal.view_end
    )
    occurrences = _occurrences(proposal, context)
    candidates: list[GroundingCandidate] = []
    for start, end, method in occurrences:
        if any(start < right and left < end for left, right in occupied):
            continue
        score = _score(start, end, expected, method, proposal_order)
        candidates.append(GroundingCandidate(start, end, score, method.value))
    if not candidates:
        return None
    candidates.sort(
        key=lambda candidate: (-candidate.score, candidate.raw_start, candidate.raw_end)
    )
    if len(candidates) > 1 and candidates[0].score == candidates[1].score:
        return None
    selected = candidates[0]
    method = next(
        method
        for start, end, method in occurrences
        if (start, end) == (selected.raw_start, selected.raw_end)
    )
    return GroundedSpan(
        proposal.proposal_id,
        selected.raw_start,
        selected.raw_end,
        raw[selected.raw_start : selected.raw_end],
        method,
        selected.score,
        tuple(candidates),
        "unique_best_candidate",
    )


def _occurrences(
    proposal: SpanProposal, context: ProposalContext
) -> list[tuple[int, int, GroundingMethod]]:
    raw = context.document.raw_text
    needle = proposal.proposed_text
    matches = [
        (match.start(), match.end(), GroundingMethod.EXACT_RAW)
        for match in re.finditer(re.escape(needle), raw)
    ]
    if matches:
        return matches
    view_matches: list[tuple[int, int, GroundingMethod]] = []
    for view in context.text_views.values():
        if view.name == "raw":
            continue
        for match in re.finditer(re.escape(needle), view.text):
            view_matches.append(
                (*map_view_span(view, match.start(), match.end()), GroundingMethod.EXACT_VIEW)
            )
    if view_matches:
        return _deduplicate(view_matches)
    matches = [
        (match.start(), match.end(), GroundingMethod.CASE_INSENSITIVE)
        for match in re.finditer(re.escape(needle), raw, re.IGNORECASE)
    ]
    if matches:
        return matches
    tokens = re.findall(r"\w+", needle.casefold())
    raw_tokens = list(re.finditer(r"\w+", raw))
    for index in range(len(raw_tokens) - len(tokens) + 1):
        if [
            token.group().casefold() for token in raw_tokens[index : index + len(tokens)]
        ] == tokens:
            matches.append(
                (
                    raw_tokens[index].start(),
                    raw_tokens[index + len(tokens) - 1].end(),
                    GroundingMethod.TOKEN_ALIGNED,
                )
            )
    return matches


def _deduplicate(
    occurrences: list[tuple[int, int, GroundingMethod]],
) -> list[tuple[int, int, GroundingMethod]]:
    unique: dict[tuple[int, int], tuple[int, int, GroundingMethod]] = {}
    for occurrence in occurrences:
        unique.setdefault(occurrence[:2], occurrence)
    return list(unique.values())


def _score(
    start: int,
    end: int,
    expected: tuple[int, int] | None,
    method: GroundingMethod,
    proposal_order: int,
) -> float:
    base = {
        GroundingMethod.EXACT_RAW: 0.8,
        GroundingMethod.EXACT_VIEW: 0.75,
        GroundingMethod.CASE_INSENSITIVE: 0.7,
        GroundingMethod.TOKEN_ALIGNED: 0.65,
    }[method]
    if expected is not None and (start, end) == expected:
        return min(1.0, base + 0.2)
    return (
        max(0.0, base - min(abs(start - expected[0]), 20) / 100 - min(proposal_order, 10) / 1000)
        if expected
        else base
    )
