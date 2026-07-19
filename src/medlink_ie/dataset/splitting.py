"""Leakage-safe, deterministic grouped splits for MedLink-IE datasets.

Groups are indivisible: this module never moves individual records to improve
split ratios.  Near-duplicate detection is reporting-only and compares raw
character shingles without normalizing, trimming, or altering source text.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

SPLIT_NAMES = ("train", "dev", "test")
CHALLENGE_BUCKETS = (
    "type_confusion",
    "assertion_scope",
    "repeated_mentions",
    "drug_strength_form",
    "lab_pairing",
    "icd_level",
    "rxnorm_granularity",
    "unicode_offset",
    "output_schema",
)


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    """Input record retained with immutable metadata for split provenance."""

    record_id: str
    text: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id:
            raise ValueError("record_id must be a non-empty string")
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.metadata, Mapping) or any(
            not isinstance(key, str) for key in self.metadata
        ):
            raise TypeError("metadata must be a mapping with string keys")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SplitConfig:
    """Split policy. Shared values in ``group_fields`` create one lineage group."""

    seed: int = 0
    proportions: tuple[float, float, float] = (0.8, 0.1, 0.1)
    group_fields: tuple[str, ...] = ("scenario_id", "paraphrase_parent")
    near_duplicate_threshold: float = 0.8

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if len(self.proportions) != len(SPLIT_NAMES) or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
            for value in self.proportions
        ):
            raise ValueError("proportions must contain three positive numbers")
        if abs(sum(self.proportions) - 1.0) > 1e-9:
            raise ValueError("proportions must sum to 1.0")
        if not self.group_fields or any(
            not isinstance(field, str) or not field for field in self.group_fields
        ):
            raise ValueError("group_fields must contain non-empty field names")
        if not 0.0 < self.near_duplicate_threshold <= 1.0:
            raise ValueError("near_duplicate_threshold must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class CrossSplitPair:
    left_id: str
    left_split: str
    right_id: str
    right_split: str
    similarity: float


@dataclass(frozen=True, slots=True)
class LeakageReport:
    group_leaks: tuple[CrossSplitPair, ...]
    exact_duplicates: tuple[CrossSplitPair, ...]
    near_duplicates: tuple[CrossSplitPair, ...]


@dataclass(frozen=True, slots=True)
class SplitManifest:
    seed: int
    group_fields: tuple[str, ...]
    source_checksum: str
    split_checksums: Mapping[str, str]
    split_record_ids: Mapping[str, tuple[str, ...]]
    split_group_ids: Mapping[str, tuple[str, ...]]
    statistics: Mapping[str, Mapping[str, int]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "split_checksums", MappingProxyType(dict(self.split_checksums)))
        object.__setattr__(self, "split_record_ids", MappingProxyType(dict(self.split_record_ids)))
        object.__setattr__(self, "split_group_ids", MappingProxyType(dict(self.split_group_ids)))
        object.__setattr__(self, "statistics", MappingProxyType(dict(self.statistics)))

    def to_dict(self) -> dict[str, Any]:
        body = {
            "schema_version": 1,
            "seed": self.seed,
            "group_fields": list(self.group_fields),
            "source_checksum": self.source_checksum,
            "split_checksums": dict(sorted(self.split_checksums.items())),
            "split_record_ids": {name: list(self.split_record_ids[name]) for name in SPLIT_NAMES},
            "split_group_ids": {name: list(self.split_group_ids[name]) for name in SPLIT_NAMES},
            "statistics": {name: dict(self.statistics[name]) for name in SPLIT_NAMES},
        }
        return {**body, "manifest_checksum": _checksum_json(body)}


@dataclass(frozen=True, slots=True)
class SplitResult:
    splits: Mapping[str, tuple[DatasetRecord, ...]]
    manifest: SplitManifest
    leakage_report: LeakageReport


@dataclass(frozen=True, slots=True)
class ChallengeSet:
    buckets: Mapping[str, tuple[DatasetRecord, ...]]


def create_grouped_splits(
    records: Iterable[DatasetRecord], config: SplitConfig = SplitConfig()
) -> SplitResult:
    """Assign entire metadata groups to train/dev/test using a stable seeded order."""
    ordered = tuple(sorted(records, key=lambda record: record.record_id))
    _validate_records(ordered, config)
    groups, record_groups = _lineage_groups(ordered, config.group_fields)
    assignments = _assign_groups(groups, config)
    splits = {
        split: tuple(
            sorted(
                (record for group_id in assignments[split] for record in groups[group_id]),
                key=lambda record: record.record_id,
            )
        )
        for split in SPLIT_NAMES
    }
    manifest = _manifest(splits, assignments, config, ordered)
    return SplitResult(
        MappingProxyType(splits),
        manifest,
        _detect_leakage(splits, config, record_groups),
    )


def build_challenge_set(records: Iterable[DatasetRecord]) -> ChallengeSet:
    """Collect explicitly tagged challenge records into all required buckets."""
    buckets: dict[str, list[DatasetRecord]] = {bucket: [] for bucket in CHALLENGE_BUCKETS}
    for record in records:
        tags = _challenge_tags(record)
        for bucket in tags:
            buckets[bucket].append(record)
    return ChallengeSet(
        MappingProxyType(
            {
                bucket: tuple(sorted(items, key=lambda record: record.record_id))
                for bucket, items in buckets.items()
            }
        )
    )


def write_split_manifest(path: Path, manifest: SplitManifest) -> None:
    """Atomically persist a canonical JSON split manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(
            manifest.to_dict(), handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        handle.write("\n")
    os.replace(temporary, path)


def _validate_records(records: tuple[DatasetRecord, ...], config: SplitConfig) -> None:
    seen_ids: set[str] = set()
    for record in records:
        if not isinstance(record, DatasetRecord):
            raise TypeError("records must contain DatasetRecord values")
        if record.record_id in seen_ids:
            raise ValueError(f"duplicate record_id: {record.record_id}")
        seen_ids.add(record.record_id)
        if not any(
            isinstance(record.metadata.get(field), str) and record.metadata[field]
            for field in config.group_fields
        ):
            raise ValueError(f"record {record.record_id} has no usable group field")


def _lineage_groups(
    records: tuple[DatasetRecord, ...], fields: tuple[str, ...]
) -> tuple[dict[str, list[DatasetRecord]], dict[str, str]]:
    """Build connected components so a shared lineage value can never leak."""
    parents = {record.record_id: record.record_id for record in records}

    def find(record_id: str) -> str:
        while parents[record_id] != record_id:
            parents[record_id] = parents[parents[record_id]]
            record_id = parents[record_id]
        return record_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    owners: dict[tuple[str, str], str] = {}
    for record in records:
        for field in fields:
            value = record.metadata.get(field)
            if not isinstance(value, str) or not value:
                continue
            token = (field, value)
            if token in owners:
                union(record.record_id, owners[token])
            else:
                owners[token] = record.record_id
    members: dict[str, list[DatasetRecord]] = {}
    for record in records:
        members.setdefault(find(record.record_id), []).append(record)
    groups: dict[str, list[DatasetRecord]] = {}
    record_groups: dict[str, str] = {}
    for group_members in members.values():
        group_id = _checksum_json(sorted(record.record_id for record in group_members))
        groups[group_id] = group_members
        record_groups.update({record.record_id: group_id for record in group_members})
    return groups, record_groups


def _assign_groups(
    groups: Mapping[str, list[DatasetRecord]], config: SplitConfig
) -> dict[str, list[str]]:
    total = sum(map(len, groups.values()))
    targets = {name: total * config.proportions[index] for index, name in enumerate(SPLIT_NAMES)}
    assignments: dict[str, list[str]] = {name: [] for name in SPLIT_NAMES}
    counts = {name: 0 for name in SPLIT_NAMES}
    group_order = sorted(groups, key=lambda group_id: _seeded_key(group_id, config.seed))
    # Seed each non-empty requested split before greedy balancing.  Without this,
    # a small target split can consume the earliest groups and leave train empty.
    initial = min(len(group_order), len(SPLIT_NAMES))
    for split, group_id in zip(SPLIT_NAMES, group_order[:initial], strict=True):
        assignments[split].append(group_id)
        counts[split] += len(groups[group_id])
    for group_id in group_order[initial:]:
        size = len(groups[group_id])
        split = min(
            SPLIT_NAMES,
            key=lambda name: (
                counts[name] / targets[name] if targets[name] else 0.0,
                counts[name],
                SPLIT_NAMES.index(name),
            ),
        )
        assignments[split].append(group_id)
        counts[split] += size
    return assignments


def _manifest(
    splits: Mapping[str, tuple[DatasetRecord, ...]],
    assignments: Mapping[str, list[str]],
    config: SplitConfig,
    records: tuple[DatasetRecord, ...],
) -> SplitManifest:
    split_ids = {name: tuple(record.record_id for record in splits[name]) for name in SPLIT_NAMES}
    return SplitManifest(
        config.seed,
        config.group_fields,
        _checksum_json([_record_payload(record) for record in records]),
        {name: _checksum_json(split_ids[name]) for name in SPLIT_NAMES},
        split_ids,
        {name: tuple(sorted(assignments[name])) for name in SPLIT_NAMES},
        {
            name: {"records": len(splits[name]), "groups": len(assignments[name])}
            for name in SPLIT_NAMES
        },
    )


def _detect_leakage(
    splits: Mapping[str, tuple[DatasetRecord, ...]],
    config: SplitConfig,
    record_groups: Mapping[str, str],
) -> LeakageReport:
    indexed = [(split, record) for split in SPLIT_NAMES for record in splits[split]]
    groups: dict[str, tuple[str, DatasetRecord]] = {}
    group_leaks: list[CrossSplitPair] = []
    for split, record in indexed:
        group_id = record_groups[record.record_id]
        if group_id in groups and groups[group_id][0] != split:
            other_split, other_record = groups[group_id]
            group_leaks.append(
                CrossSplitPair(other_record.record_id, other_split, record.record_id, split, 1.0)
            )
        else:
            groups[group_id] = (split, record)
    exact: list[CrossSplitPair] = []
    near: list[CrossSplitPair] = []
    for index, (left_split, left) in enumerate(indexed):
        for right_split, right in indexed[index + 1 :]:
            if left_split == right_split:
                continue
            if _text_checksum(left.text) == _text_checksum(right.text):
                exact.append(
                    CrossSplitPair(left.record_id, left_split, right.record_id, right_split, 1.0)
                )
                continue
            similarity = _shingle_similarity(left.text, right.text)
            if similarity >= config.near_duplicate_threshold:
                near.append(
                    CrossSplitPair(
                        left.record_id, left_split, right.record_id, right_split, similarity
                    )
                )
    return LeakageReport(tuple(group_leaks), tuple(exact), tuple(near))


def _challenge_tags(record: DatasetRecord) -> tuple[str, ...]:
    values = record.metadata.get("challenge_tags", record.metadata.get("challenge_buckets", ()))
    if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) for value in values):
        raise ValueError(f"record {record.record_id} challenge tags must be a list of strings")
    unknown = set(values) - set(CHALLENGE_BUCKETS)
    if unknown:
        raise ValueError(f"record {record.record_id} has unknown challenge tags: {sorted(unknown)}")
    return tuple(sorted(set(values)))


def _record_payload(record: DatasetRecord) -> dict[str, Any]:
    return {"record_id": record.record_id, "text": record.text, "metadata": dict(record.metadata)}


def _seeded_key(group_id: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{group_id}".encode("utf-8")).hexdigest()


def _text_checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _checksum_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _shingle_similarity(left: str, right: str, width: int = 3) -> float:
    left_shingles = _shingles(left, width)
    right_shingles = _shingles(right, width)
    return len(left_shingles & right_shingles) / len(left_shingles | right_shingles)


def _shingles(text: str, width: int) -> frozenset[str]:
    if len(text) <= width:
        return frozenset({text})
    return frozenset(text[index : index + width] for index in range(len(text) - width + 1))
