from __future__ import annotations

from medlink_ie.assertions.engine import AssertionScopeEngine
from medlink_ie.domain import AssertionLabel, SourceDocument
from medlink_ie.structure.analyzer import StructuralAnalyzer


def _decisions(text: str, entity: str, occurrence: int = 0):
    document = SourceDocument(
        "propagation-test", text.encode("utf-8"), text, "utf-8", False, "none"
    )
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(entity, start + 1)
    return AssertionScopeEngine().classify(
        text,
        start,
        start + len(entity),
        StructuralAnalyzer().analyze(document),
    )


def _labels(decisions):
    return {decision.label for decision in decisions if decision.applies}


def test_medication_history_section_propagates_to_every_list_medication() -> None:
    text = "Danh sách thuốc trước nhập viện\n- amlodipine\n- metformin"
    for medication in ("amlodipine", "metformin"):
        decisions = _decisions(text, medication)
        historical = next(item for item in decisions if item.label is AssertionLabel.HISTORICAL)
        assert historical.applies
        assert historical.source_unit_id == "section:0"
        assert historical.inheritance_path == ("section:0",)


def test_local_current_medication_exception_overrides_inherited_history_only() -> None:
    text = "Danh sách thuốc trước nhập viện\n- amlodipine\n- Thuốc hiện tại: metformin"
    decisions = _decisions(text, "metformin")
    assert AssertionLabel.HISTORICAL not in _labels(decisions)
    assert any(item.rule_id == "assert.exception.current_medication.v1" for item in decisions)


def test_family_history_section_propagates_to_multiple_diseases() -> None:
    text = "Tiền sử gia đình\n- đái tháo đường\n- tăng huyết áp"
    assert AssertionLabel.FAMILY in _labels(_decisions(text, "đái tháo đường"))
    assert AssertionLabel.FAMILY in _labels(_decisions(text, "tăng huyết áp"))


def test_negated_family_history_composes_both_labels() -> None:
    decisions = _decisions("Tiền sử gia đình\n- mẹ không bị lao", "lao")
    assert {AssertionLabel.FAMILY, AssertionLabel.NEGATED} <= _labels(decisions)


def test_list_cue_propagates_only_to_nested_descendants() -> None:
    text = "Danh sách\n- tiền sử\n  - hen\n  - COPD\n- đau ngực"
    assert AssertionLabel.HISTORICAL in _labels(_decisions(text, "hen"))
    assert AssertionLabel.HISTORICAL in _labels(_decisions(text, "COPD"))
    assert AssertionLabel.HISTORICAL not in _labels(_decisions(text, "đau ngực"))


def test_heading_without_descendant_does_not_create_an_assertion() -> None:
    decisions = _decisions("Danh sách thuốc trước nhập viện", "Danh sách thuốc trước nhập viện")
    assert not _labels(decisions)


def test_composition_deduplicates_labels_without_dropping_evidence() -> None:
    decisions = _decisions("Tiền sử gia đình\n- mẹ không bị lao", "lao")
    composition = AssertionScopeEngine().compose(decisions)
    assert composition.labels.count(AssertionLabel.FAMILY) == 1
    assert composition.labels.count(AssertionLabel.NEGATED) == 1
    assert len(composition.evidence) == len(decisions)
