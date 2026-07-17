"""Precision-first deterministic medication span proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass

from medlink_ie.domain import ProposalSource
from medlink_ie.proposals.contract import ProposalContext, ProposalEvidence, SpanProposal
from medlink_ie.structure.analyzer import ListItem

_COMPONENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "strength",
        re.compile(
            r"\d+(?:[.,]\d+)?(?:\s*[/\-]\s*\d+(?:[.,]\d+)?)?\s*-?\s*(?:mcg|mg|g|mL|ml|%)", re.I
        ),
    ),
    (
        "form",
        re.compile(
            r"(?:enteric-coated\s+tablet|tablet|tab|capsule|cap|viên|ống|gói|syrup|solution|suspension|cream|gel|drops?)\b",
            re.I,
        ),
    ),
    ("route", re.compile(r"(?:po|iv|im|sc|oral|uống|tiêm|truyền\s+tĩnh\s+mạch)\b", re.I)),
    (
        "frequency",
        re.compile(
            r"(?:qd|bid|tid|qhs|qam|q\d+h)(?::prn)?\b|prn\b|daily\b|khi\s+sốt\b|mỗi\s+(?:\d+\s+giờ|ngày)\b|\d+\s*(?:lần|x)\s*/\s*(?:ngày|day)\b",
            re.I,
        ),
    ),
    ("release", re.compile(r"(?:XR|XL|SR|CR|ER)\b", re.I)),
)
_COMBINATION = re.compile(r"\s*(?:\+|/|và|and)\s*", re.I)


@dataclass(frozen=True, slots=True)
class MedicationAlias:
    """A terminology-derived medication alias; no terminology code is carried here."""

    text: str
    alias_id: str

    def __post_init__(self) -> None:
        if not self.text or not self.alias_id:
            raise ValueError("medication alias text and alias_id must be non-empty")


@dataclass(frozen=True, slots=True)
class MedicationAliasLexicon:
    """Immutable, frozen alias input for a medication proposer."""

    aliases: tuple[MedicationAlias, ...]

    def __post_init__(self) -> None:
        aliases = tuple(self.aliases)
        if not aliases:
            raise ValueError("medication alias lexicon must not be empty")
        if any(not isinstance(alias, MedicationAlias) for alias in aliases):
            raise TypeError("aliases must contain MedicationAlias values")
        object.__setattr__(self, "aliases", aliases)


@dataclass(frozen=True, slots=True)
class MedicationSpanProposer:
    """Emit raw-view medication proposals without grounding, coding, or assertions."""

    lexicon: MedicationAliasLexicon
    name: str = "medication-rules"
    source: ProposalSource = ProposalSource.MEDICATION_RULES
    version: str = "framework-v1"

    def propose(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        raw = context.view_for("raw")
        if raw.text != context.document.raw_text:
            raise ValueError("raw text view must equal SourceDocument.raw_text")
        if not context.source_trust.trust_for(self.source).enabled:
            return ()

        proposals: list[SpanProposal] = []
        occupied: list[tuple[int, int]] = []
        for alias in sorted(
            self.lexicon.aliases, key=lambda item: (-len(item.text), item.text.casefold())
        ):
            for match in re.finditer(re.escape(alias.text), raw.text, re.I):
                if not _token_boundary(raw.text, match.start(), match.end()):
                    continue
                item = _list_item_at(context, match.start())
                start, end, kinds, spans = _extend_medication(
                    raw.text,
                    match.start(),
                    match.end(),
                    self.lexicon,
                    item.content_end if item is not None else len(raw.text),
                )
                if any(
                    start < other_end and other_start < end for other_start, other_end in occupied
                ):
                    continue
                evidence = ProposalEvidence(
                    "rule_match",
                    "med-001",
                    self.version,
                    {
                        "alias_id": alias.alias_id,
                        "component_kinds": kinds,
                        "component_spans": spans,
                        "confidence_tier": "high",
                        "list_item_id": item.unit_id if item is not None else None,
                        "list_rule_ids": list(item.rule_ids) if item is not None else [],
                    },
                )
                proposals.append(
                    SpanProposal.create(
                        context, self.source, self.version, "raw", start, end, 0.98, (evidence,)
                    )
                )
                occupied.append((start, end))
        return tuple(
            sorted(
                proposals,
                key=lambda proposal: (proposal.view_start, proposal.view_end, proposal.proposal_id),
            )
        )


def _extend_medication(
    text: str, start: int, end: int, lexicon: MedicationAliasLexicon, limit: int
) -> tuple[int, int, list[str], list[list[int]]]:
    kinds: list[str] = []
    spans: list[list[int]] = [[start, end]]
    position = end
    while position < limit:
        whitespace = re.match(r"[ \t]+", text[position:])
        candidate = position + (whitespace.end() if whitespace else 0)
        component = next(
            (
                (kind, pattern.match(text, candidate))
                for kind, pattern in _COMPONENTS
                if pattern.match(text, candidate)
            ),
            None,
        )
        if component is not None:
            kind, match = component
            assert match is not None
            if match.end() > limit:
                break
            position = match.end()
            kinds.append(kind)
            spans.append([candidate, position])
            continue
        connector = _COMBINATION.match(text, position)
        if connector is not None:
            alias_end = _alias_end_at(text, connector.end(), lexicon)
            if alias_end is not None and alias_end <= limit:
                alias_start = connector.end()
                position = alias_end
                kinds.append("combination")
                spans.append([alias_start, position])
                continue
        break
    return start, position, kinds, spans


def _alias_end_at(text: str, start: int, lexicon: MedicationAliasLexicon) -> int | None:
    for alias in sorted(lexicon.aliases, key=lambda item: -len(item.text)):
        match = re.match(re.escape(alias.text), text[start:], re.I)
        if match is not None and _token_boundary(text, start, start + match.end()):
            return start + match.end()
    return None


def _token_boundary(text: str, start: int, end: int) -> bool:
    return (start == 0 or not text[start - 1].isalnum()) and (
        end == len(text) or not text[end].isalnum()
    )


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
