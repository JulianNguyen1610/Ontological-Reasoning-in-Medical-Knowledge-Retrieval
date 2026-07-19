"""Deterministic global consistency resolution for decoded entities."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from medlink_ie.domain import EntityType, FinalEntity


class OverlapAction(str, Enum):
    ALLOW = "allow"
    FORBID = "forbid"


@dataclass(frozen=True, slots=True)
class ConsistencyConfig:
    """Explicit policy for interval conflicts; unconfigured conflicts abstain."""

    overlap_actions: Mapping[tuple[EntityType, EntityType], OverlapAction]
    minimum_utility: float

    def __post_init__(self) -> None:
        actions: dict[tuple[EntityType, EntityType], OverlapAction] = {}
        for pair, action in self.overlap_actions.items():
            if (
                not isinstance(pair, tuple)
                or len(pair) != 2
                or any(not isinstance(value, EntityType) for value in pair)
            ):
                raise TypeError("overlap action keys must contain two EntityType values")
            if not isinstance(action, OverlapAction):
                raise TypeError("overlap actions must be OverlapAction values")
            canonical_pair = _type_pair(*pair)
            previous = actions.setdefault(canonical_pair, action)
            if previous is not action:
                raise ValueError("reciprocal overlap actions must agree")
        if (
            isinstance(self.minimum_utility, bool)
            or not isinstance(self.minimum_utility, (int, float))
            or not math.isfinite(self.minimum_utility)
        ):
            raise TypeError("minimum_utility must be finite")
        object.__setattr__(self, "overlap_actions", MappingProxyType(actions))


@dataclass(frozen=True, slots=True)
class ResolverInput:
    """A positional entity plus its decoder utility, never keyed by surface text."""

    entity_id: str
    entity: FinalEntity
    utility: float

    def __post_init__(self) -> None:
        if not isinstance(self.entity_id, str) or not self.entity_id:
            raise ValueError("entity_id must be a non-empty string")
        if not isinstance(self.entity, FinalEntity):
            raise TypeError("entity must be a FinalEntity")
        if (
            isinstance(self.utility, bool)
            or not isinstance(self.utility, (int, float))
            or not math.isfinite(self.utility)
        ):
            raise TypeError("utility must be finite")


@dataclass(frozen=True, slots=True)
class LabPairing:
    """A result's local eligible tests and any upstream assignment."""

    result_id: str
    test_ids: tuple[str, ...]
    assigned_test_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "test_ids", tuple(self.test_ids))
        if not isinstance(self.result_id, str) or not self.result_id:
            raise ValueError("result_id must be a non-empty string")
        if not self.test_ids or any(
            not isinstance(item, str) or not item for item in self.test_ids
        ):
            raise ValueError("test_ids must contain non-empty identifiers")
        if len(set(self.test_ids)) != len(self.test_ids):
            raise ValueError("test_ids must be unique")
        if self.assigned_test_id is not None and self.assigned_test_id not in self.test_ids:
            raise ValueError("assigned_test_id must be one of test_ids")


@dataclass(frozen=True, slots=True)
class ConsistencyDecision:
    entity_id: str
    kept: bool
    entity: FinalEntity | None
    reason: str
    trace: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsistencyResult:
    entities: tuple[FinalEntity, ...]
    decisions: tuple[ConsistencyDecision, ...]
    lab_pairs: tuple[tuple[str, str], ...]


def resolve_global_consistency(
    inputs: tuple[ResolverInput, ...],
    config: ConsistencyConfig,
    lab_pairings: tuple[LabPairing, ...] = (),
) -> ConsistencyResult:
    """Resolve duplicates, overlap conflicts, and local laboratory pairings.

    This intentionally uses deterministic greedy conflict rules: candidates are
    considered by descending decoder utility and positional identity.  It keeps
    the component pure and makes an ILP backend unnecessary for the current
    interval and pairwise-constraint scope.
    """
    if not isinstance(config, ConsistencyConfig):
        raise TypeError("config must be a ConsistencyConfig")
    items = tuple(inputs)
    by_id = _index_inputs(items)
    decisions = {
        item.entity_id: ConsistencyDecision(item.entity_id, True, item.entity, "kept", ())
        for item in items
    }
    _remove_duplicates(items, decisions)
    _abstain_unsupported_overlaps(items, config, decisions)
    _resolve_forbidden_overlaps(items, config, decisions)
    _drop_low_utility(items, config, decisions)
    lab_pairs = _resolve_lab_pairings(tuple(lab_pairings), by_id, decisions)
    ordered_decisions = tuple(decisions[item_id] for item_id in sorted(decisions))
    entities = tuple(
        sorted(
            (
                decision.entity
                for decision in ordered_decisions
                if decision.kept and decision.entity
            ),
            key=lambda entity: (
                entity.position[0],
                entity.position[1],
                entity.type.value,
                entity.text,
            ),
        )
    )
    return ConsistencyResult(entities, ordered_decisions, lab_pairs)


def _index_inputs(items: tuple[ResolverInput, ...]) -> Mapping[str, ResolverInput]:
    indexed = {item.entity_id: item for item in items}
    if len(indexed) != len(items):
        raise ValueError("entity IDs must be unique")
    return MappingProxyType(indexed)


def _remove_duplicates(
    items: tuple[ResolverInput, ...], decisions: dict[str, ConsistencyDecision]
) -> None:
    seen: dict[tuple[object, ...], str] = {}
    for item in sorted(items, key=lambda value: (_identity(value), value.entity_id)):
        fingerprint = _exact_object(item.entity)
        original = seen.setdefault(fingerprint, item.entity_id)
        if original != item.entity_id:
            _drop(
                decisions, item.entity_id, f"exact_duplicate:{original}", f"duplicate_of:{original}"
            )


