from __future__ import annotations

from medlink_ie.decoding.consistency import (
    ConsistencyConfig,
    LabPairing,
    OverlapAction,
    ResolverInput,
    resolve_global_consistency,
)
from medlink_ie.domain import AssertionLabel, EntityType, FinalEntity


def _item(
    identifier: str,
    text: str,
    start: int,
    entity_type: EntityType,
    utility: float = 1.0,
    assertions: tuple[AssertionLabel, ...] = (),
    candidates: tuple[str, ...] | None = None,
) -> ResolverInput:
    return ResolverInput(
        identifier,
        FinalEntity(text, entity_type, (start, start + len(text)), assertions, candidates),
        utility,
    )


def _config(*forbidden: tuple[EntityType, EntityType]) -> ConsistencyConfig:
    entity_types = tuple(EntityType)
    actions = {
        (left, right): OverlapAction.ALLOW
        for index, left in enumerate(entity_types)
        for right in entity_types[index:]
    }
    actions.update({pair: OverlapAction.FORBID for pair in forbidden})
    return ConsistencyConfig(actions, 0.0)


def test_same_ingredient_at_different_positions_and_strengths_keeps_distinct_rxnorm() -> None:
    low = _item(
        "clonazepam-low", "clonazepam 0.5 mg", 0, EntityType.MEDICATION, candidates=("RX:05",)
    )
    high = _item(
        "clonazepam-high", "clonazepam 1 mg", 20, EntityType.MEDICATION, candidates=("RX:1",)
    )

    result = resolve_global_consistency((high, low), _config())

    assert [(item.position, item.candidates) for item in result.entities] == [
        ((0, 17), ("RX:05",)),
        ((20, 35), ("RX:1",)),
    ]


def test_repeated_symptoms_preserve_positional_identity_and_assertions() -> None:
    first = _item(
        "pain-negated", "đau", 0, EntityType.SYMPTOM, assertions=(AssertionLabel.NEGATED,)
    )
    second = _item("pain-present", "đau", 10, EntityType.SYMPTOM)

    result = resolve_global_consistency((second, first), _config())

    assert result.entities[0].assertions == (AssertionLabel.NEGATED,)
    assert result.entities[1].assertions == ()


def test_nested_medication_alias_and_strength_follow_configured_overlap_policy() -> None:
    full = _item("full", "clonazepam 0.5 mg", 0, EntityType.MEDICATION, 0.8)
    alias = _item("alias", "clonazepam", 0, EntityType.MEDICATION, 0.9)

    allowed = resolve_global_consistency((full, alias), _config())
    forbidden = resolve_global_consistency(
        (full, alias), _config((EntityType.MEDICATION, EntityType.MEDICATION))
    )

    assert len(allowed.entities) == 2
    assert [item.text for item in forbidden.entities] == ["clonazepam"]
    assert next(item for item in forbidden.decisions if item.entity_id == "full").reason == (
        "overlap_conflict:alias"
    )


def test_overlapping_symptom_and_diagnosis_resolve_by_utility() -> None:
    symptom = _item("symptom", "đau ngực", 0, EntityType.SYMPTOM, 0.7)
    diagnosis = _item("diagnosis", "đau ngực cấp", 0, EntityType.DIAGNOSIS, 0.8)

    result = resolve_global_consistency(
        (symptom, diagnosis), _config((EntityType.SYMPTOM, EntityType.DIAGNOSIS))
    )

    assert [item.type for item in result.entities] == [EntityType.DIAGNOSIS]


def test_lab_result_wrong_neighbor_is_repaired_to_nearest_local_test() -> None:
    glucose = _item("glucose", "Glucose", 0, EntityType.TEST_NAME)
    sodium = _item("sodium", "Sodium", 30, EntityType.TEST_NAME)
    result = _item("result", "5 mmol/L", 10, EntityType.TEST_RESULT)

    output = resolve_global_consistency(
        (glucose, sodium, result),
        _config(),
        (LabPairing("result", ("glucose", "sodium"), "sodium"),),
    )

    assert output.lab_pairs == (("result", "glucose"),)
    assert (
        "lab_pair_reassigned:glucose"
        in next(item for item in output.decisions if item.entity_id == "result").trace
    )


def test_exact_duplicate_proposals_are_removed() -> None:
    duplicate_a = _item("a", "đau", 0, EntityType.SYMPTOM)
    duplicate_b = _item("b", "đau", 0, EntityType.SYMPTOM)

    result = resolve_global_consistency((duplicate_b, duplicate_a), _config())

    assert len(result.entities) == 1
    assert (
        next(item for item in result.decisions if item.entity_id == "b").reason
        == "exact_duplicate:a"
    )


def test_utility_tie_resolves_by_positional_identity() -> None:
    left = _item("b", "đau", 0, EntityType.SYMPTOM)
    right = _item("a", "viêm", 0, EntityType.DIAGNOSIS)

    result = resolve_global_consistency(
        (left, right), _config((EntityType.SYMPTOM, EntityType.DIAGNOSIS))
    )

    assert [item.text for item in result.entities] == [left.entity.text]
    assert (
        next(item for item in result.decisions if item.entity_id == "a").reason
        == "overlap_conflict:b"
    )
