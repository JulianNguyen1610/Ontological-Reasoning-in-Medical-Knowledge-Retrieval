"""Regenerate generated-drug candidates from the local RxNorm snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def main() -> None:
    """Build the verified alias index and remap one curated batch."""
    from data_generation.rxnorm_candidate_regenerator import (
        build_active_rxnorm_alias_index,
        remap_rxnorm_candidates,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--terminology-manifest",
        type=Path,
        default=REPOSITORY_ROOT / "specs" / "terminology_manifest.yaml",
    )
    args = parser.parse_args()
    alias_index = build_active_rxnorm_alias_index(args.terminology_manifest)
    print(remap_rxnorm_candidates(args.input_path, args.output_dir, alias_index)["counts"])


if __name__ == "__main__":
    main()
