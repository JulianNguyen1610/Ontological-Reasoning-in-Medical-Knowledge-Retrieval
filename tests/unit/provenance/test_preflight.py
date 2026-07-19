from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from medlink_ie.provenance.preflight import load_artifact_inventory, verify_artifact_inventory


def test_preflight_reports_required_missing_and_optional_missing_without_network(
    tmp_path: Path,
) -> None:
    present = tmp_path / "present.bin"
    present.write_bytes(b"offline")
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(
        f"""schema_version: 1
artifacts:
  - name: present
    path: present.bin
    size_bytes: 7
    sha256: {sha256(b"offline").hexdigest()}
    license: test
    required: true
  - name: required-missing
    path: missing.bin
    size_bytes: 1
    sha256: "{"0" * 64}"
    license: test
    required: true
  - name: optional-missing
    path: optional.bin
    size_bytes: 1
    sha256: "{"0" * 64}"
    license: test
    required: false
""",
        encoding="utf-8",
    )

    report = verify_artifact_inventory(load_artifact_inventory(inventory))

    assert report.ok is False
    assert report.required_failure_count == 1
    assert [item.status for item in report.artifacts] == ["verified", "missing", "missing"]
    assert report.network_accessed is False


def test_preflight_rejects_model_above_parameter_limit(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(
        f"""schema_version: 1
artifacts:
  - name: oversized
    path: missing.bin
    size_bytes: 1
    sha256: "{"0" * 64}"
    license: test
    required: false
    parameter_count: 9000000001
""",
        encoding="utf-8",
    )

    report = verify_artifact_inventory(load_artifact_inventory(inventory))

    assert report.artifacts[0].status == "invalid"
