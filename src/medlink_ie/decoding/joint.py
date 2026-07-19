"""Pure, score-aware joint decoding for grounded entity hypotheses.

The local scorer's matching and double-penalty behavior are assumptions, so
all utility and acceptance values are explicit decoder configuration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from types import MappingProxyType
from typing import Mapping

from medlink_ie.domain import AssertionLabel, EntityHypothesis, EntityType, FinalEntity


def _probability(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TypeError(f"{name} must be a finite probability")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class UtilityWeights:
    """Explicit approximation weights, including wrong-field risk."""

    entity_reward: float
    false_positive_penalty: float
    type_reward: float
    wrong_type_penalty: float
    assertion_reward: float
    assertion_false_positive_penalty: float
    candidate_reward: float
    extra_candidate_penalty: float

    def __post_init__(self) -> None:
        for item in fields(self):
            name, value = item.name, getattr(self, item.name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise TypeError(f"{name} must be finite")
            if value < 0.0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class EntityTypeRule:
    """Type-specific acceptance thresholds; none are implicit."""

    entity_threshold: float
    type_threshold: float
    link_threshold: float
    candidate_threshold: float

    def __post_init__(self) -> None:
        for item in fields(self):
            name, value = item.name, getattr(self, item.name)
            _probability(value, name)


@dataclass(frozen=True, slots=True)
class LabelRule:
    threshold: float

    def __post_init__(self) -> None:
        _probability(self.threshold, "label threshold")


@dataclass(frozen=True, slots=True)
class CandidateRule:
    applicable_types: frozenset[EntityType]

    def __post_init__(self) -> None:
        object.__setattr__(self, "applicable_types", frozenset(self.applicable_types))
        if any(not isinstance(value, EntityType) for value in self.applicable_types):
            raise TypeError("candidate applicable_types must contain EntityType values")


@dataclass(frozen=True, slots=True)
class DecoderConfig:
    utility: UtilityWeights
    type_rules: Mapping[EntityType, EntityTypeRule]
    label_rules: Mapping[AssertionLabel, LabelRule]
    candidate_rule: CandidateRule
    applicable_assertions: Mapping[EntityType, frozenset[AssertionLabel]]
    minimum_keep_utility: float

    def __post_init__(self) -> None:
        type_rules = MappingProxyType(dict(self.type_rules))
        label_rules = MappingProxyType(dict(self.label_rules))
        applicable = MappingProxyType(
            {key: frozenset(value) for key, value in self.applicable_assertions.items()}
        )
        if set(type_rules) != set(EntityType) or any(
            not isinstance(value, EntityTypeRule) for value in type_rules.values()
        ):
            raise ValueError("type_rules must configure every EntityType")
        if set(label_rules) != set(AssertionLabel) or any(
            not isinstance(value, LabelRule) for value in label_rules.values()
        ):
            raise ValueError("label_rules must configure every AssertionLabel")
        if set(applicable) != set(EntityType) or any(
            any(not isinstance(label, AssertionLabel) for label in labels)
            for labels in applicable.values()
        ):
            raise ValueError(
                "applicable_assertions must configure valid labels for every EntityType"
            )
        if not isinstance(self.minimum_keep_utility, (int, float)) or not math.isfinite(
            self.minimum_keep_utility
        ):
            raise TypeError("minimum_keep_utility must be finite")
        object.__setattr__(self, "type_rules", type_rules)
        object.__setattr__(self, "label_rules", label_rules)
        object.__setattr__(self, "applicable_assertions", applicable)


@dataclass(frozen=True, slots=True)
class CalibratedEntityScores:
    span_probability: float
    type_probabilities: Mapping[EntityType, float]
    assertion_probabilities: Mapping[AssertionLabel, float]
    link_probability: float
    candidate_scores: Mapping[str, float]

    def __post_init__(self) -> None:
        _probability(self.span_probability, "span_probability")
        _probability(self.link_probability, "link_probability")
        types = MappingProxyType(dict(self.type_probabilities))
        assertions = MappingProxyType(dict(self.assertion_probabilities))
        candidates = MappingProxyType(dict(self.candidate_scores))
        if any(not isinstance(key, EntityType) for key in types):
            raise TypeError("type_probabilities keys must be EntityType")
        if any(not isinstance(key, AssertionLabel) for key in assertions):
            raise TypeError("assertion_probabilities keys must be AssertionLabel")
        for name, values in (("type", types), ("assertion", assertions), ("candidate", candidates)):
            for key, value in values.items():
                if name == "candidate" and (not isinstance(key, str) or not key):
                    raise ValueError("candidate identifiers must be non-empty strings")
                _probability(value, f"{name} probability")
        object.__setattr__(self, "type_probabilities", types)
        object.__setattr__(self, "assertion_probabilities", assertions)
        object.__setattr__(self, "candidate_scores", candidates)


@dataclass(frozen=True, slots=True)
class JointDecoderInput:
    hypothesis_id: str
    hypothesis: EntityHypothesis
    scores: CalibratedEntityScores

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis_id, str) or not self.hypothesis_id:
            raise ValueError("hypothesis_id must be a non-empty string")
        if not isinstance(self.hypothesis, EntityHypothesis):
            raise TypeError("hypothesis must be an EntityHypothesis")
        if not isinstance(self.scores, CalibratedEntityScores):
            raise TypeError("scores must be CalibratedEntityScores")


@dataclass(frozen=True, slots=True)
class OverlapRelationship:
    left_id: str
    right_id: str
    compatible: bool

    def __post_init__(self) -> None:
        if not self.left_id or not self.right_id or self.left_id == self.right_id:
            raise ValueError("overlap relationships require two distinct non-empty IDs")
        if not isinstance(self.compatible, bool):
            raise TypeError("overlap compatibility must be bool")


@dataclass(frozen=True, slots=True)
class UtilityBreakdown:
    span_utility: float
    type_utility: float
    assertion_utility: float
    candidate_utility: float
    total_utility: float


@dataclass(frozen=True, slots=True)
class EntityDecision:
    hypothesis_id: str
    kept: bool
    entity: FinalEntity | None
    utility: UtilityBreakdown
    reason: str
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JointDecodeResult:
    entities: tuple[FinalEntity, ...]
    decisions: tuple[EntityDecision, ...]


def decode_entities(
    inputs: tuple[JointDecoderInput, ...],
    config: DecoderConfig,
    overlaps: tuple[OverlapRelationship, ...] = (),
) -> JointDecodeResult:
    """Jointly decode inputs without model calls or mutation.

    Candidate selection uses expected utility and applies the configurable
    extra-candidate penalty.  Incompatible overlaps are resolved greedily by
    descending total utility then hypothesis ID, an explicitly stable and
    tuneable approximation rather than an official scorer clone.
    """
    if not isinstance(config, DecoderConfig):
        raise TypeError("config must be a DecoderConfig")
    items = tuple(inputs)
    if len({item.hypothesis_id for item in items}) != len(items):
        raise ValueError("hypothesis IDs must be unique")
    item_ids = {item.hypothesis_id for item in items}
    conflicts = _conflicts(tuple(overlaps), item_ids)
    preliminary = tuple(_decode_one(item, config) for item in items)
    accepted: set[str] = set()
    final: dict[str, EntityDecision] = {item.hypothesis_id: item for item in preliminary}
    for decision in sorted(
        (item for item in preliminary if item.kept),
        key=lambda item: (-item.utility.total_utility, item.hypothesis_id),
    ):
        blocker = next(
            (item for item in sorted(accepted) if item in conflicts[decision.hypothesis_id]), None
        )
        if blocker is None:
            accepted.add(decision.hypothesis_id)
        else:
            final[decision.hypothesis_id] = replace(
                decision,
                kept=False,
                entity=None,
                reason=f"overlap_conflict:{blocker}",
                trace=decision.trace + (f"dropped_overlap:{blocker}",),
            )
    decisions = tuple(final[item_id] for item_id in sorted(final))
    entities = tuple(
        sorted(
            (item.entity for item in decisions if item.kept and item.entity is not None),
            key=lambda item: (item.position[0], item.position[1], item.type.value, item.text),
        )
    )
    return JointDecodeResult(entities, decisions)


def _decode_one(item: JointDecoderInput, config: DecoderConfig) -> EntityDecision:
    scores, weights = item.scores, config.utility
    type_choice = _choose_type(scores.type_probabilities, config)
    span_utility = _expected(
        scores.span_probability, weights.entity_reward, weights.false_positive_penalty
    )
    if type_choice is None:
        return _dropped(
            item.hypothesis_id, span_utility, "no_type_meets_threshold", ("type_abstained",)
        )
    entity_type, type_probability = type_choice
    rule = config.type_rules[entity_type]
    if scores.span_probability < rule.entity_threshold:
        return _dropped(
            item.hypothesis_id, span_utility, "span_below_threshold", ("span_abstained",)
        )
    type_utility = _expected(type_probability, weights.type_reward, weights.wrong_type_penalty)
    assertions, assertion_utility = _select_assertions(scores, entity_type, config)
    candidates, candidate_utility = _select_candidates(scores, entity_type, config)
    total = span_utility + type_utility + assertion_utility + candidate_utility
    breakdown = UtilityBreakdown(
        span_utility, type_utility, assertion_utility, candidate_utility, total
    )
    trace = [f"type_selected:{entity_type.value}"]
    trace.append("assertions_empty" if not assertions else "assertions_selected")
    trace.append("candidate_abstained" if candidates is None else "candidates_selected")
    if total < config.minimum_keep_utility:
        return EntityDecision(
            item.hypothesis_id, False, None, breakdown, "utility_below_minimum", tuple(trace)
        )
    hypothesis = item.hypothesis
    return EntityDecision(
        item.hypothesis_id,
        True,
        FinalEntity(
            hypothesis.text,
            entity_type,
            (hypothesis.raw_start, hypothesis.raw_end),
            assertions,
            candidates,
        ),
        breakdown,
        "kept",
        tuple(trace),
    )


def _choose_type(
    probabilities: Mapping[EntityType, float], config: DecoderConfig
) -> tuple[EntityType, float] | None:
    eligible = [
        (entity_type, probability)
        for entity_type, probability in probabilities.items()
        if probability >= config.type_rules[entity_type].type_threshold
    ]
    return max(eligible, key=lambda item: (item[1], item[0].value)) if eligible else None


def _select_assertions(
    scores: CalibratedEntityScores, entity_type: EntityType, config: DecoderConfig
) -> tuple[tuple[AssertionLabel, ...], float]:
    selected: list[tuple[AssertionLabel, float]] = []
    for label in config.applicable_assertions[entity_type]:
        probability = scores.assertion_probabilities.get(label, 0.0)
        utility = _expected(
            probability,
            config.utility.assertion_reward,
            config.utility.assertion_false_positive_penalty,
        )
        if probability >= config.label_rules[label].threshold and utility > 0.0:
            selected.append((label, utility))
    return tuple(label for label, _ in sorted(selected, key=lambda item: item[0].value)), sum(
        utility for _, utility in selected
    )


def _select_candidates(
    scores: CalibratedEntityScores, entity_type: EntityType, config: DecoderConfig
) -> tuple[tuple[str, ...] | None, float]:
    rule = config.type_rules[entity_type]
    if (
        entity_type not in config.candidate_rule.applicable_types
        or scores.link_probability < rule.link_threshold
    ):
        return None, 0.0
    selected = []
    for candidate, probability in scores.candidate_scores.items():
        combined = scores.link_probability * probability
        utility = _expected(
            combined, config.utility.candidate_reward, config.utility.extra_candidate_penalty
        )
        if probability >= rule.candidate_threshold and utility > 0.0:
            selected.append((candidate, utility, probability))
    if not selected:
        return None, 0.0
    ordered = sorted(selected, key=lambda item: (-item[2], item[0]))
    return tuple(candidate for candidate, _, _ in ordered), sum(
        utility for _, utility, _ in selected
    )


def _dropped(
    hypothesis_id: str, span_utility: float, reason: str, trace: tuple[str, ...]
) -> EntityDecision:
    return EntityDecision(
        hypothesis_id,
        False,
        None,
        UtilityBreakdown(span_utility, 0.0, 0.0, 0.0, span_utility),
        reason,
        trace,
    )


def _expected(probability: float, reward: float, penalty: float) -> float:
    return probability * reward - (1.0 - probability) * penalty


def _conflicts(
    overlaps: tuple[OverlapRelationship, ...], item_ids: set[str]
) -> Mapping[str, frozenset[str]]:
    conflicts: dict[str, set[str]] = {item_id: set() for item_id in item_ids}
    for overlap in overlaps:
        if not isinstance(overlap, OverlapRelationship):
            raise TypeError("overlaps must contain OverlapRelationship values")
        if overlap.left_id not in item_ids or overlap.right_id not in item_ids:
            raise ValueError("overlap references an unknown hypothesis")
        if not overlap.compatible:
            conflicts[overlap.left_id].add(overlap.right_id)
            conflicts[overlap.right_id].add(overlap.left_id)
    return MappingProxyType({key: frozenset(value) for key, value in conflicts.items()})
