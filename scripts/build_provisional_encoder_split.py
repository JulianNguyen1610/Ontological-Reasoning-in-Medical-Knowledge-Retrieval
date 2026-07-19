"""Build a clearly labelled grouped split from curated synthetic data.

This utility is for local pipeline checks only.  It does not promote synthetic
annotations to BTC-adjudicated gold or official benchmark evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from medlink_ie.dataset import (
    DatasetRecord,
    SplitConfig,
    create_grouped_splits,
    write_split_manifest,
)


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/curated/gold.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/benchmarks/provisional_synthetic_v1/grouped_split_manifest.json"),
    )
    parser.add_argument("--seed", type=int, default=17)
    parsed = parser.parse_args(arguments)
    records = _records(parsed.input)
    result = create_grouped_splits(
        records,
        SplitConfig(
            seed=parsed.seed,
            proportions=(0.6, 0.2, 0.2),
            group_fields=("scenario_id",),
        ),
    )
    if result.leakage_report.group_leaks or result.leakage_report.exact_duplicates:
        raise ValueError("provisional source contains cross-split leakage")
    if parsed.output.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {parsed.output}")
    write_split_manifest(parsed.output, result.manifest)
    return 0


def _records(path: Path) -> tuple[DatasetRecord, ...]:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("curated gold input must be a JSON array")
    records = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ValueError("curated gold records must be objects")
        text, scenario = value.get("text"), value.get("scenario_id")
        if not isinstance(text, str) or not isinstance(scenario, str) or not scenario:
            raise ValueError("each curated record needs text and scenario_id")
        records.append(
            DatasetRecord(
                f"provisional:{index:04d}",
                text,
                {"scenario_id": scenario, "benchmark_status": "provisional_synthetic_v1"},
            )
        )
    return tuple(records)


if __name__ == "__main__":
    raise SystemExit(main())
