"""Immutable gold-annotation records and non-adjudicating review utilities.

The JSONL schema deliberately retains raw text when it is available.  A record
may instead retain a content-addressed source reference, but semantic span
validation then requires the caller to supply the corresponding raw text.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from medlink_ie.domain import AssertionLabel, EntityType


class AdjudicationStatus(str, Enum):
    """Human-review state; this module never changes it automatically."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class GoldRecordError(ValueError):
    """Raised when one JSONL record cannot be decoded into the gold schema."""


@dataclass(frozen=True, slots=True)
class ImmutableSourceReference:
    """Content-addressed reference used when raw text is stored elsewhere."""

    uri: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str) or not self.uri:
            raise ValueError("source reference uri must be a non-empty string")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64:
            raise ValueError("source reference sha256 must be a 64-character hexadecimal digest")
        if any(char not in "0123456789abcdefABCDEF" for char in self.sha256):
            raise ValueError("source reference sha256 must be hexadecimal")
        object.__setattr__(self, "sha256", self.sha256.lower())

    def to_dict(self) -> dict[str, str]:
        return {"uri": self.uri, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class GoldEntity:
    """A positional entity annotation, independent of generated predictions."""

    text: str
    start: int
    end: int
    type: EntityType
    assertions: tuple[AssertionLabel, ...] = ()
    candidates: tuple[str, ...] | None = None
    adjudication_status: AdjudicationStatus = AdjudicationStatus.PENDING
    rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "assertions", tuple(self.assertions))
        object.__setattr__(self, "rule_ids", tuple(self.rule_ids))
        if self.candidates is not None:
            object.__setattr__(self, "candidates", tuple(self.candidates))
        self.validate_structure()

    def validate_structure(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("entity text must be a non-empty string")
        _validate_interval(self.start, self.end, "entity")
        if not isinstance(self.type, EntityType):
            raise TypeError("entity type must be an EntityType")
        if any(not isinstance(label, AssertionLabel) for label in self.assertions):
            raise TypeError("entity assertions must contain AssertionLabel values")
        if len(set(self.assertions)) != len(self.assertions):
            raise ValueError("entity assertions must not contain duplicates")
        if self.candidates is not None:
            if self.type not in {EntityType.DIAGNOSIS, EntityType.MEDICATION}:
                raise ValueError(
                    "candidates are only applicable to diagnosis and medication entities"
                )
            if any(
                not isinstance(candidate, str) or not candidate for candidate in self.candidates
            ):
                raise ValueError("entity candidates must contain non-empty strings")
        if not isinstance(self.adjudication_status, AdjudicationStatus):
            raise TypeError("entity adjudication_status must be an AdjudicationStatus")
        if any(not isinstance(rule_id, str) or not rule_id for rule_id in self.rule_ids):
            raise ValueError("entity rule_ids must contain non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "type": self.type.value,
            "assertions": [label.value for label in self.assertions],
            "adjudication_status": self.adjudication_status.value,
        }
        if self.candidates is not None:
            result["candidates"] = list(self.candidates)
        if self.rule_ids:
            result["rule_ids"] = list(self.rule_ids)
        return result


@dataclass(frozen=True, slots=True)
class GoldSample:
    """One gold record with text retained locally or via an immutable reference."""

    sample_id: str
    raw_text: str | None
    source_reference: ImmutableSourceReference | None
    entities: tuple[GoldEntity, ...] = ()
    adjudication_status: AdjudicationStatus = AdjudicationStatus.PENDING

    def __post_init__(self) -> None:
        object.__setattr__(self, "entities", tuple(self.entities))
        self.validate_structure()

    def validate_structure(self) -> None:
        if not isinstance(self.sample_id, str) or not self.sample_id:
            raise ValueError("sample_id must be a non-empty string")
        if self.raw_text is not None and not isinstance(self.raw_text, str):
            raise TypeError("raw_text must be str or None")
        if self.raw_text is None and self.source_reference is None:
            raise ValueError("raw_text or source_reference must be preserved")
        if self.source_reference is not None and not isinstance(
            self.source_reference, ImmutableSourceReference
        ):
            raise TypeError("source_reference must be an ImmutableSourceReference or None")
        if any(not isinstance(entity, GoldEntity) for entity in self.entities):
            raise TypeError("entities must contain GoldEntity values")
        if not isinstance(self.adjudication_status, AdjudicationStatus):
            raise TypeError("sample adjudication_status must be an AdjudicationStatus")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sample_id": self.sample_id,
            "entities": [entity.to_dict() for entity in self.entities],
            "adjudication_status": self.adjudication_status.value,
        }
        if self.raw_text is not None:
            result["raw_text"] = self.raw_text
        if self.source_reference is not None:
            result["source_reference"] = self.source_reference.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    entity_indexes: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class GoldValidationReport:
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class JsonlReadError:
    line_number: int
    message: str


