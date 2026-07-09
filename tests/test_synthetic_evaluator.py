import json

from data_generation.evaluation.synthetic_evaluator import SyntheticDataEvaluator


def _clean_samples():
    return [
        {
            "text": "BN đau ngực. Troponin I tăng.",
            "entities": [
                {
                    "text": "đau ngực",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": [],
                    "candidates": [],
                    "position": [3, 11],
                },
                {
                    "text": "Troponin I",
                    "type": "TÊN_XÉT_NGHIỆM",
                    "assertions": [],
                    "candidates": [],
                    "position": [13, 23],
                },
            ],
            "scenario_id": "clean_1",
        }
    ]


def _hard_samples():
    return [
        {
            "text": "BN đau ngực. SĐT 0912345678.",
            "entities": [
                {
                    "text": "đau ngực",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": [],
                    "candidates": [],
                    "position": [999, 1007],
                }
            ],
            "scenario_id": "hard_1",
        },
        {
            "text": "",
            "entities": [],
            "scenario_id": "hard_2",
        },
    ]


def _human_samples():
    return [
        {
            "text": "BN sốt, HA ổn.",
            "entities": [
                {
                    "text": "sốt",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": ["isHistorical"],
                    "candidates": [],
                    "position": [3, 6],
                }
            ],
            "scenario_id": "human_1",
        }
    ]


def test_multiple_splits_can_be_loaded(tmp_path):
    clean_path = tmp_path / "clean.json"
    hard_path = tmp_path / "hard.jsonl"
    human_path = tmp_path / "human.json"
    clean_path.write_text(json.dumps(_clean_samples(), ensure_ascii=False), encoding="utf-8")
    with open(hard_path, "w", encoding="utf-8") as handle:
        for sample in _hard_samples():
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
    human_path.write_text(json.dumps(_human_samples(), ensure_ascii=False), encoding="utf-8")

    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_splits(
        {
            "synthetic_clean": clean_path,
            "synthetic_hard": hard_path,
            "human_reviewed": human_path,
        }
    )

    assert report["synthetic_clean"]["structural_fidelity"]["total_samples"] == 1
    assert report["synthetic_hard"]["structural_fidelity"]["total_samples"] == 2
    assert report["human_reviewed"]["structural_fidelity"]["total_samples"] == 1


def test_split_summary_is_correct():
    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_splits(
        {
            "synthetic_clean": "dummy_clean.json",
            "synthetic_hard": "dummy_hard.json",
        }
    ) if False else evaluator._build_cross_split_analysis(
        evaluator._evaluate_split(_clean_samples(), "synthetic_clean"),
        evaluator._evaluate_split(_hard_samples(), "synthetic_hard"),
        evaluator._evaluate_split(_human_samples(), "human_reviewed"),
    )

    assert "clean_vs_hard_entity_drop" in report
    assert "clean_vs_hard_assertion_shift" in report


def test_quality_gate_warns_when_hard_split_is_worse_than_clean_split():
    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_splits_from_samples(
        {
            "synthetic_clean": _clean_samples(),
            "synthetic_hard": _hard_samples(),
            "human_reviewed": _human_samples(),
        }
    )

    assert any(
        "synthetic_hard has worse span quality" in warning
        for warning in report["final_recommendation"]["warnings"]
    )


def test_human_split_is_prioritized_in_summary():
    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_splits_from_samples(
        {
            "synthetic_clean": _clean_samples(),
            "synthetic_hard": _hard_samples(),
            "human_reviewed": _human_samples(),
        }
    )

    assert "Prioritize human_reviewed split" in report["cross_split_analysis"]["human_split_priority_note"]


def test_utility_proxy_does_not_crash_with_empty_split():
    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_splits_from_samples({"synthetic_clean": []})

    assert report["synthetic_clean"]["utility_proxy"]["score"] == 0.5


def test_json_and_jsonl_are_supported(tmp_path):
    clean_path = tmp_path / "clean.json"
    hard_path = tmp_path / "hard.jsonl"
    clean_path.write_text(json.dumps(_clean_samples(), ensure_ascii=False), encoding="utf-8")
    with open(hard_path, "w", encoding="utf-8") as handle:
        for sample in _hard_samples():
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")

    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_splits(
        {
            "synthetic_clean": clean_path,
            "synthetic_hard": hard_path,
        }
    )

    assert report["synthetic_clean"]["structural_fidelity"]["total_samples"] == 1
    assert report["synthetic_hard"]["privacy"]["privacy_warning_count"] >= 1

def test_manifest_is_supported(tmp_path):
    clean_path = tmp_path / "clean.json"
    hard_path = tmp_path / "hard.json"
    human_path = tmp_path / "human.json"
    manifest_path = tmp_path / "manifest.json"
    clean_path.write_text(json.dumps(_clean_samples(), ensure_ascii=False), encoding="utf-8")
    hard_path.write_text(json.dumps(_hard_samples(), ensure_ascii=False), encoding="utf-8")
    human_path.write_text(json.dumps(_human_samples(), ensure_ascii=False), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "splits": {
                    "synthetic_clean": str(clean_path),
                    "synthetic_hard": str(hard_path),
                    "human_reviewed": str(human_path),
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_manifest(manifest_path)

    assert report["human_reviewed"]["structural_fidelity"]["total_samples"] == 1


def test_missing_clean_split_blocks_training():
    evaluator = SyntheticDataEvaluator()
    report = evaluator.evaluate_splits_from_samples(
        {
            "synthetic_hard": _hard_samples(),
            "human_reviewed": _human_samples(),
        }
    )

    assert report["final_recommendation"]["ready_for_training"] is False
    assert any(
        "synthetic_clean split is missing or empty." == issue
        for issue in report["final_recommendation"]["blocking_issues"]
    )
