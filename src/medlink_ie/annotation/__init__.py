"""Gold annotation storage, validation, and review comparison utilities."""

from .gold import (
    AdjudicationStatus,
    AnnotatorComparisonReport,
    GoldEntity,
    GoldJsonlReadReport,
    GoldRecordError,
    GoldSample,
    ImmutableSourceReference,
    compare_annotators,
    read_gold_jsonl,
    validate_gold_sample,
    write_gold_jsonl,
)

__all__ = [
    "AdjudicationStatus",
    "AnnotatorComparisonReport",
    "GoldEntity",
    "GoldJsonlReadReport",
    "GoldRecordError",
    "GoldSample",
    "ImmutableSourceReference",
    "compare_annotators",
    "read_gold_jsonl",
    "validate_gold_sample",
    "write_gold_jsonl",
]
