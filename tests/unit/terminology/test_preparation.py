from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from medlink_ie.provenance.manifest import TerminologyManifest, load_terminology_manifest
from medlink_ie.terminology.preparation import (
    AliasRecord,
    ConceptRecord,
    ICD10ZipAdapter,
    ICDAdapter,
    RxNormAdapter,
    RxNormZipAdapter,
    prepare_canonical_tables,
    prepare_from_manifest,
    write_canonical_tables,
)


def _checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _manifest(tmp_path: Path) -> TerminologyManifest:
    icd = tmp_path / "icd.fixture"
    rxnorm = tmp_path / "rxnorm.fixture"
    aliases = tmp_path / "aliases.yaml"
    icd.write_text("icd", encoding="utf-8")
    rxnorm.write_text("rxnorm", encoding="utf-8")
    aliases.write_text("aliases: []\n", encoding="utf-8")
    return TerminologyManifest.from_mapping(
        {
            "schema_version": 1,
            "icd": {
                "source": "fixture",
                "variant": "ICD-10",
                "version": "fixture-1",
                "release_date": "2025-01-01",
                "source_path": str(icd),
                "checksum_sha256": _checksum(icd),
                "license_or_usage_basis": "test",
                "include_inactive": False,
                "allowed_code_levels": ["category_3"],
            },
            "rxnorm": {
                "source": "fixture",
                "release": "fixture-2",
                "release_date": "2025-01-01",
                "source_path": str(rxnorm),
                "checksum_sha256": _checksum(rxnorm),
                "license_or_usage_basis": "test",
                "include_obsolete": False,
                "allowed_ttys": ["IN"],
                "granularity": "ingredient",
            },
            "alias_enrichment_sources": [
                {
                    "name": "fixture-aliases",
                    "kind": "alias",
                    "source": "fixture",
                    "version": "fixture-1",
                    "source_path": str(aliases),
                    "checksum_sha256": _checksum(aliases),
                    "license_or_usage_basis": "test",
                }
            ],
        }
    )


class _ICDFixture(ICDAdapter):
    supported_versions = frozenset({"fixture-1"})

    def iter_concepts(self, source_path: Path, version: str):
        yield ConceptRecord(
            "ICD-10", "A00", "Cholera", True, "category_3", None, source_path, 6, version
        )
        yield ConceptRecord(
            "ICD-10", "A00", "Cholera", True, "category_3", None, source_path, 2, version
        )
        yield ConceptRecord(
            "ICD-10", "A00.1", "Other cholera", True, "subcategory_4", None, source_path, 3, version
        )
        yield ConceptRecord(
            "ICD-10", "A01", "Inactive", False, "category_3", None, source_path, 4, version
        )

    def iter_aliases(self, source_path: Path, version: str):
        yield AliasRecord("ICD-10", "A00", "Cholera", "preferred", source_path, 2, version)
        yield AliasRecord("ICD-10", "A00", " CHOLERA ", "synonym", source_path, 5, version)


class _RxNormFixture(RxNormAdapter):
    supported_versions = frozenset({"fixture-2"})

    def iter_concepts(self, source_path: Path, version: str):
        yield ConceptRecord(
            "RXNORM", "1", "Aspirin", True, "ingredient", "IN", source_path, 1, version
        )
        yield ConceptRecord(
            "RXNORM", "2", "Old aspirin", False, "ingredient", "IN", source_path, 2, version
        )
        yield ConceptRecord(
            "RXNORM", "3", "Aspirin tablet", True, "clinical_drug", "SCD", source_path, 3, version
        )
        yield ConceptRecord(
            "RXNORM", "9", "Acetylsalicylic acid", True, "ingredient", "IN", source_path, 5, version
        )

    def iter_aliases(self, source_path: Path, version: str):
        yield AliasRecord("RXNORM", "1", "Aspirin", "preferred", source_path, 1, version)
        yield AliasRecord("RXNORM", "1", "ASA", "synonym", source_path, 4, version)
        yield AliasRecord("RXNORM", "9", "ASA", "synonym", source_path, 5, version)


def test_preparation_filters_and_reports_deterministically(tmp_path: Path) -> None:
    tables = prepare_canonical_tables(_manifest(tmp_path), _ICDFixture(), _RxNormFixture())

    assert [(record.system, record.concept_id) for record in tables.concepts] == [
        ("ICD-10", "A00"),
        ("RXNORM", "1"),
        ("RXNORM", "9"),
    ]
    assert {record.alias for record in tables.aliases} == {"Cholera", " CHOLERA ", "Aspirin", "ASA"}
    assert (
        next(record for record in tables.aliases if record.alias == " CHOLERA ").normalized_alias
        == "cholera"
    )
    assert tables.duplicate_aliases[0].normalized_alias == "cholera"
    assert tables.conflicting_aliases[0].normalized_alias == "asa"
    assert tables.preparation_manifest["source_checksums"]["icd"] == _checksum(
        tmp_path / "icd.fixture"
    )

    paths = write_canonical_tables(tables, tmp_path / "prepared")
    assert paths.manifest_path.exists()
    assert sha256(paths.concepts_path.read_bytes()).hexdigest() == paths.checksums["concepts"]


def test_checksum_and_unsupported_version_fail_before_loading(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    (tmp_path / "icd.fixture").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        prepare_canonical_tables(manifest, _ICDFixture(), _RxNormFixture())

    manifest = _manifest(tmp_path)
    bad_manifest = replace(manifest, icd=replace(manifest.icd, version="unsupported"))
    with pytest.raises(ValueError, match="unsupported ICD version"):
        prepare_canonical_tables(bad_manifest, _ICDFixture(), _RxNormFixture())


def test_frozen_manifest_preparation_is_byte_stable(tmp_path: Path) -> None:
    manifest_path = Path("specs/terminology_manifest.yaml")
    manifest = load_terminology_manifest(manifest_path)
    icd = ICD10ZipAdapter(frozenset({manifest.icd.version}))
    rxnorm = RxNormZipAdapter(
        frozenset({manifest.rxnorm.release}), frozenset(manifest.rxnorm.allowed_ttys)
    )
    tables = prepare_from_manifest(manifest_path, icd, rxnorm)
    assert any(
        alias.alias == "Paracetamol" and alias.concept_id == "161" for alias in tables.aliases
    )
    first = write_canonical_tables(tables, tmp_path / "first")
    second = write_canonical_tables(tables, tmp_path / "second")
    assert first.checksums == second.checksums
