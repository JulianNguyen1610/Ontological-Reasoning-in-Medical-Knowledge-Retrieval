from __future__ import annotations

import json
from pathlib import Path

import pytest

from medlink_ie.evaluation.scorer import ScoringConfig, score_entities

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "scorer" / "framework_v1_cases.json"
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "case_name", ["perfect", "empty", "extra", "missing", "wrong_type", "shifted_span", "repeated"]
)
def test_framework_v1_golden_entity_cases(case_name: str) -> None:
    case = CASES[case_name]

    result = score_entities(case["gold"], case["prediction"], ScoringConfig.framework_v1())

    assert result.entity_f1 == case["entity_f1"]
    if "final_score" in case:
        assert result.final_score == case["final_score"]


def test_assertion_and_candidate_jaccard_handle_exact_missing_and_extra_values() -> None:
    gold = [
        {
            "text": "amlodipine",
            "type": "THUỐC",
            "position": [0, 10],
            "assertions": ["isHistorical", "isNegated"],
            "candidates": ["rx-1", "rx-2"],
        }
    ]
    prediction = [
        {
            "text": "amlodipine",
            "type": "THUỐC",
            "position": [0, 10],
            "assertions": ["isHistorical", "isFamily"],
            "candidates": ["rx-1", "rx-3"],
        }
    ]

    result = score_entities(gold, prediction, ScoringConfig.framework_v1())

    assert result.assertion_jaccard == pytest.approx(1 / 3)
    assert result.candidate_jaccard == pytest.approx(1 / 3)


def test_optional_field_policy_is_explicit_and_configurable() -> None:
    gold = [{"text": "ho", "type": "TRIỆU_CHỨNG", "position": [0, 2]}]
    prediction = [
        {
            "text": "ho",
            "type": "TRIỆU_CHỨNG",
            "position": [0, 2],
            "assertions": [],
            "candidates": [],
        }
    ]

    framework_result = score_entities(gold, prediction, ScoringConfig.framework_v1())
    strict_result = score_entities(
        gold,
        prediction,
        ScoringConfig.framework_v1(optional_none_equals_empty=False),
    )

    assert framework_result.assertion_jaccard == 1.0
    assert framework_result.candidate_jaccard == 1.0
    assert strict_result.assertion_jaccard == 0.0
    assert strict_result.candidate_jaccard == 0.0


def test_scoring_is_deterministic_and_returns_diagnostic_breakdown() -> None:
    gold = CASES["repeated"]["gold"]
    prediction = CASES["repeated"]["prediction"]

    first = score_entities(gold, prediction, ScoringConfig.framework_v1())
    second = score_entities(gold, prediction, ScoringConfig.framework_v1())

    assert first == second
    assert first.matched_count == 2
    assert first.unmatched_gold_count == 0
    assert first.unmatched_prediction_count == 0
