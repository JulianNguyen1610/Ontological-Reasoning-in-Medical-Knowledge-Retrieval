from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "annotation" / "adjudication_matrix.yaml"


def test_framework_v1_annotation_matrix_has_exact_entities_or_explicit_rejection() -> None:
    payload = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = payload["cases"]

    assert len(cases) == 100
    for case in cases:
        entities = case["expected_entities"]
        rejection = case.get("expected_rejection")
        assert isinstance(entities, list)
        assert bool(entities) != bool(rejection)
        for entity in entities:
            start, end = entity["position"]
            assert entity["text"] == case["raw_text"][start:end]
            assert 0 <= start < end <= len(case["raw_text"])
