"""Reversible deterministic symptom/diagnosis concept proposal evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeVar

from medlink_ie.domain import ProposalSource
from medlink_ie.proposals.contract import ProposalContext, ProposalEvidence, SpanProposal
from medlink_ie.structure.analyzer import Clause, ListItem, Section, Sentence

_StructuralUnitT = TypeVar("_StructuralUnitT", Section, ListItem, Sentence, Clause)

_DIAGNOSIS_TRIGGERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("concept.trigger.diagnosis", re.compile(r"\b(?:được\s+)?chẩn\s+đoán\b", re.IGNORECASE)),
    ("concept.trigger.diagnosis", re.compile(r"\bdiagnosis\b", re.IGNORECASE)),
)
_SYMPTOM_LEXICAL = re.compile(r"^(?:đau|khó|mệt|ho|sốt|chóng\s+mặt)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ApprovedConceptAlias:
    """An approved exact alias with reversible source-level type evidence."""

    concept_id: str
    text: str
    supported_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.concept_id, str) or not self.concept_id:
            raise ValueError("concept_id must be a non-empty string")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be a non-empty string")
        object.__setattr__(self, "supported_kinds", tuple(self.supported_kinds))
        if not self.supported_kinds or set(self.supported_kinds) - {"symptom", "diagnosis"}:
            raise ValueError("supported_kinds must contain symptom and/or diagnosis")


@dataclass(frozen=True, slots=True)
class FrozenConceptAliasLexicon:
    """Immutable local aliases; no ICD/RxNorm or final entity type is stored."""

    version: str
    aliases: tuple[ApprovedConceptAlias, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("version must be a non-empty string")
        object.__setattr__(self, "aliases", tuple(self.aliases))
        if not self.aliases:
            raise ValueError("aliases must not be empty")
        if any(not isinstance(alias, ApprovedConceptAlias) for alias in self.aliases):
            raise TypeError("aliases must contain ApprovedConceptAlias values")
        if len({alias.text.casefold() for alias in self.aliases}) != len(self.aliases):
            raise ValueError("aliases must have distinct case-insensitive text")


@dataclass(frozen=True, slots=True)
class ConceptSpanProposer:
    """Propose exact aliases with local, non-final symptom/diagnosis evidence."""

    lexicon: FrozenConceptAliasLexicon
    name: str = "concept-rules"
    source: ProposalSource = ProposalSource.CONCEPT_RULES
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
            for match in re.finditer(re.escape(alias.text), raw.text, re.IGNORECASE):
                start, end = match.span()
                if not _token_boundary(raw.text, start, end) or _is_heading(context, start, end):
                    continue
                if any(
                    start < other_end and other_start < end for other_start, other_end in occupied
                ):
                    continue
                clause = _clause_at(context, start)
                triggers = _trigger_spans(raw.text, clause, start, end)
                distribution = _distribution(alias, raw.text[start:end], bool(triggers))
                evidence = ProposalEvidence(
                    "rule_match",
                    "concept-alias",
                    self.version,
                    {
                        "component_spans": [[start, end]],
                        "concept_id": alias.concept_id,
                        "local_context_ids": _context_ids(context, start),
                        "matched_alias": alias.text,
                        "provisional_type_distribution": distribution,
                        "rule_ids": [
                            "concept.alias",
                            *(trigger["rule_id"] for trigger in triggers),
                        ],
                        "trigger_spans": triggers,
                    },
                )
                proposals.append(
                    SpanProposal.create(
                        context, self.source, self.version, "raw", start, end, 0.9, (evidence,)
                    )
                )
                occupied.append((start, end))
        return tuple(
            sorted(
                proposals,
                key=lambda proposal: (proposal.view_start, proposal.view_end, proposal.proposal_id),
            )
        )


def _distribution(
    alias: ApprovedConceptAlias, text: str, has_diagnosis_trigger: bool
) -> dict[str, float]:
    if len(alias.supported_kinds) == 1:
        primary = alias.supported_kinds[0]
        return {primary: 0.9, "diagnosis" if primary == "symptom" else "symptom": 0.1}
    if has_diagnosis_trigger:
        return {"diagnosis": 0.75, "symptom": 0.25}
    if _SYMPTOM_LEXICAL.search(text):
        return {"symptom": 0.75, "diagnosis": 0.25}
    return {"diagnosis": 0.5, "symptom": 0.5}


def _trigger_spans(
    text: str, clause: Clause | None, start: int, end: int
) -> list[dict[str, int | str]]:
    if clause is None:
        scope_start, scope_end = _line_bounds(text, start, end)
    else:
        scope_start, scope_end = clause.start, clause.end
    return [
        {"end": scope_start + match.end(), "rule_id": rule_id, "start": scope_start + match.start()}
        for rule_id, pattern in _DIAGNOSIS_TRIGGERS
        for match in pattern.finditer(text[scope_start:scope_end])
    ]


def _context_ids(context: ProposalContext, start: int) -> dict[str, str | None]:
    return {
        "clause_id": _unit_id(_clause_at(context, start)),
        "list_item_id": _unit_id(_list_item_at(context, start)),
        "section_id": _unit_id(_section_at(context, start)),
        "sentence_id": _unit_id(_sentence_at(context, start)),
    }


def _is_heading(context: ProposalContext, start: int, end: int) -> bool:
    return (
        any(
            section.heading_start < end and start < section.heading_end
            for section in context.structure.sections
        )
        if context.structure
        else False
    )


def _section_at(context: ProposalContext, start: int) -> Section | None:
    return _unit_at(context.structure.sections if context.structure else (), start)


def _list_item_at(context: ProposalContext, start: int) -> ListItem | None:
    return _unit_at(context.structure.list_items if context.structure else (), start)


def _sentence_at(context: ProposalContext, start: int) -> Sentence | None:
    return _unit_at(context.structure.sentences if context.structure else (), start)


def _clause_at(context: ProposalContext, start: int) -> Clause | None:
    return _unit_at(context.structure.clauses if context.structure else (), start)


def _unit_at(units: tuple[_StructuralUnitT, ...], start: int) -> _StructuralUnitT | None:
    return next((unit for unit in units if unit.start <= start < unit.end), None)


def _unit_id(unit: Section | ListItem | Sentence | Clause | None) -> str | None:
    return unit.unit_id if unit is not None else None


def _line_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    return text.rfind("\n", 0, start) + 1, text.find("\n", end) if "\n" in text[end:] else len(text)


def _token_boundary(text: str, start: int, end: int) -> bool:
    return (start == 0 or not text[start - 1].isalnum()) and (
        end == len(text) or not text[end].isalnum()
    )
