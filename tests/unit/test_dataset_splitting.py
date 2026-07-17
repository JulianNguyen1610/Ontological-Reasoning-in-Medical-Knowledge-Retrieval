from __future__ import annotations

from medlink_ie.dataset.splitting import (
    CHALLENGE_BUCKETS,
    DatasetRecord,
    SplitConfig,
    build_challenge_set,
    create_grouped_splits,
)


def _record(record_id: str, scenario: str, text: str, tags: tuple[str, ...] = ()) -> DatasetRecord:
    return DatasetRecord(
        record_id,
        text,
        {
            "scenario_id": scenario,
            "template_family": f"template-{scenario}",
            "seed_concept": f"concept-{scenario}",
            "generator_prompt_version": "v1",
            "paraphrase_parent": scenario,
            "specialty": "cardiology",
            "annotation_version": "1.0",
            "challenge_tags": list(tags),
        },
    )


def test_grouped_split_has_no_lineage_leakage_and_is_stable() -> None:
    records = tuple(
        record
        for scenario in ("a", "b", "c", "d", "e", "f")
        for record in (
            _record(f"{scenario}-1", scenario, f"note {scenario} first"),
            _record(f"{scenario}-2", scenario, f"note {scenario} paraphrase"),
        )
    )
    config = SplitConfig(seed=19, group_fields=("scenario_id", "paraphrase_parent"))

    first = create_grouped_splits(records, config)
    second = create_grouped_splits(tuple(reversed(records)), config)

    assignments = {
        record.record_id: split
        for split, split_records in first.splits.items()
        for record in split_records
    }
    assert assignments["a-1"] == assignments["a-2"]
    assert assignments["f-1"] == assignments["f-2"]
    assert first.leakage_report.group_leaks == ()
    assert first.manifest.to_dict() == second.manifest.to_dict()


def test_cross_split_duplicate_and_near_duplicate_records_are_reported() -> None:
    records = (
        _record("a", "scenario-a", "BN đau ngực nhiều"),
        _record("b", "scenario-b", "BN đau ngực nhiều"),
        _record("c", "scenario-c", "BN đau ngực nhiều."),
    )
    result = create_grouped_splits(
        records,
        SplitConfig(seed=1, proportions=(0.34, 0.33, 0.33), group_fields=("scenario_id",)),
    )

    assert result.leakage_report.exact_duplicates
    assert result.leakage_report.near_duplicates
    assert result.manifest.source_checksum
    assert set(result.manifest.split_checksums) == {"train", "dev", "test"}


def test_challenge_set_has_all_required_buckets_and_preserves_records() -> None:
    records = tuple(
        _record(f"r-{index}", f"s-{index}", f"note {index}", (bucket,))
        for index, bucket in enumerate(CHALLENGE_BUCKETS)
    )

    challenge = build_challenge_set(records)

    assert tuple(challenge.buckets) == CHALLENGE_BUCKETS
    assert {record.record_id for bucket in challenge.buckets.values() for record in bucket} == {
        record.record_id for record in records
    }
