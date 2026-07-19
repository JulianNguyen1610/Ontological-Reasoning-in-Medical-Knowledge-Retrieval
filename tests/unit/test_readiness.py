from __future__ import annotations

import json
from pathlib import Path

from medlink_ie.readiness import validate_run_manifest


def test_run_manifest_gate_requires_finalized_complete_counts(tmp_path: Path) -> None:
    manifest = tmp_path / "run_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "finalized",
                "sample_order": ["1.txt", "2.txt"],
                "counts": {"completed": 1, "failed": 1, "resumed": 0},
            }
        ),
        encoding="utf-8",
    )

    assert validate_run_manifest(tmp_path).passed is True


def test_run_manifest_gate_rejects_incomplete_counts(tmp_path: Path) -> None:
    (tmp_path / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "finalized",
                "sample_order": ["1.txt"],
                "counts": {"completed": 0, "failed": 0, "resumed": 0},
            }
        ),
        encoding="utf-8",
    )

    assert validate_run_manifest(tmp_path).passed is False