@dataclass(frozen=True, slots=True)
class GoldJsonlReadReport:
    samples: tuple[GoldSample, ...]
    errors: tuple[JsonlReadError, ...]


@dataclass(frozen=True, slots=True)
class EntityDisagreement:
    left: GoldEntity
    right: GoldEntity


@dataclass(frozen=True, slots=True)
class AnnotatorComparisonReport:
    sample_id: str
    boundary_disagreements: tuple[EntityDisagreement, ...]
    type_disagreements: tuple[EntityDisagreement, ...]
    assertion_disagreements: tuple[EntityDisagreement, ...]
    candidate_disagreements: tuple[EntityDisagreement, ...]
    unmatched_left: tuple[GoldEntity, ...]
    unmatched_right: tuple[GoldEntity, ...]


def validate_gold_sample(sample: GoldSample, raw_text: str | None = None) -> GoldValidationReport:
    """Check raw-slice semantics, duplicates, and guide-controlled overlaps."""
    sample.validate_structure()
    text = sample.raw_text if raw_text is None else raw_text
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    if text is None:
        errors.append(
            ValidationIssue("raw_text_unavailable", "raw text is needed to validate spans")
        )
    else:
        if not isinstance(text, str):
            raise TypeError("raw_text must be str or None")
        if sample.raw_text is not None and raw_text is not None and sample.raw_text != raw_text:
            errors.append(
                ValidationIssue(
                    "raw_text_mismatch", "supplied raw text differs from stored raw text"
                )
            )
        for index, entity in enumerate(sample.entities):
            if entity.end > len(text):
                errors.append(
                    ValidationIssue(
                        "offset_out_of_bounds", "entity offsets exceed raw text", (index,)
                    )
                )
            elif text[entity.start : entity.end] != entity.text:
                errors.append(
                    ValidationIssue(
                        "text_mismatch", "entity text differs from raw_text[start:end]", (index,)
                    )
                )
    seen: dict[GoldEntity, int] = {}
    for index, entity in enumerate(sample.entities):
        if entity in seen:
            errors.append(
                ValidationIssue("duplicate_entity", "exact duplicate entity", (seen[entity], index))
            )
        else:
            seen[entity] = index
    for left_index, left in enumerate(sample.entities):
        for right_index in range(left_index + 1, len(sample.entities)):
            right = sample.entities[right_index]
            if _overlaps(left, right):
                issue = ValidationIssue(
                    "overlap_requires_adjudication",
                    "overlapping entities require an explicit confirmed boundary policy",
                    (left_index, right_index),
                )
                if sample.adjudication_status is AdjudicationStatus.CONFIRMED:
                    errors.append(issue)
                else:
                    warnings.append(issue)
    return GoldValidationReport(tuple(errors), tuple(warnings))


