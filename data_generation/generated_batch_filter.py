"""Immutable curation for one generated JSONL batch.

The filter never rewrites a retained sample.  It emits an auditable derived
dataset and isolates rows that violate deterministic quality rules.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from data_generation.config import VALID_ASSERTIONS, VALID_ENTITY_TYPES

CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def curate_jsonl_batch(input_path: Path, output_dir: Path) -> Dict[str, Any]:
    """Create clean and rejected JSONL views from one immutable input batch."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for line_number, raw_line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line:
            rejected.append(_rejection(line_number, None, ["blank_line"]))
            continue
        try:
            sample = json.loads(raw_line)
        except json.JSONDecodeError:
            rejected.append(_rejection(line_number, None, ["invalid_json"]))
            continue

        reasons = _rejection_reasons(sample)
        if reasons:
            rejected.append(_rejection(line_number, sample, reasons))
        else:
            accepted.append(sample)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    _write_jsonl(output_dir / f"{stem}_clean.jsonl", accepted)
    _write_jsonl(output_dir / f"{stem}_rejected.jsonl", rejected)
    report = {
        "format_version": 1,
        "input_path": str(input_path),
        "rules": [
            "exact_span",
            "valid_entity_type",
            "valid_assertion",
            "nonempty_linking_candidate",
            "repeated_profile_has_multiple_annotated_positions",
            "no_cjk_surface_noise",
        ],
        "counts": {
            "input": len(accepted) + len(rejected),
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
        "rejection_reasons": dict(Counter(item["decision_trace"]["reason"] for item in rejected)),
    }
    (output_dir / f"{stem}_curation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _rejection_reasons(sample: Any) -> List[str]:
    if not isinstance(sample, dict):
        return ["sample_not_object"]
    text = sample.get("text")
    entities = sample.get("entities")
    if not isinstance(text, str):
        return ["text_not_string"]
    if not isinstance(entities, list):
        return ["entities_not_list"]

    reasons: List[str] = []
    if CJK_PATTERN.search(text):
        reasons.append("contains_cjk_noise")
    for entity in entities:
        reasons.extend(_entity_rejection_reasons(text, entity))
    if sample.get("challenge_profile") == "repeated_mention" and not _has_repeated_annotation(
        entities
    ):
        reasons.append("missing_repeated_annotation")
    return list(dict.fromkeys(reasons))


def _entity_rejection_reasons(text: str, entity: Any) -> List[str]:
    if not isinstance(entity, dict):
        return ["entity_not_object"]
    entity_text = entity.get("text")
    position = entity.get("position")
    entity_type = entity.get("type")
    assertions = entity.get("assertions")
    candidates = entity.get("candidates")
    reasons: List[str] = []
    if entity_type not in VALID_ENTITY_TYPES:
        reasons.append("invalid_entity_type")
    if not isinstance(assertions, list) or any(
        value not in VALID_ASSERTIONS for value in assertions
    ):
        reasons.append("invalid_assertion")
    if not _has_exact_span(text, entity_text, position):
        reasons.append("bad_exact_span")
    if not isinstance(candidates, list) or any(not isinstance(value, str) for value in candidates):
        reasons.append("invalid_candidates_shape")
    elif entity_type in {"CHẨN_ĐOÁN", "THUỐC"} and any(not value for value in candidates):
        reasons.append("empty_linking_candidate")
    return reasons


def _has_exact_span(text: str, entity_text: Any, position: Any) -> bool:
    return (
        isinstance(entity_text, str)
        and isinstance(position, list)
        and len(position) == 2
        and all(isinstance(value, int) for value in position)
        and 0 <= position[0] < position[1] <= len(text)
        and text[position[0] : position[1]] == entity_text
    )


def _has_repeated_annotation(entities: Iterable[Any]) -> bool:
    positions_by_text: Dict[str, set[Tuple[int, int]]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_text = entity.get("text")
        position = entity.get("position")
        if (
            isinstance(entity_text, str)
            and isinstance(position, list)
            and len(position) == 2
            and all(isinstance(value, int) for value in position)
        ):
            positions_by_text.setdefault(entity_text, set()).add((position[0], position[1]))
    return any(len(positions) >= 2 for positions in positions_by_text.values())


def _rejection(line_number: int, sample: Any, reasons: List[str]) -> Dict[str, Any]:
    return {
        "source_line": line_number,
        "decision_trace": {"decision": "rejected", "reason": reasons[0], "all_reasons": reasons},
        "sample": sample,
    }


def _write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
