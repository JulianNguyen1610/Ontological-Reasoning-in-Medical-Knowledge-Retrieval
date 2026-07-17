"""Deterministic assertion cues, structural scope, and entity association.

All coordinates are half-open offsets into the unmodified raw source text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from medlink_ie.domain import AssertionLabel
from medlink_ie.structure.analyzer import DocumentStructure, StructuralUnit


class ConfidenceTier(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class AssertionCueRecord:
    """A versioned cue rule; patterns run directly against raw text."""

    label: AssertionLabel
    language: str
    pattern: str
    direction: str
    allowed_structure_levels: tuple[str, ...]
    terminators: tuple[str, ...]
    blockers: tuple[str, ...]
    rule_id: str
    exclude_quoted_or_template: bool = True

    def __post_init__(self) -> None:
        if self.direction not in {"forward", "backward", "bidirectional"}:
            raise ValueError("cue direction must be forward, backward, or bidirectional")
        if not self.language or not self.pattern or not self.rule_id:
            raise ValueError("cue language, pattern, and rule_id must be non-empty")
        if not self.allowed_structure_levels:
            raise ValueError("cue allowed_structure_levels must not be empty")
        allowed = {"clause", "sentence", "list_item", "section", "document"}
        if not set(self.allowed_structure_levels) <= allowed:
            raise ValueError("cue allowed_structure_levels contains an unknown structure level")
        re.compile(self.pattern, re.IGNORECASE)
        for expression in (*self.terminators, *self.blockers):
            re.compile(expression, re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CueMatch:
    record: AssertionCueRecord
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class AssertionLexicon:
    """A named, immutable lexicon snapshot for reproducible assertion runs."""

    version: str
    records: tuple[AssertionCueRecord, ...]

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("lexicon version must be non-empty")
        object.__setattr__(self, "records", tuple(self.records))
        if not self.records:
            raise ValueError("lexicon records must not be empty")
        if any(not isinstance(record, AssertionCueRecord) for record in self.records):
            raise TypeError("lexicon records must contain AssertionCueRecord values")


@dataclass(frozen=True, slots=True)
class AssertionDecision:
    """Evidence for one cue-to-entity association; it never removes an entity."""

    label: AssertionLabel
    cue_span: tuple[int, int]
    cue_text: str
    scope_span: tuple[int, int]
    rule_id: str
    score: float
    confidence_tier: ConfidenceTier
    applies: bool = True
    source_unit_id: str | None = None
    inheritance_path: tuple[str, ...] = ()
    origin: str = "local"

    def __post_init__(self) -> None:
        if not 0 <= self.cue_span[0] < self.cue_span[1]:
            raise ValueError("cue_span must be a non-empty interval")
        if not 0 <= self.scope_span[0] < self.scope_span[1]:
            raise ValueError("scope_span must be a non-empty interval")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be in [0, 1]")
        object.__setattr__(self, "inheritance_path", tuple(self.inheritance_path))
        if self.origin not in {"local", "inherited", "exception"}:
            raise ValueError("origin must be local, inherited, or exception")

    def to_dict(self) -> dict[str, object]:
        return {
            "applies": self.applies,
            "confidence_tier": self.confidence_tier.value,
            "cue_span": self.cue_span,
            "cue_text": self.cue_text,
            "label": self.label.value,
            "rule_id": self.rule_id,
            "scope_span": self.scope_span,
            "score": self.score,
            "source_unit_id": self.source_unit_id,
            "inheritance_path": self.inheritance_path,
            "origin": self.origin,
        }


@dataclass(frozen=True, slots=True)
class AssertionComposition:
    """Unique applied labels with every contributing local/inherited trace retained."""

    labels: tuple[AssertionLabel, ...]
    evidence: tuple[AssertionDecision, ...]


def default_lexicon() -> AssertionLexicon:
    """Return immutable lexicon version 1; order is part of deterministic behavior."""

    local = ("clause", "sentence", "list_item", "section")
    terminators = (r"(?<!\w)(?:nhưng|tuy nhiên|however|but|ghi nhận)(?!\w)",)
    return AssertionLexicon(
        "1.0.0",
        (
            AssertionCueRecord(
                AssertionLabel.NEGATED,
                "vi",
                r"(?<!\w)không có(?!\w)",
                "forward",
                local,
                terminators,
                (),
                "assert.negation.vi.khong_co.v1",
            ),
            AssertionCueRecord(
                AssertionLabel.NEGATED,
                "vi",
                r"(?<!\w)chưa ghi nhận(?!\w)",
                "forward",
                local,
                terminators,
                (),
                "assert.negation.vi.chua_ghi_nhan.v1",
            ),
            AssertionCueRecord(
                AssertionLabel.NEGATED,
                "vi",
                r"(?<!\w)(?:phủ nhận|không)(?!\w)",
                "forward",
                local,
                terminators,
                (),
                "assert.negation.vi.general.v1",
            ),
            AssertionCueRecord(
                AssertionLabel.HISTORICAL,
                "vi",
                r"(?<!\w)tiền sử(?!\w)",
                "forward",
                ("list_item", "section"),
                (),
                (),
                "assert.history.vi.tien_su.v1",
            ),
            AssertionCueRecord(
                AssertionLabel.HISTORICAL,
                "vi",
                r"(?<!\w)trước nhập viện(?!\w)",
                "forward",
                ("list_item", "section"),
                (),
                (),
                "assert.history.vi.truoc_nhap_vien.v1",
            ),
            AssertionCueRecord(
                AssertionLabel.FAMILY,
                "vi",
                r"(?<!\w)(?:mẹ|bố|cha|anh|chị|em)(?!\w)",
                "forward",
                local,
                terminators,
                (),
                "assert.family.vi.relation.v1",
            ),
        ),
    )


class CueDetector:
    def __init__(
        self, lexicon: AssertionLexicon | Iterable[AssertionCueRecord] | None = None
    ) -> None:
        self.lexicon = default_lexicon() if lexicon is None else _coerce_lexicon(lexicon)

    def detect(self, raw_text: str) -> tuple[CueMatch, ...]:
        """Locate cues in raw text without rewriting it or changing offsets."""

        excluded = _excluded_ranges(raw_text)
        matches: list[CueMatch] = []
        for record in self.lexicon.records:
            for match in re.finditer(record.pattern, raw_text, re.IGNORECASE):
                if record.exclude_quoted_or_template and _is_excluded(
                    match.start(), match.end(), excluded
                ):
                    continue
                matches.append(
                    CueMatch(
                        record, match.start(), match.end(), raw_text[match.start() : match.end()]
                    )
                )
        return tuple(sorted(matches, key=lambda item: (item.start, item.end, item.record.rule_id)))


class ScopeBoundaryResolver:
    """Resolve cue scope using the narrowest permitted structural unit."""

    def resolve(
        self, cue: CueMatch, raw_text: str, structure: DocumentStructure | None
    ) -> tuple[int, int, str]:
        unit, level = _anchor_for(cue, raw_text, structure)
        start, end = unit.start, unit.end
        if level == "list_item" and structure is not None:
            end = _nested_list_descendant_end(unit, end, raw_text, structure)
        stop_patterns = (*cue.record.terminators, *cue.record.blockers)
        if cue.record.direction in {"forward", "bidirectional"}:
            stop = _nearest_after(raw_text, cue.end, end, stop_patterns)
            if stop is not None:
                end = stop
        if cue.record.direction in {"backward", "bidirectional"}:
            stop = _nearest_before(raw_text, start, cue.start, stop_patterns)
            if stop is not None:
                start = stop
        return start, end, level


class AssertionScopeEngine:
    """Associate every in-scope cue independently so entities may be multi-label."""

    def __init__(
        self, lexicon: AssertionLexicon | Iterable[AssertionCueRecord] | None = None
    ) -> None:
        self.detector = CueDetector(lexicon)
        self.resolver = ScopeBoundaryResolver()

    def classify(
        self,
        raw_text: str,
        entity_start: int,
        entity_end: int,
        structure: DocumentStructure | None = None,
    ) -> tuple[AssertionDecision, ...]:
        if not 0 <= entity_start < entity_end <= len(raw_text):
            raise ValueError("entity coordinates must be a non-empty interval in raw_text")
        decisions: list[AssertionDecision] = []
        for cue in self.detector.detect(raw_text):
            if _is_section_heading_cue(cue, structure):
                continue
            scope_start, scope_end, level = self.resolver.resolve(cue, raw_text, structure)
            if not _applies(cue, entity_start, entity_end, scope_start, scope_end):
                continue
            source_unit, _ = _anchor_for(cue, raw_text, structure)
            score = _association_score(cue, entity_start, entity_end, scope_start, scope_end, level)
            decisions.append(
                AssertionDecision(
                    cue.record.label,
                    (cue.start, cue.end),
                    cue.text,
                    (scope_start, scope_end),
                    cue.record.rule_id,
                    score,
                    _tier_for(score),
                    source_unit_id=source_unit.unit_id,
                    inheritance_path=(source_unit.unit_id,),
                )
            )
        exceptions = _current_medication_exceptions(raw_text, entity_start, entity_end, structure)
        decisions.extend(exceptions)
        blocked_inherited = {item.label for item in exceptions if not item.applies}
        decisions.extend(
            _section_propagation(
                raw_text,
                entity_start,
                entity_end,
                structure,
                blocked_inherited,
            )
        )
        return tuple(sorted(decisions, key=lambda item: (item.cue_span, item.rule_id)))

    def compose(self, decisions: Iterable[AssertionDecision]) -> AssertionComposition:
        """Deduplicate output labels while preserving all local and inherited evidence."""

        evidence = tuple(decisions)
        labels = tuple(
            sorted(
                {item.label for item in evidence if item.applies},
                key=lambda label: label.value,
            )
        )
        return AssertionComposition(labels, evidence)


def _anchor_for(
    cue: CueMatch, raw_text: str, structure: DocumentStructure | None
) -> tuple[StructuralUnit, str]:
    if structure is not None:
        by_level: tuple[tuple[str, tuple[StructuralUnit, ...]], ...] = (
            ("clause", structure.clauses),
            ("sentence", structure.sentences),
            ("list_item", structure.list_items),
            ("section", structure.sections),
        )
        for level, units in by_level:
            if level not in cue.record.allowed_structure_levels:
                continue
            unit = next((item for item in units if item.start <= cue.start < item.end), None)
            if unit is not None:
                return unit, level
    return StructuralUnit("document", 0, len(raw_text), raw_text, ("assert.document",)), "document"


def _is_section_heading_cue(cue: CueMatch, structure: DocumentStructure | None) -> bool:
    return structure is not None and any(
        section.heading_start <= cue.start and cue.end <= section.heading_end
        for section in structure.sections
    )


def _nested_list_descendant_end(
    source: StructuralUnit, end: int, raw_text: str, structure: DocumentStructure
) -> int:
    """Include only deeper-indented list descendants, never later siblings or other lists."""

    source_indent = _line_indent(raw_text, source.start)
    for item in sorted(structure.list_items, key=lambda value: value.start):
        if item.start < source.end:
            continue
        indent = _line_indent(raw_text, item.start)
        if indent <= source_indent:
            break
        end = max(end, item.end)
    return end


def _line_indent(raw_text: str, start: int) -> int:
    end = start
    while end < len(raw_text) and raw_text[end] in " \t":
        end += 1
    return end - start


def _section_propagation(
    raw_text: str,
    entity_start: int,
    entity_end: int,
    structure: DocumentStructure | None,
    blocked_labels: set[AssertionLabel],
) -> tuple[AssertionDecision, ...]:
    if structure is None:
        return ()
    label_by_section = {
        "medical_history": AssertionLabel.HISTORICAL,
        "medication_history": AssertionLabel.HISTORICAL,
        "family_history": AssertionLabel.FAMILY,
    }
    decisions: list[AssertionDecision] = []
    for section in structure.sections:
        label = label_by_section.get(section.label)
        if label is None or label in blocked_labels:
            continue
        if not (section.heading_end <= entity_start and entity_end <= section.end):
            continue
        decisions.append(
            AssertionDecision(
                label,
                (section.heading_start, section.heading_end),
                raw_text[section.heading_start : section.heading_end],
                (section.start, section.end),
                f"assert.propagation.{section.label}.v1",
                0.80,
                ConfidenceTier.MEDIUM,
                source_unit_id=section.unit_id,
                inheritance_path=(section.unit_id,),
                origin="inherited",
            )
        )
    return tuple(decisions)


def _current_medication_exceptions(
    raw_text: str,
    entity_start: int,
    entity_end: int,
    structure: DocumentStructure | None,
) -> tuple[AssertionDecision, ...]:
    """Suppress only inherited medication-history status in an explicit current-medication item."""

    if structure is None:
        return ()
    expression = r"(?<!\w)(?:thuốc hiện tại|current medications?)(?!\w)"
    decisions: list[AssertionDecision] = []
    for item in structure.list_items:
        if not (item.content_start <= entity_start and entity_end <= item.content_end):
            continue
        match = re.search(
            expression,
            raw_text[item.content_start : item.content_end],
            re.IGNORECASE,
        )
        if match is None:
            continue
        start = item.content_start + match.start()
        end = item.content_start + match.end()
        decisions.append(
            AssertionDecision(
                AssertionLabel.HISTORICAL,
                (start, end),
                raw_text[start:end],
                (item.content_start, item.content_end),
                "assert.exception.current_medication.v1",
                1.0,
                ConfidenceTier.HIGH,
                applies=False,
                source_unit_id=item.unit_id,
                inheritance_path=(item.unit_id,),
                origin="exception",
            )
        )
    return tuple(decisions)


def _applies(cue: CueMatch, start: int, end: int, scope_start: int, scope_end: int) -> bool:
    if not (scope_start <= start and end <= scope_end):
        return False
    if cue.record.direction == "forward":
        return cue.end <= start
    if cue.record.direction == "backward":
        return end <= cue.start
    return end <= cue.start or cue.end <= start


def _association_score(
    cue: CueMatch, start: int, end: int, scope_start: int, scope_end: int, level: str
) -> float:
    base = {"clause": 0.96, "sentence": 0.91, "list_item": 0.86, "section": 0.80}.get(level, 0.70)
    distance = start - cue.end if cue.end <= start else cue.start - end
    span_width = max(1, scope_end - scope_start)
    return max(0.50, round(base - min(0.20, 0.20 * distance / span_width), 3))


def _tier_for(score: float) -> ConfidenceTier:
    if score >= 0.85:
        return ConfidenceTier.HIGH
    if score >= 0.70:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW


def _nearest_after(text: str, start: int, end: int, patterns: tuple[str, ...]) -> int | None:
    positions = [
        match.start()
        for pattern in patterns
        for match in re.finditer(pattern, text[start:end], re.IGNORECASE)
    ]
    return start + min(positions) if positions else None


def _nearest_before(text: str, start: int, end: int, patterns: tuple[str, ...]) -> int | None:
    positions = [
        match.end()
        for pattern in patterns
        for match in re.finditer(pattern, text[start:end], re.IGNORECASE)
    ]
    return start + max(positions) if positions else None


def _excluded_ranges(text: str) -> tuple[tuple[int, int], ...]:
    """Recognize quoted/template segments only for cue exclusion, never text mutation."""

    ranges = [(match.start(), match.end()) for match in re.finditer(r'"[^"\r\n]*"', text)]
    ranges.extend(
        (match.start(), match.end()) for match in re.finditer(r"\{\{.*?\}\}", text, re.DOTALL)
    )
    return tuple(sorted(ranges))


def _is_excluded(start: int, end: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(left <= start and end <= right for left, right in ranges)


def _coerce_lexicon(
    lexicon: AssertionLexicon | Iterable[AssertionCueRecord],
) -> AssertionLexicon:
    if isinstance(lexicon, AssertionLexicon):
        return lexicon
    return AssertionLexicon("ad-hoc", tuple(lexicon))
