"""Pure, deterministic local scoring under explicit ``framework_v1`` assumptions.

This module is not an organizer-scorer clone.  Exact alignment, optional-field
handling, set aggregation, and metric weights are configuration values until an
official scorer or scoring specification is available.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """All local scorer assumptions that are not externally confirmed."""

    name: str = "framework_v1"
    alignment: str = "exact_text_type_position"
    optional_none_equals_empty: bool = True
    entity_weight: float = 1.0
    assertion_weight: float = 1.0
    candidate_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.name != "framework_v1":
            raise ValueError("only framework_v1 is currently supported")
        if self.alignment != "exact_text_type_position":
            raise ValueError("only exact_text_type_position alignment is currently supported")
        weights = (self.entity_weight, self.assertion_weight, self.candidate_weight)
        if any(weight < 0.0 for weight in weights) or not any(weight > 0.0 for weight in weights):
            raise ValueError(
                "scoring weights must be non-negative with at least one positive weight"
            )

    @classmethod
    def framework_v1(cls, **overrides: Any) -> "ScoringConfig":
        """Return framework_v1's documented local scoring configuration."""

        return cls(**overrides)


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Deterministic diagnostic result of one local scoring operation."""

    final_score: float
    entity_precision: float
    entity_recall: float
    entity_f1: float
    assertion_jaccard: float
    candidate_jaccard: float
    matched_count: int
    unmatched_gold_count: int
    unmatched_prediction_count: int
    configuration: str


@dataclass(frozen=True, slots=True)
class _EntityObservation:
    text: str
    entity_type: str
    start: int
    end: int
    assertions: frozenset[str] | None
    candidates: frozenset[str] | None

    @property
    def key(self) -> tuple[str, str, int, int]:
        return (self.text, self.entity_type, self.start, self.end)


def score_entities(
    gold_entities: Sequence[Mapping[str, Any]],
    predicted_entities: Sequence[Mapping[str, Any]],
    config: ScoringConfig | None = None,
) -> ScoreBreakdown:
    """Score two entity sequences without mutating either input sequence.

    ``framework_v1`` pairs only exact ``text``, ``type``, and half-open
    ``position`` tuples. Assertions and candidates are then compared as sets
    on matched pairs and unmatched entities, using the selected optional-field
    policy. The final score is the configured weighted mean of entity F1 and
    the two mean Jaccard metrics.
    """

    resolved_config = config or ScoringConfig.framework_v1()
    gold = tuple(_parse_entity(entity, "gold") for entity in gold_entities)
    prediction = tuple(_parse_entity(entity, "prediction") for entity in predicted_entities)
    matched, unmatched_gold, unmatched_prediction = _align_exact(gold, prediction)
    matched_count = len(matched)
    precision = _ratio(matched_count, len(prediction), empty_value=1.0)
    recall = _ratio(matched_count, len(gold), empty_value=1.0)
    entity_f1 = _f1(precision, recall)
    assertion_jaccard = _mean_optional_jaccard(
        matched, unmatched_gold, unmatched_prediction, "assertions", resolved_config
    )
    candidate_jaccard = _mean_optional_jaccard(
        matched, unmatched_gold, unmatched_prediction, "candidates", resolved_config
    )
    total_weight = (
        resolved_config.entity_weight
        + resolved_config.assertion_weight
        + resolved_config.candidate_weight
    )
    final_score = (
        (entity_f1 * resolved_config.entity_weight)
        + (assertion_jaccard * resolved_config.assertion_weight)
        + (candidate_jaccard * resolved_config.candidate_weight)
    ) / total_weight
    return ScoreBreakdown(
        final_score=final_score,
        entity_precision=precision,
        entity_recall=recall,
        entity_f1=entity_f1,
        assertion_jaccard=assertion_jaccard,
        candidate_jaccard=candidate_jaccard,
        matched_count=matched_count,
        unmatched_gold_count=len(unmatched_gold),
        unmatched_prediction_count=len(unmatched_prediction),
        configuration=resolved_config.name,
    )


def _parse_entity(entity: Mapping[str, Any], role: str) -> _EntityObservation:
    if not isinstance(entity, Mapping):
        raise TypeError(f"{role} entity must be a mapping")
    text = entity.get("text")
    entity_type = entity.get("type")
    position = entity.get("position")
    if not isinstance(text, str) or not text:
        raise ValueError(f"{role} entity text must be a non-empty string")
    if not isinstance(entity_type, str) or not entity_type:
        raise ValueError(f"{role} entity type must be a non-empty string")
    if (
        not isinstance(position, Sequence)
        or isinstance(position, (str, bytes))
        or len(position) != 2
    ):
        raise TypeError(f"{role} entity position must contain two integer boundaries")
    start, end = position
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
    ):
        raise TypeError(f"{role} entity position boundaries must be integers")
    if start < 0 or end <= start:
        raise ValueError(f"{role} entity position must be a non-negative half-open interval")
    return _EntityObservation(
        text=text,
        entity_type=entity_type,
        start=start,
        end=end,
        assertions=_optional_string_set(entity, "assertions", role),
        candidates=_optional_string_set(entity, "candidates", role),
    )


def _optional_string_set(
    entity: Mapping[str, Any], field_name: str, role: str
) -> frozenset[str] | None:
    if field_name not in entity or entity[field_name] is None:
        return None
    value = entity[field_name]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{role} entity {field_name} must be a sequence of strings or omitted")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{role} entity {field_name} must contain non-empty strings")
    return frozenset(value)


def _align_exact(
    gold: tuple[_EntityObservation, ...], prediction: tuple[_EntityObservation, ...]
) -> tuple[
    tuple[tuple[_EntityObservation, _EntityObservation], ...],
    tuple[_EntityObservation, ...],
    tuple[_EntityObservation, ...],
]:
    prediction_by_key: dict[tuple[str, str, int, int], deque[_EntityObservation]] = defaultdict(
        deque
    )
    for entity in prediction:
        prediction_by_key[entity.key].append(entity)
    matched: list[tuple[_EntityObservation, _EntityObservation]] = []
    unmatched_gold: list[_EntityObservation] = []
    for entity in gold:
        candidates = prediction_by_key[entity.key]
        if candidates:
            matched.append((entity, candidates.popleft()))
        else:
            unmatched_gold.append(entity)
    unmatched_prediction = tuple(
        entity for candidates in prediction_by_key.values() for entity in candidates
    )
    return tuple(matched), tuple(unmatched_gold), unmatched_prediction


def _mean_optional_jaccard(
    matched: tuple[tuple[_EntityObservation, _EntityObservation], ...],
    unmatched_gold: tuple[_EntityObservation, ...],
    unmatched_prediction: tuple[_EntityObservation, ...],
    field_name: str,
    config: ScoringConfig,
) -> float:
    values = [
        _optional_jaccard(getattr(gold, field_name), getattr(prediction, field_name), config)
        for gold, prediction in matched
    ]
    values.extend(
        _optional_jaccard(getattr(entity, field_name), frozenset(), config)
        for entity in unmatched_gold
    )
    values.extend(
        _optional_jaccard(frozenset(), getattr(entity, field_name), config)
        for entity in unmatched_prediction
    )
    return 1.0 if not values else sum(values) / len(values)


def _optional_jaccard(
    left: frozenset[str] | None, right: frozenset[str] | None, config: ScoringConfig
) -> float:
    if left is None and right is None:
        return 1.0
    if config.optional_none_equals_empty:
        left = frozenset() if left is None else left
        right = frozenset() if right is None else right
    elif left is None or right is None:
        return 0.0
    assert left is not None and right is not None
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _ratio(numerator: int, denominator: int, empty_value: float) -> float:
    return empty_value if denominator == 0 else numerator / denominator


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0.0 else 2.0 * precision * recall / (precision + recall)
