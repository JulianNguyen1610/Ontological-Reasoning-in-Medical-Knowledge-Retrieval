"""Create clean, auditable dataset views from generated raw batches."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Support direct execution with ``python scripts/curate_generated_data.py``.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from data_generation.dataset_curator import GeneratedDataCurator
from data_generation.generators.text_generator import TextGenerator


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw_generated"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/curated"))
    parser.add_argument("--hard-duplicate-threshold", type=float, default=0.72)
    parser.add_argument("--soft-duplicate-threshold", type=float, default=0.62)
    parser.add_argument("--validation-ratio", type=float, default=0.15)
    args = parser.parse_args()

    assertion_cues = TextGenerator(None).assertion_cues
    report = GeneratedDataCurator(assertion_cues).curate(
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        hard_duplicate_threshold=args.hard_duplicate_threshold,
        soft_duplicate_threshold=args.soft_duplicate_threshold,
        validation_ratio=args.validation_ratio,
    )
    print(f"Curated {report['counts']['input']} samples into {args.output_dir}")
    print(report["counts"])


if __name__ == "__main__":
    main()
