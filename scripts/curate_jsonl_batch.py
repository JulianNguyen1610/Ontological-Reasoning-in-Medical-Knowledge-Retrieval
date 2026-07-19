"""Create an immutable curated view from a generated JSONL batch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> None:
    """Parse CLI arguments and curate one generated JSONL batch."""
    from data_generation.generated_batch_filter import curate_jsonl_batch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = curate_jsonl_batch(args.input_path, args.output_dir)
    print(report["counts"])


if __name__ == "__main__":
    main()
