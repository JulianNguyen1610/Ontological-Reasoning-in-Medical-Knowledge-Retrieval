from __future__ import annotations

import pytest

from medlink_ie.assertions.engine import AssertionScopeEngine
from medlink_ie.domain import AssertionLabel, SourceDocument
from medlink_ie.structure.analyzer import StructuralAnalyzer


def _decisions(text: str, entity: str, occurrence: int = 0):
    document = SourceDocument("assertion-test", text.encode("utf-8"), text, "utf-8", False, "none")
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(entity, start + 1)
    return AssertionScopeEngine().classify(
        raw_text=text,
        entity_start=start,
        entity_end=start + len(entity),
        structure=StructuralAnalyzer().analyze(document),
    )


def _labels(decisions):
    return {decision.label for decision in decisions if decision.applies}


def test_contrast_terminates_forward_negation_scope() -> None:
    pain = _decisions("không sốt nhưng ho", "sốt")
    cough = _decisions("không sốt nhưng ho", "ho")

    assert AssertionLabel.NEGATED in _labels(pain)
    assert AssertionLabel.NEGATED not in _labels(cough)


def test_preceding_negation_and_historical_cues_include_raw_evidence_spans() -> None:
    decisions = _decisions("chưa ghi nhận ho. tiền sử hen", "ho")
    historical = _decisions("chưa ghi nhận ho. tiền sử hen", "hen")

    negation = next(item for item in decisions if item.label is AssertionLabel.NEGATED)
    history = next(item for item in historical if item.label is AssertionLabel.HISTORICAL)
    assert negation.applies and negation.cue_text == "chưa ghi nhận"
    assert negation.cue_span == (0, len("chưa ghi nhận"))
    assert negation.scope_span[0] <= negation.cue_span[0] < negation.scope_span[1]
    assert history.applies and history.rule_id.startswith("assert.history")


@pytest.mark.parametrize("cue", ["tiền sử", "trước nhập viện"])
def test_historical_cues_scope_the_following_entity(cue: str) -> None:
    decisions = _decisions(f"{cue}: tăng huyết áp", "tăng huyết áp")
    assert AssertionLabel.HISTORICAL in _labels(decisions)


def test_family_relation_and_historical_cues_can_both_apply() -> None:
    labels = _labels(_decisions("tiền sử gia đình: mẹ bị đái tháo đường", "đái tháo đường"))
    assert {AssertionLabel.FAMILY, AssertionLabel.HISTORICAL} <= labels


def test_list_item_scope_does_not_leak_to_another_item() -> None:
    text = "1. không sốt\n2. ho"
    assert AssertionLabel.NEGATED in _labels(_decisions(text, "sốt"))
    assert AssertionLabel.NEGATED not in _labels(_decisions(text, "ho"))


def test_explicit_terminator_stops_scope_before_later_entity() -> None:
    labels = _labels(_decisions("không đau, ghi nhận ho", "ho"))
    assert AssertionLabel.NEGATED not in labels


def test_quoted_and_template_cues_are_excluded_by_default_rule() -> None:
    quoted = _decisions('Ghi chú: "không ho"; bệnh nhân ho', "ho", 1)
    assert AssertionLabel.NEGATED not in _labels(quoted)
    assert AssertionLabel.NEGATED not in _labels(_decisions("{{không ho}}; bệnh nhân ho", "ho", 1))
