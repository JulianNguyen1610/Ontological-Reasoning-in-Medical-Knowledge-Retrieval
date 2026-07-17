"""Deterministic framework_v1 laboratory proposals and local pair evidence.

The proposer emits source-level proposal kinds only; it does not assign a final
entity type or serialize a relation into competition output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from medlink_ie.domain import ProposalSource
from medlink_ie.proposals.contract import ProposalContext, ProposalEvidence, SpanProposal
from medlink_ie.structure.analyzer import Clause, ListItem

LAB_TEST_NAME = "test_name"
LAB_TEST_RESULT = "test_result"

_UNITS = r"(?:mmol/L|mg/dL|g/L|G/L|U/L|IU/L|mIU/L|ng/mL|pg/mL|%|10\^?\d+/L)"
_NUMBER = r"(?:(?:[<>≤≥]|<=|>=)\s*)?\d+(?:[.,]\d+)?"
_RANGE = rf"{_NUMBER}(?:\s*[-–]\s*{_NUMBER})?"
_NUMERIC_RESULT = re.compile(
    rf"(?<![\w.])(?P<value>{_RANGE})(?:\s*(?P<unit>{_UNITS}))?(?:\s+(?P<flag>H|L))?(?!\w)",
    re.IGNORECASE,
)
_QUALITATIVE_RESULT = re.compile(
    r"\b(?:tăng|giảm|cao|thấp|dương\s+tính|âm\s+tính|không\s+phát\s+hiện)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class LaboratoryTest:
    """A frozen local test-name alias without terminology identifiers or codes."""

    test_id: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.test_id, str) or not self.test_id:
            raise ValueError("test_id must be a non-empty string")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be a non-empty string")


@dataclass(frozen=True, slots=True)
class FrozenLaboratoryTestLexicon:
    """Immutable local test-name aliases used only for exact deterministic matching."""

    version: str
    tests: tuple[LaboratoryTest, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("version must be a non-empty string")
        object.__setattr__(self, "tests", tuple(self.tests))
        if not self.tests:
            raise ValueError("tests must not be empty")
        if any(not isinstance(test, LaboratoryTest) for test in self.tests):
            raise TypeError("tests must contain LaboratoryTest values")


@dataclass(frozen=True, slots=True)
class LaboratoryTestNameProposer:
    """Emit exact local laboratory test-name proposals only."""

    lexicon: FrozenLaboratoryTestLexicon
    name: str = "laboratory-test-name-rules"
    source: ProposalSource = ProposalSource.LAB_RULES
    version: str = "framework-v1"

    def propose(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        return _LaboratoryRules(self.lexicon, self.source, self.version).test_proposals(context)


@dataclass(frozen=True, slots=True)
class LaboratoryResultProposer:
    """Emit result proposals only, with internal evidence for the nearest test."""

    lexicon: FrozenLaboratoryTestLexicon
    name: str = "laboratory-result-rules"
    source: ProposalSource = ProposalSource.LAB_RULES
    version: str = "framework-v1"

    def propose(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        rules = _LaboratoryRules(self.lexicon, self.source, self.version)
        return rules.result_proposals(context, rules.test_proposals(context))


@dataclass(frozen=True, slots=True)
class LaboratorySpanProposer:
    """Emit local test-name and result proposals with internal pair evidence."""

    lexicon: FrozenLaboratoryTestLexicon
    name: str = "laboratory-rules"
    source: ProposalSource = ProposalSource.LAB_RULES
    version: str = "framework-v1"

    def propose(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        rules = _LaboratoryRules(self.lexicon, self.source, self.version)
        tests = rules.test_proposals(context)
        results = rules.result_proposals(context, tests)
        return tuple(
            sorted(
                (*tests, *results),
                key=lambda proposal: (proposal.view_start, proposal.view_end, proposal.proposal_id),
            )
        )


@dataclass(frozen=True, slots=True)
class _LaboratoryRules:
    """Shared deterministic matching implementation for the two public proposers."""

    lexicon: FrozenLaboratoryTestLexicon
    source: ProposalSource
    version: str

    def test_proposals(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        raw = context.view_for("raw")
        if raw.text != context.document.raw_text:
            raise ValueError("raw text view must equal SourceDocument.raw_text")
        if not context.source_trust.trust_for(self.source).enabled:
            return ()
        text = context.document.raw_text
        proposals: list[SpanProposal] = []
        for test in sorted(
            self.lexicon.tests, key=lambda item: (-len(item.text), item.text.casefold())
        ):
            for match in re.finditer(re.escape(test.text), text, re.IGNORECASE):
                if not _token_boundary(text, match.start(), match.end()):
                    continue
                item = _list_item_at(context, match.start())
                evidence = ProposalEvidence(
                    "rule_match",
                    "lab-test-alias",
                    self.version,
                    {
                        "component_spans": [[match.start(), match.end()]],
                        "matched_test": test.text,
                        "proposal_kind": LAB_TEST_NAME,
                        "rule_ids": ["lab.test_alias"],
                        "test_id": test.test_id,
                        "list_item_id": item.unit_id if item is not None else None,
                    },
                )
                proposals.append(
                    SpanProposal.create(
                        context,
                        self.source,
                        self.version,
                        "raw",
                        match.start(),
                        match.end(),
                        0.98,
                        (evidence,),
                    )
                )
        return tuple(
            sorted(proposals, key=lambda proposal: (proposal.view_start, proposal.view_end))
        )

    def result_proposals(
        self, context: ProposalContext, tests: tuple[SpanProposal, ...]
    ) -> tuple[SpanProposal, ...]:
        text = context.document.raw_text
        candidates = [*self._numeric_candidates(text), *self._qualitative_candidates(text)]
        results: list[SpanProposal] = []
        for start, end, pattern, component_spans in sorted(candidates):
            if any(start < test.view_end and test.view_start < end for test in tests):
                continue
            paired = _nearest_compatible_test(context, tests, start, end)
            if paired is None:
                continue
            item = _list_item_at(context, start)
            evidence = ProposalEvidence(
                "rule_match",
                "lab-result-pattern",
                self.version,
                {
                    "component_spans": component_spans,
                    "has_result_test_proposal_id": paired.proposal_id,
                    "list_item_id": item.unit_id if item is not None else None,
                    "pairing_scope": _scope_name(context, start, end),
                    "proposal_kind": LAB_TEST_RESULT,
                    "rule_ids": ["lab.result." + pattern, "lab.pair.nearest"],
                },
            )
            results.append(
                SpanProposal.create(
                    context, self.source, self.version, "raw", start, end, 0.96, (evidence,)
                )
            )
        return tuple(results)

    def _numeric_candidates(self, text: str) -> tuple[tuple[int, int, str, list[list[int]]], ...]:
        candidates: list[tuple[int, int, str, list[list[int]]]] = []
        for match in _NUMERIC_RESULT.finditer(text):
            start, end = match.span()
            if _is_parenthesized_reference_range(text, start, end):
                continue
            components = [list(match.span("value"))]
            if match.group("unit") is not None:
                components.append(list(match.span("unit")))
            if match.group("flag") is not None:
                components.append(list(match.span("flag")))
            pattern = (
                "range" if "-" in match.group("value") or "–" in match.group("value") else "numeric"
            )
            if match.group("value").lstrip().startswith(("<", ">", "≤", "≥")):
                pattern = "inequality"
            candidates.append((start, end, pattern, components))
        return tuple(candidates)

    def _qualitative_candidates(
        self, text: str
    ) -> tuple[tuple[int, int, str, list[list[int]]], ...]:
        return tuple(
            (match.start(), match.end(), "qualitative", [[match.start(), match.end()]])
            for match in _QUALITATIVE_RESULT.finditer(text)
        )


def _nearest_compatible_test(
    context: ProposalContext, tests: tuple[SpanProposal, ...], start: int, end: int
) -> SpanProposal | None:
    scope = _scope_bounds(context, start, end)
    compatible = [
        proposal
        for proposal in tests
        if scope[0] <= proposal.view_start and proposal.view_end <= scope[1]
    ]
    if not compatible:
        return None
    return min(
        compatible,
        key=lambda proposal: (
            abs(start - proposal.view_end),
            -proposal.view_start,
            proposal.proposal_id,
        ),
    )


def _scope_bounds(context: ProposalContext, start: int, end: int) -> tuple[int, int]:
    item = _list_item_at(context, start)
    if item is not None and end <= item.content_end:
        return item.content_start, item.content_end
    clause = _clause_at(context, start)
    if clause is not None and end <= clause.end:
        return clause.start, clause.end
    text = context.document.raw_text
    return text.rfind("\n", 0, start) + 1, text.find("\n", end) if "\n" in text[end:] else len(text)


def _scope_name(context: ProposalContext, start: int, end: int) -> str:
    item = _list_item_at(context, start)
    if item is not None and end <= item.content_end:
        return "list_item"
    clause = _clause_at(context, start)
    if clause is not None and end <= clause.end:
        return "clause"
    return "line"


def _list_item_at(context: ProposalContext, start: int) -> ListItem | None:
    if context.structure is None:
        return None
    return next(
        (
            item
            for item in context.structure.list_items
            if item.content_start <= start < item.content_end
        ),
        None,
    )


def _clause_at(context: ProposalContext, start: int) -> Clause | None:
    if context.structure is None:
        return None
    return next(
        (clause for clause in context.structure.clauses if clause.start <= start < clause.end), None
    )


def _is_parenthesized_reference_range(text: str, start: int, end: int) -> bool:
    return start > 0 and text[start - 1] == "(" and end < len(text) and text[end] == ")"


def _token_boundary(text: str, start: int, end: int) -> bool:
    return (start == 0 or not text[start - 1].isalnum()) and (
        end == len(text) or not text[end].isalnum()
    )
