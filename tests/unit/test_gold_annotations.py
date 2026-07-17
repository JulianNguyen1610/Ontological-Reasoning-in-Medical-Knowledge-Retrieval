from __future__ import annotations

from pathlib import Path

import pytest

from medlink_ie.annotation.gold import (
    AdjudicationStatus,
    GoldEntity,
    GoldRecordError,
    GoldSample,
    ImmutableSourceReference,
    compare_annotators,
    read_gold_jsonl,
    validate_gold_sample,
    write_gold_jsonl,
)
from medlink_ie.domain import AssertionLabel, EntityType


def _entity(
    text: str,
    start: int,
    end: int,
    entity_type: EntityType = EntityType.SYMPTOM,
    assertions: tuple[AssertionLabel, ...] = (),
    candidates: tuple[str, ...] | None = None,
) -> GoldEntity:
    return GoldEntity(text, start, end, entity_type, assertions, candidates)


def test_unicode_and_repeated_mentions_are_positionally_preserved(tmp_path: Path) -> None:
    raw = "Bệnh nhân ho 😊, sau đó ho."
    first = raw.index("ho")
    second = raw.rindex("ho")
    sample = GoldSample(
        "note-1",
        raw,
        None,
        (_entity("ho", first, first + 2), _entity("ho", second, second + 2)),
    )

    assert validate_gold_sample(sample).is_valid
    path = tmp_path / "gold.jsonl"
    write_gold_jsonl(path, (sample,))
    loaded = read_gold_jsonl(path)
    assert loaded.errors == ()
    assert loaded.samples == (sample,)


def test_empty_annotations_and_immutable_reference_are_valid() -> None:
    sample = GoldSample(
        "empty",
        None,
        ImmutableSourceReference(
            "source/empty.txt",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),
        (),
        AdjudicationStatus.PENDING,
    )

    assert validate_gold_sample(sample, raw_text="").is_valid


def test_wrong_offsets_duplicates_and_confirmed_overlap_are_reported() -> None:
    raw = "đau ngực"
    invalid = GoldSample(
        "bad",
        raw,
        None,
        (
            _entity("đau", 1, 4),
            _entity("đau", 1, 4),
            _entity("ngực", 4, 8),
        ),
        AdjudicationStatus.CONFIRMED,
    )
    report = validate_gold_sample(invalid)
    assert not report.is_valid
    assert any(issue.code == "text_mismatch" for issue in report.errors)
    assert any(issue.code == "duplicate_entity" for issue in report.errors)
    assert any(issue.code == "overlap_requires_adjudication" for issue in report.errors)


def test_malformed_jsonl_records_are_reported_without_stopping_batch(tmp_path: Path) -> None:
    path = tmp_path / "malformed.jsonl"
    path.write_text(
        '{"sample_id":"ok","raw_text":"ho","entities":[]}\nnot json\n{"sample_id": 2}\n',
        encoding="utf-8",
    )

    report = read_gold_jsonl(path)
    assert [sample.sample_id for sample in report.samples] == ["ok"]
    assert [error.line_number for error in report.errors] == [2, 3]

    with pytest.raises(GoldRecordError):
        read_gold_jsonl(path, strict=True)


def test_annotator_comparison_separates_disagreement_dimensions() -> None:
    raw = "ho sốt amlodipine"
    left = GoldSample(
        "note",
        raw,
        None,
        (
            _entity("ho", 0, 2, assertions=(AssertionLabel.NEGATED,)),
            _entity("sốt", 3, 6),
            _entity("amlodipine", 7, 17, EntityType.MEDICATION, candidates=("123",)),
        ),
    )
    right = GoldSample(
        "note",
        raw,
        None,
        (
            _entity("ho", 0, 2),
            _entity("sốt", 3, 6, EntityType.DIAGNOSIS),
            _entity("amlodipin", 7, 16, EntityType.MEDICATION, candidates=("456",)),
        ),
    )

    report = compare_annotators(left, right)
    assert len(report.type_disagreements) == 1
    assert len(report.assertion_disagreements) == 1
    assert len(report.boundary_disagreements) == 1
    assert len(report.candidate_disagreements) == 1
    assert report.unmatched_left == ()
    assert report.unmatched_right == ()