def read_gold_jsonl(path: Path, strict: bool = False) -> GoldJsonlReadReport:
    """Read JSONL independently per line so malformed samples do not halt a batch."""
    samples: list[GoldSample] = []
    errors: list[JsonlReadError] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                error = JsonlReadError(line_number, "blank JSONL record")
                if strict:
                    raise GoldRecordError(f"line {line_number}: {error.message}")
                errors.append(error)
                continue
            try:
                value = json.loads(line)
                samples.append(_sample_from_dict(value))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                if strict:
                    raise GoldRecordError(f"line {line_number}: {exc}") from exc
                errors.append(JsonlReadError(line_number, str(exc)))
    return GoldJsonlReadReport(tuple(samples), tuple(errors))


def write_gold_jsonl(path: Path, samples: Iterable[GoldSample]) -> None:
    """Atomically write deterministic UTF-8 JSONL records after semantic validation."""
    checked = tuple(samples)
    for sample in checked:
        sample.validate_structure()
        if sample.raw_text is not None:
            report = validate_gold_sample(sample)
            if not report.is_valid:
                raise GoldRecordError(
                    "cannot write invalid gold sample: " + report.errors[0].message
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        for sample in checked:
            handle.write(
                json.dumps(
                    sample.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
            )
            handle.write("\n")
    os.replace(temporary, path)


def compare_annotators(left: GoldSample, right: GoldSample) -> AnnotatorComparisonReport:
    """Align annotations by interval and type, then report each field disagreement."""
    if left.sample_id != right.sample_id:
        raise ValueError("annotator samples must have the same sample_id")
    left_text = left.raw_text
    right_text = right.raw_text
    if left_text is not None and right_text is not None and left_text != right_text:
        raise ValueError("annotator samples must use the same raw text")
    pairs, remaining_left, remaining_right = _align_entities(left.entities, right.entities)
    boundary: list[EntityDisagreement] = []
    types: list[EntityDisagreement] = []
    assertions: list[EntityDisagreement] = []
    candidates: list[EntityDisagreement] = []
    for pair in pairs:
        if (pair.left.start, pair.left.end) != (pair.right.start, pair.right.end):
            boundary.append(pair)
        if pair.left.type is not pair.right.type:
            types.append(pair)
        if pair.left.assertions != pair.right.assertions:
            assertions.append(pair)
        if pair.left.candidates != pair.right.candidates:
            candidates.append(pair)
    return AnnotatorComparisonReport(
        left.sample_id,
        tuple(boundary),
        tuple(types),
        tuple(assertions),
        tuple(candidates),
        tuple(left.entities[index] for index in remaining_left),
        tuple(right.entities[index] for index in remaining_right),
    )


def _sample_from_dict(value: object) -> GoldSample:
    item = _mapping(value, "sample")
    _require_keys(
        item,
        {"sample_id", "raw_text", "source_reference", "entities", "adjudication_status"},
        "sample",
    )
    entities_value = item.get("entities", [])
    if not isinstance(entities_value, list):
        raise GoldRecordError("sample entities must be a list")
    source_value = item.get("source_reference")
    source = None if source_value is None else _source_from_dict(source_value)
    return GoldSample(
        _string(item.get("sample_id"), "sample_id"),
        _optional_string(item.get("raw_text"), "raw_text"),
        source,
        tuple(_entity_from_dict(entity) for entity in entities_value),
        _status(item.get("adjudication_status", AdjudicationStatus.PENDING.value), "sample"),
    )


def _entity_from_dict(value: object) -> GoldEntity:
    item = _mapping(value, "entity")
    _require_keys(
        item,
        {
            "text",
            "start",
            "end",
            "type",
            "assertions",
            "candidates",
            "adjudication_status",
            "rule_ids",
        },
        "entity",
    )
    assertions_value = item.get("assertions", [])
    if not isinstance(assertions_value, list):
        raise GoldRecordError("entity assertions must be a list")
    candidates_value = item.get("candidates")
    if candidates_value is not None and not isinstance(candidates_value, list):
        raise GoldRecordError("entity candidates must be a list or omitted")
    rule_ids_value = item.get("rule_ids", [])
    if not isinstance(rule_ids_value, list):
        raise GoldRecordError("entity rule_ids must be a list")
    try:
        entity_type = EntityType(_string(item.get("type"), "entity type"))
        assertions = tuple(
            AssertionLabel(_string(label, "assertion")) for label in assertions_value
        )
    except ValueError as exc:
        raise GoldRecordError(str(exc)) from exc
    return GoldEntity(
        _string(item.get("text"), "entity text"),
        _integer(item.get("start"), "entity start"),
        _integer(item.get("end"), "entity end"),
        entity_type,
        assertions,
        None
        if candidates_value is None
        else tuple(_string(value, "candidate") for value in candidates_value),
        _status(item.get("adjudication_status", AdjudicationStatus.PENDING.value), "entity"),
        tuple(_string(value, "rule_id") for value in rule_ids_value),
    )


def _source_from_dict(value: object) -> ImmutableSourceReference:
    item = _mapping(value, "source_reference")
    _require_keys(item, {"uri", "sha256"}, "source_reference")
    return ImmutableSourceReference(
        _string(item.get("uri"), "source uri"), _string(item.get("sha256"), "source sha256")
    )


def _align_entities(
    left: tuple[GoldEntity, ...], right: tuple[GoldEntity, ...]
) -> tuple[list[EntityDisagreement], set[int], set[int]]:
    remaining_left = set(range(len(left)))
    remaining_right = set(range(len(right)))
    pairs: list[EntityDisagreement] = []
    for predicate in (_same_position_and_type, _same_position, _same_type_overlap, _overlaps):
        for left_index in sorted(remaining_left):
            matches = [
                right_index
                for right_index in remaining_right
                if predicate(left[left_index], right[right_index])
            ]
            if not matches:
                continue
            right_index = min(
                matches, key=lambda index: _alignment_key(left[left_index], right[index])
            )
            pairs.append(EntityDisagreement(left[left_index], right[right_index]))
            remaining_left.remove(left_index)
            remaining_right.remove(right_index)
    return pairs, remaining_left, remaining_right


def _same_position_and_type(left: GoldEntity, right: GoldEntity) -> bool:
    return left.start == right.start and left.end == right.end and left.type is right.type


def _same_position(left: GoldEntity, right: GoldEntity) -> bool:
    return left.start == right.start and left.end == right.end


def _same_type_overlap(left: GoldEntity, right: GoldEntity) -> bool:
    return left.type is right.type and _overlaps(left, right)


def _overlaps(left: GoldEntity, right: GoldEntity) -> bool:
    return left.start < right.end and right.start < left.end


def _alignment_key(left: GoldEntity, right: GoldEntity) -> tuple[int, int, int, str]:
    return (
        abs(left.start - right.start) + abs(left.end - right.end),
        right.start,
        right.end,
        right.type.value,
    )


def _validate_interval(start: int, end: int, name: str) -> None:
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
    ):
        raise TypeError(f"{name} boundaries must be integers")
    if start < 0 or end <= start:
        raise ValueError(f"{name} must be a non-empty ordered interval")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise GoldRecordError(f"{name} must be an object")
    return value


def _require_keys(item: Mapping[str, object], allowed: set[str], name: str) -> None:
    unknown = set(item) - allowed
    if unknown:
        raise GoldRecordError(f"{name} has unknown fields: {sorted(unknown)}")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise GoldRecordError(f"{name} must be a non-empty string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GoldRecordError(f"{name} must be an integer")
    return value


def _status(value: object, name: str) -> AdjudicationStatus:
    try:
        return AdjudicationStatus(_string(value, f"{name} adjudication_status"))
    except ValueError as exc:
        raise GoldRecordError(str(exc)) from exc