def _abstain_unsupported_overlaps(
    items: tuple[ResolverInput, ...],
    config: ConsistencyConfig,
    decisions: dict[str, ConsistencyDecision],
) -> None:
    for left, right in _overlapping_pairs(items):
        if _type_pair(left.entity.type, right.entity.type) not in config.overlap_actions:
            _drop(
                decisions,
                left.entity_id,
                "unsupported_overlap",
                f"abstained_overlap:{right.entity_id}",
            )
            _drop(
                decisions,
                right.entity_id,
                "unsupported_overlap",
                f"abstained_overlap:{left.entity_id}",
            )


def _resolve_forbidden_overlaps(
    items: tuple[ResolverInput, ...],
    config: ConsistencyConfig,
    decisions: dict[str, ConsistencyDecision],
) -> None:
    for candidate in sorted(
        items, key=lambda value: (-value.utility, _identity(value), value.entity_id)
    ):
        if not decisions[candidate.entity_id].kept:
            continue
        blockers = [
            other
            for other in items
            if other.entity_id != candidate.entity_id
            and decisions[other.entity_id].kept
            and _overlaps(candidate.entity, other.entity)
            and config.overlap_actions.get(_type_pair(candidate.entity.type, other.entity.type))
            is OverlapAction.FORBID
            and _outranks(other, candidate)
        ]
        if blockers:
            blocker = min(
                blockers, key=lambda value: (-value.utility, _identity(value), value.entity_id)
            )
            _drop(
                decisions,
                candidate.entity_id,
                f"overlap_conflict:{blocker.entity_id}",
                f"dropped_overlap:{blocker.entity_id}",
            )


def _drop_low_utility(
    items: tuple[ResolverInput, ...],
    config: ConsistencyConfig,
    decisions: dict[str, ConsistencyDecision],
) -> None:
    for item in items:
        if decisions[item.entity_id].kept and item.utility < config.minimum_utility:
            _drop(decisions, item.entity_id, "utility_below_minimum", "abstained_low_utility")


def _resolve_lab_pairings(
    pairings: tuple[LabPairing, ...],
    by_id: Mapping[str, ResolverInput],
    decisions: dict[str, ConsistencyDecision],
) -> tuple[tuple[str, str], ...]:
    resolved: list[tuple[str, str]] = []
    for pairing in sorted(pairings, key=lambda item: item.result_id):
        if pairing.result_id not in by_id or any(
            test_id not in by_id for test_id in pairing.test_ids
        ):
            raise ValueError("lab pairing references an unknown entity")
        result = by_id[pairing.result_id]
        if result.entity.type is not EntityType.TEST_RESULT:
            raise ValueError("lab pairing result must be a TEST_RESULT")
        tests = tuple(by_id[test_id] for test_id in pairing.test_ids)
        if any(test.entity.type is not EntityType.TEST_NAME for test in tests):
            raise ValueError("lab pairing test IDs must be TEST_NAME entities")
        eligible = tuple(test for test in tests if decisions[test.entity_id].kept)
        if not decisions[result.entity_id].kept:
            continue
        if not eligible:
            _drop(decisions, result.entity_id, "lab_pair_abstained", "no_kept_local_test")
            continue
        selected = min(
            eligible,
            key=lambda test: (
                _interval_gap(test.entity, result.entity),
                -test.entity.position[0],
                test.entity_id,
            ),
        )
        trace = (
            "lab_pair_confirmed"
            if pairing.assigned_test_id == selected.entity_id
            else (f"lab_pair_reassigned:{selected.entity_id}")
        )
        decision = decisions[result.entity_id]
        decisions[result.entity_id] = replace(decision, trace=decision.trace + (trace,))
        resolved.append((result.entity_id, selected.entity_id))
    return tuple(resolved)


def _drop(
    decisions: dict[str, ConsistencyDecision], entity_id: str, reason: str, trace: str
) -> None:
    decision = decisions[entity_id]
    if decision.kept:
        decisions[entity_id] = replace(
            decision, kept=False, entity=None, reason=reason, trace=decision.trace + (trace,)
        )


def _overlapping_pairs(
    items: tuple[ResolverInput, ...],
) -> tuple[tuple[ResolverInput, ResolverInput], ...]:
    return tuple(
        (left, right)
        for index, left in enumerate(items)
        for right in items[index + 1 :]
        if _overlaps(left.entity, right.entity)
    )


def _overlaps(left: FinalEntity, right: FinalEntity) -> bool:
    return left.position[0] < right.position[1] and right.position[0] < left.position[1]


def _interval_gap(left: FinalEntity, right: FinalEntity) -> int:
    return max(right.position[0] - left.position[1], left.position[0] - right.position[1], 0)


def _type_pair(left: EntityType, right: EntityType) -> tuple[EntityType, EntityType]:
    return tuple(sorted((left, right), key=lambda value: value.value))  # type: ignore[return-value]


def _identity(item: ResolverInput) -> tuple[int, int, str, str, str]:
    entity = item.entity
    return (entity.position[0], entity.position[1], entity.type.value, entity.text, item.entity_id)


def _exact_object(entity: FinalEntity) -> tuple[object, ...]:
    return (entity.text, entity.type, entity.position, entity.assertions, entity.candidates)


def _outranks(left: ResolverInput, right: ResolverInput) -> bool:
    return (-left.utility, _identity(left), left.entity_id) < (
        -right.utility,
        _identity(right),
        right.entity_id,
    )
