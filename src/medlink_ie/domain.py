"""Immutable, dependency-free domain contracts for MedLink-IE.

These contracts intentionally preserve optional values rather than applying
submission-field omission rules: TASK_CONTRACT.md has not adjudicated those
rules yet.  They perform no file I/O and serialize only in-memory state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class EntityType(str, Enum):
    SYMPTOM = "TRIỆU_CHỨNG"
    TEST_NAME = "TÊN_XÉT_NGHIỆM"
    TEST_RESULT = "KẾT_QUẢ_XÉT_NGHIỆM"
    DIAGNOSIS = "CHẨN_ĐOÁN"
    MEDICATION = "THUỐC"


class AssertionLabel(str, Enum):
    NEGATED = "isNegated"
    HISTORICAL = "isHistorical"
    FAMILY = "isFamily"


class ProposalSource(str, Enum):
    MEDICATION_RULES = "medication_rules"
    LAB_RULES = "lab_rules"
    CONCEPT_RULES = "concept_rules"
    SPAN_MODEL = "span_model"
    LLM_PROPOSER = "llm_proposer"


class GroundingMethod(str, Enum):
    EXACT_RAW = "exact_raw"
    EXACT_VIEW = "exact_view"
    CASE_INSENSITIVE = "case_insensitive"
    TOKEN_ALIGNED = "token_aligned"
    FUZZY_RAW = "fuzzy_raw"


def _validate_confidence(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number between 0 and 1")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _validate_interval(start: int, end: int, field_name: str) -> None:
    if isinstance(start, bool) or isinstance(end, bool):
        raise TypeError(f"{field_name} boundaries must be integers")
    if not isinstance(start, int) or not isinstance(end, int):
        raise TypeError(f"{field_name} boundaries must be integers")
    if start < 0 or end < 0:
        raise ValueError(f"{field_name} boundaries must be non-negative")
    if end <= start:
        raise ValueError(f"{field_name} must be a non-empty ordered interval")


def _validate_optional_interval(start: int | None, end: int | None, name: str) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{name}_start and {name}_end must both be set or both be None")
    if start is not None and end is not None:
        _validate_interval(start, end, name)


def _frozen_mapping(value: Mapping[Any, Any], field_name: str) -> Mapping[Any, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(dict(value))


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _serialize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


class _Serializable:
    """Mixin for stable in-memory JSON representations."""

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SourceDocument(_Serializable):
    document_id: str
    raw_bytes: bytes
    raw_text: str
    encoding: str
    had_bom: bool
    newline_style: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata, "metadata"))
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id:
            raise ValueError("document_id must be a non-empty string")
        if not isinstance(self.raw_bytes, bytes):
            raise TypeError("raw_bytes must be bytes")
        if not isinstance(self.raw_text, str):
            raise TypeError("raw_text must be str")
        if not isinstance(self.encoding, str) or not self.encoding:
            raise ValueError("encoding must be a non-empty string")
        if not isinstance(self.had_bom, bool):
            raise TypeError("had_bom must be bool")
        if not isinstance(self.newline_style, str) or not self.newline_style:
            raise ValueError("newline_style must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {
                "document_id": self.document_id,
                "raw_bytes": self.raw_bytes.hex(),
                "raw_text": self.raw_text,
                "encoding": self.encoding,
                "had_bom": self.had_bom,
                "newline_style": self.newline_style,
                "metadata": self.metadata,
            }
        )


@dataclass(frozen=True, slots=True)
class TextView(_Serializable):
    name: str
    text: str
    boundary_to_raw: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "boundary_to_raw", tuple(self.boundary_to_raw))
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.text, str):
            raise TypeError("text must be str")
        if len(self.boundary_to_raw) != len(self.text) + 1:
            raise ValueError("boundary_to_raw must contain one more boundary than text")
        previous = -1
        for boundary in self.boundary_to_raw:
            if isinstance(boundary, bool) or not isinstance(boundary, int):
                raise TypeError("boundary_to_raw values must be integers")
            if boundary < 0:
                raise ValueError("boundary_to_raw values must be non-negative")
            if boundary < previous:
                raise ValueError("boundary_to_raw must be non-decreasing")
            previous = boundary

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {"name": self.name, "text": self.text, "boundary_to_raw": self.boundary_to_raw}
        )


@dataclass(frozen=True, slots=True)
class SpanProposal(_Serializable):
    proposal_id: str
    source: ProposalSource
    view_name: str
    proposed_text: str
    proposed_type: EntityType | None
    view_start: int | None
    view_end: int | None
    raw_start: int | None
    raw_end: int | None
    raw_text: str | None
    source_score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata, "metadata"))
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise ValueError("proposal_id must be a non-empty string")
        if not isinstance(self.source, ProposalSource):
            raise TypeError("source must be a ProposalSource")
        if not isinstance(self.view_name, str) or not self.view_name:
            raise ValueError("view_name must be a non-empty string")
        if not isinstance(self.proposed_text, str) or not self.proposed_text:
            raise ValueError("proposed_text must be a non-empty string")
        if self.proposed_type is not None and not isinstance(self.proposed_type, EntityType):
            raise TypeError("proposed_type must be an EntityType or None")
        _validate_optional_interval(self.view_start, self.view_end, "view")
        _validate_optional_interval(self.raw_start, self.raw_end, "raw")
        if self.raw_text is not None and not isinstance(self.raw_text, str):
            raise TypeError("raw_text must be str or None")
        _validate_confidence(self.source_score, "source_score")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {
                "proposal_id": self.proposal_id,
                "source": self.source,
                "view_name": self.view_name,
                "proposed_text": self.proposed_text,
                "proposed_type": self.proposed_type,
                "view_start": self.view_start,
                "view_end": self.view_end,
                "raw_start": self.raw_start,
                "raw_end": self.raw_end,
                "raw_text": self.raw_text,
                "source_score": self.source_score,
                "metadata": self.metadata,
            }
        )


@dataclass(frozen=True, slots=True)
class GroundingCandidate(_Serializable):
    raw_start: int
    raw_end: int
    score: float
    reason: str

    def __post_init__(self) -> None:
        _validate_interval(self.raw_start, self.raw_end, "raw")
        _validate_confidence(self.score, "score")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {
                "raw_start": self.raw_start,
                "raw_end": self.raw_end,
                "score": self.score,
                "reason": self.reason,
            }
        )


@dataclass(frozen=True, slots=True)
class GroundedSpan(_Serializable):
    proposal_id: str
    raw_start: int
    raw_end: int
    text: str
    method: GroundingMethod
    confidence: float
    candidate_occurrences: tuple[GroundingCandidate, ...] = ()
    selected_reason: str = "legacy"

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_occurrences", tuple(self.candidate_occurrences))
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise ValueError("proposal_id must be a non-empty string")
        _validate_interval(self.raw_start, self.raw_end, "raw")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be a non-empty string")
        if not isinstance(self.method, GroundingMethod):
            raise TypeError("method must be a GroundingMethod")
        _validate_confidence(self.confidence, "confidence")
        if any(
            not isinstance(candidate, GroundingCandidate)
            for candidate in self.candidate_occurrences
        ):
            raise TypeError("candidate_occurrences must contain GroundingCandidate values")
        if not isinstance(self.selected_reason, str) or not self.selected_reason:
            raise ValueError("selected_reason must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {
                "proposal_id": self.proposal_id,
                "raw_start": self.raw_start,
                "raw_end": self.raw_end,
                "text": self.text,
                "method": self.method,
                "confidence": self.confidence,
                "candidate_occurrences": tuple(
                    candidate.to_dict() for candidate in self.candidate_occurrences
                ),
                "selected_reason": self.selected_reason,
            }
        )


@dataclass(frozen=True, slots=True)
class DecisionTrace(_Serializable):
    decisions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "decisions", tuple(self.decisions))
        self.validate()

    def validate(self) -> None:
        if any(not isinstance(decision, str) or not decision for decision in self.decisions):
            raise ValueError("decisions must contain non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        return _serialize({"decisions": self.decisions})


@dataclass(frozen=True, slots=True)
class EntityHypothesis(_Serializable):
    raw_start: int
    raw_end: int
    text: str
    evidence_sources: tuple[ProposalSource, ...]
    source_scores: Mapping[ProposalSource, float]
    type_probabilities: Mapping[EntityType, float]
    assertion_probabilities: Mapping[AssertionLabel, float]
    structured_slots: Mapping[str, Any]
    candidate_scores: tuple[Mapping[str, Any], ...]
    decision_trace: DecisionTrace

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_sources", tuple(self.evidence_sources))
        object.__setattr__(
            self, "source_scores", _frozen_mapping(self.source_scores, "source_scores")
        )
        object.__setattr__(
            self,
            "type_probabilities",
            _frozen_mapping(self.type_probabilities, "type_probabilities"),
        )
        object.__setattr__(
            self,
            "assertion_probabilities",
            _frozen_mapping(self.assertion_probabilities, "assertion_probabilities"),
        )
        object.__setattr__(
            self, "structured_slots", _frozen_mapping(self.structured_slots, "structured_slots")
        )
        object.__setattr__(
            self,
            "candidate_scores",
            tuple(_frozen_mapping(item, "candidate_scores item") for item in self.candidate_scores),
        )
        self.validate()

    def validate(self) -> None:
        _validate_interval(self.raw_start, self.raw_end, "raw")
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be a non-empty string")
        if any(not isinstance(source, ProposalSource) for source in self.evidence_sources):
            raise TypeError("evidence_sources must contain ProposalSource values")
        for source, score in self.source_scores.items():
            if not isinstance(source, ProposalSource):
                raise TypeError("source_scores keys must be ProposalSource values")
            _validate_confidence(score, f"source_scores[{source.value}]")
        for entity_type, probability in self.type_probabilities.items():
            if not isinstance(entity_type, EntityType):
                raise TypeError("type_probabilities keys must be EntityType values")
            _validate_confidence(probability, f"type_probabilities[{entity_type.value}]")
        for label, probability in self.assertion_probabilities.items():
            if not isinstance(label, AssertionLabel):
                raise TypeError("assertion_probabilities keys must be AssertionLabel values")
            _validate_confidence(probability, f"assertion_probabilities[{label.value}]")
        if not isinstance(self.decision_trace, DecisionTrace):
            raise TypeError("decision_trace must be a DecisionTrace")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {
                "raw_start": self.raw_start,
                "raw_end": self.raw_end,
                "text": self.text,
                "evidence_sources": self.evidence_sources,
                "source_scores": self.source_scores,
                "type_probabilities": self.type_probabilities,
                "assertion_probabilities": self.assertion_probabilities,
                "structured_slots": self.structured_slots,
                "candidate_scores": self.candidate_scores,
                "decision_trace": self.decision_trace.to_dict(),
            }
        )


@dataclass(frozen=True, slots=True)
class FinalEntity(_Serializable):
    text: str
    type: EntityType
    position: tuple[int, int]
    assertions: tuple[AssertionLabel, ...]
    candidates: tuple[str, ...] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "assertions", tuple(self.assertions))
        if self.candidates is not None:
            object.__setattr__(self, "candidates", tuple(self.candidates))
        self.validate()

    def validate(self, document: SourceDocument | None = None) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("text must be a non-empty string")
        if not isinstance(self.type, EntityType):
            raise TypeError("type must be an EntityType")
        if not isinstance(self.position, tuple) or len(self.position) != 2:
            raise TypeError("position must be a tuple of two integer boundaries")
        _validate_interval(self.position[0], self.position[1], "position")
        if any(not isinstance(label, AssertionLabel) for label in self.assertions):
            raise TypeError("assertions must contain AssertionLabel values")
        if self.candidates is not None and any(
            not isinstance(candidate, str) or not candidate for candidate in self.candidates
        ):
            raise ValueError("candidates must contain non-empty strings")
        if document is not None:
            if not isinstance(document, SourceDocument):
                raise TypeError("document must be a SourceDocument")
            start, end = self.position
            if end > len(document.raw_text):
                raise ValueError("position is outside document.raw_text")
            if document.raw_text[start:end] != self.text:
                raise ValueError("FinalEntity text does not match document.raw_text at position")

    def validate_semantics(self, document: SourceDocument) -> None:
        self.validate(document)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(
            {
                "text": self.text,
                "type": self.type,
                "position": self.position,
                "assertions": self.assertions,
                "candidates": self.candidates,
            }
        )


# Backward-compatible spelling for the earlier contract name.
Assertion = AssertionLabel
