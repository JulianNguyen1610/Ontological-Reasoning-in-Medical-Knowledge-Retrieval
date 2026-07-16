from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from medlink_ie.provenance.manifest import (
    ArtifactManifest,
    TerminologyManifest,
    load_artifact_manifest,
    load_terminology_manifest,
)


def _checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _terminology_payload(icd_path: Path, rxnorm_path: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "icd": {
            "source": "organizer_provided",
            "variant": "ICD-10",
            "version": "2025",
            "release_date": "2025-01-01",
            "source_path": str(icd_path),
            "checksum_sha256": _checksum(icd_path),
            "license_or_usage_basis": "competition license",
            "include_inactive": False,
            "allowed_code_levels": ["category", "sub-category"],
        },
        "rxnorm": {
            "source": "organizer_provided",
            "release": "2025-03",
            "release_date": "2025-03-03",
            "source_path": str(rxnorm_path),
            "checksum_sha256": _checksum(rxnorm_path),
            "license_or_usage_basis": "UMLS license",
            "include_obsolete": False,
            "allowed_ttys": ["IN", "SCD"],
            "granularity": "concept",
        },
        "alias_enrichment_sources": [
            {
                "name": "organizer_aliases",
                "kind": "alias",
                "source": "organizer_provided",
                "version": "2025.1",
                "source_path": str(icd_path),
                "checksum_sha256": _checksum(icd_path),
                "license_or_usage_basis": "competition license",
            }
        ],
    }


def _artifact_payload(model_path: Path, data_path: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "model_artifacts": [
            {
                "model_name": "local-span-model",
                "parameter_count": 9000000000,
                "path": str(model_path),
                "checksum_sha256": _checksum(model_path),
                "training_config": {"epochs": 3, "learning_rate": 0.0001},
                "dataset_versions": {"train": "synthetic-v1"},
                "code_commit": "a" * 40,
                "seed": 7,
            }
        ],
        "synthetic_data": {
            "generator_name": "medlink-synthetic",
            "generator_version": "1.0.0",
            "path": str(data_path),
            "checksum_sha256": _checksum(data_path),
            "generation_config": {"profile": "clean"},
            "dataset_versions": {"terminology": "2025"},
            "code_commit": "b" * 40,
            "seed": 11,
        },
    }


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_loaders_create_frozen_typed_manifests(tmp_path: Path) -> None:
    icd_path = tmp_path / "icd.csv"
    rxnorm_path = tmp_path / "rxnorm.csv"
    model_path = tmp_path / "model.bin"
    data_path = tmp_path / "synthetic.jsonl"
    for path, content in ((icd_path, b"icd"), (rxnorm_path, b"rxnorm"), (model_path, b"model"), (data_path, b"data")):
        path.write_bytes(content)
    terminology_path = tmp_path / "terminology.yaml"
    artifact_path = tmp_path / "artifact.yaml"
    _write_yaml(terminology_path, _terminology_payload(icd_path, rxnorm_path))
    _write_yaml(artifact_path, _artifact_payload(model_path, data_path))

    terminology = load_terminology_manifest(terminology_path, verify_paths=True)
    artifacts = load_artifact_manifest(artifact_path, verify_paths=True)

    assert isinstance(terminology, TerminologyManifest)
    assert terminology.icd.variant == "ICD-10"
    assert isinstance(artifacts, ArtifactManifest)
    assert artifacts.model_artifacts[0].parameter_count == 9_000_000_000
    with pytest.raises(FrozenInstanceError):
        terminology.icd.version = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("section,field", [("icd", "version"), ("rxnorm", "release")])
def test_missing_terminology_version_is_rejected(tmp_path: Path, section: str, field: str) -> None:
    icd_path = tmp_path / "icd.csv"
    rxnorm_path = tmp_path / "rxnorm.csv"
    icd_path.write_bytes(b"icd")
    rxnorm_path.write_bytes(b"rxnorm")
    payload = _terminology_payload(icd_path, rxnorm_path)
    payload[section][field] = ""  # type: ignore[index]

    with pytest.raises(ValueError, match=field):
        TerminologyManifest.from_mapping(payload)


def test_missing_checksum_and_checksum_mismatch_are_rejected(tmp_path: Path) -> None:
    icd_path = tmp_path / "icd.csv"
    rxnorm_path = tmp_path / "rxnorm.csv"
    icd_path.write_bytes(b"icd")
    rxnorm_path.write_bytes(b"rxnorm")
    payload = _terminology_payload(icd_path, rxnorm_path)
    payload["icd"]["checksum_sha256"] = ""  # type: ignore[index]
    with pytest.raises(ValueError, match="checksum_sha256"):
        TerminologyManifest.from_mapping(payload)

    payload = _terminology_payload(icd_path, rxnorm_path)
    payload["icd"]["checksum_sha256"] = "0" * 64  # type: ignore[index]
    manifest_path = tmp_path / "terminology.yaml"
    _write_yaml(manifest_path, payload)
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_terminology_manifest(manifest_path, verify_paths=True)


def test_unsupported_variant_and_secrets_are_rejected(tmp_path: Path) -> None:
    icd_path = tmp_path / "icd.csv"
    rxnorm_path = tmp_path / "rxnorm.csv"
    icd_path.write_bytes(b"icd")
    rxnorm_path.write_bytes(b"rxnorm")
    payload = _terminology_payload(icd_path, rxnorm_path)
    payload["icd"]["variant"] = "ICD-12"  # type: ignore[index]
    with pytest.raises(ValueError, match="unsupported ICD variant"):
        TerminologyManifest.from_mapping(payload)

    payload = _terminology_payload(icd_path, rxnorm_path)
    payload["api_key"] = "not-allowed"
    with pytest.raises(ValueError, match="secret-like"):
        TerminologyManifest.from_mapping(payload)


def test_model_larger_than_9b_is_rejected(tmp_path: Path) -> None:
    model_path = tmp_path / "model.bin"
    data_path = tmp_path / "synthetic.jsonl"
    model_path.write_bytes(b"model")
    data_path.write_bytes(b"data")
    payload = _artifact_payload(model_path, data_path)
    payload["model_artifacts"][0]["parameter_count"] = 9_000_000_001  # type: ignore[index]

    with pytest.raises(ValueError, match="9B"):
        ArtifactManifest.from_mapping(payload)
