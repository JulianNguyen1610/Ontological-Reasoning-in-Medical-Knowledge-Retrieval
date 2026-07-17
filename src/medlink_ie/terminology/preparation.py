"""Prepare deterministic canonical terminology tables from frozen local inputs.

Adapters intentionally receive only local paths.  They are responsible for the
source-specific archive format, while this module owns provenance validation,
filtering, reporting, and stable artifact serialization.
"""

from __future__ import annotations

import json
import unicodedata
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zipfile import ZipFile

import yaml

from medlink_ie.provenance.manifest import (
    ICDProvenance,
    RxNormProvenance,
    TerminologyManifest,
    load_terminology_manifest,
)


def normalize_alias_for_retrieval(value: str) -> str:
    """Create a retrieval key without changing the source display alias."""
    if not isinstance(value, str):
        raise TypeError("alias must be a string")
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


@dataclass(frozen=True, slots=True)
class ConceptRecord:
    system: str
    concept_id: str
    preferred_term: str
    active: bool
    granularity: str
    tty: str | None
    source_path: Path
    source_row: int
    source_version: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required_text(self.system, "system")
        _required_text(self.concept_id, "concept_id")
        _required_text(self.preferred_term, "preferred_term")
        _required_text(self.granularity, "granularity")
        _required_text(self.source_version, "source_version")
        if not isinstance(self.active, bool):
            raise TypeError("active must be bool")
        if self.tty is not None:
            _required_text(self.tty, "tty")
        _source_trace(self.source_path, self.source_row)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class AliasRecord:
    system: str
    concept_id: str
    alias: str
    alias_type: str
    source_path: Path
    source_row: int
    source_version: str
    normalized_alias: str = field(init=False)

    def __post_init__(self) -> None:
        _required_text(self.system, "system")
        _required_text(self.concept_id, "concept_id")
        _required_text(self.alias, "alias")
        _required_text(self.alias_type, "alias_type")
        _required_text(self.source_version, "source_version")
        _source_trace(self.source_path, self.source_row)
        normalized = normalize_alias_for_retrieval(self.alias)
        if not normalized:
            raise ValueError("alias must contain non-whitespace text")
        object.__setattr__(self, "normalized_alias", normalized)


class ICDAdapter(ABC):
    """Local ICD reader contract; implementations must not access the network."""

    supported_versions: frozenset[str]

    @abstractmethod
    def iter_concepts(self, source_path: Path, version: str) -> Iterable[ConceptRecord]:
        """Yield source-traceable ICD concepts from one verified local source."""

    @abstractmethod
    def iter_aliases(self, source_path: Path, version: str) -> Iterable[AliasRecord]:
        """Yield source-traceable ICD aliases from one verified local source."""


class RxNormAdapter(ABC):
    """Local RxNorm reader contract; implementations must not access the network."""

    supported_versions: frozenset[str]

    @abstractmethod
    def iter_concepts(self, source_path: Path, version: str) -> Iterable[ConceptRecord]:
        """Yield source-traceable RxNorm concepts from one verified local source."""

    @abstractmethod
    def iter_aliases(self, source_path: Path, version: str) -> Iterable[AliasRecord]:
        """Yield source-traceable RxNorm aliases from one verified local source."""


@dataclass(frozen=True, slots=True)
class ICD10ZipAdapter(ICDAdapter):
    """Reader for the frozen WHO ICD-10 metadata ZIP declared by the manifest."""

    supported_versions: frozenset[str]

    def iter_concepts(self, source_path: Path, version: str) -> Iterable[ConceptRecord]:
        selected: dict[str, tuple[int, list[str]]] = {}
        for row, fields in _zip_rows(source_path, "icd102019syst_codes.txt", ";"):
            if len(fields) < 9 or fields[0] not in {"3", "4"}:
                continue
            prior = selected.get(fields[4])
            if prior is None or (fields[0], row) < (prior[1][0], prior[0]):
                selected[fields[4]] = (row, fields)
        for code, (row, fields) in sorted(selected.items()):
            yield ConceptRecord(
                "ICD-10",
                code,
                fields[8],
                True,
                "category_3" if fields[0] == "3" else "subcategory_4",
                None,
                source_path,
                row,
                version,
            )

    def iter_aliases(self, source_path: Path, version: str) -> Iterable[AliasRecord]:
        for row, fields in _zip_rows(source_path, "icd102019syst_codes.txt", ";"):
            if len(fields) < 11 or fields[0] not in {"3", "4"}:
                continue
            for alias_type, alias in (
                ("preferred", fields[8]),
                ("inclusion", fields[9]),
                ("inclusion", fields[10]),
            ):
                if alias:
                    yield AliasRecord(
                        "ICD-10", fields[4], alias, alias_type, source_path, row, version
                    )


@dataclass(frozen=True, slots=True)
class RxNormZipAdapter(RxNormAdapter):
    """Reader for local RXNCONSO.RRF; no terminology data is fetched at runtime."""

    supported_versions: frozenset[str]
    allowed_ttys: frozenset[str]

    def iter_concepts(self, source_path: Path, version: str) -> Iterable[ConceptRecord]:
        selected: dict[str, tuple[int, list[str]]] = {}
        for row, fields in _zip_rows(source_path, "rrf/RXNCONSO.RRF", "|"):
            if not _rxnorm_row_allowed(fields, self.allowed_ttys):
                continue
            rxcui = fields[0]
            candidate = (row, fields)
            prior = selected.get(rxcui)
            if prior is None or (fields[12], fields[14], row) < (
                prior[1][12],
                prior[1][14],
                prior[0],
            ):
                selected[rxcui] = candidate
        for rxcui, (row, fields) in sorted(selected.items()):
            yield ConceptRecord(
                "RXNORM",
                rxcui,
                fields[14],
                fields[16] != "O",
                "rxnorm",
                fields[12],
                source_path,
                row,
                version,
            )

    def iter_aliases(self, source_path: Path, version: str) -> Iterable[AliasRecord]:
        for row, fields in _zip_rows(source_path, "rrf/RXNCONSO.RRF", "|"):
            if _rxnorm_row_allowed(fields, self.allowed_ttys):
                yield AliasRecord(
                    "RXNORM", fields[0], fields[14], fields[12], source_path, row, version
                )


@dataclass(frozen=True, slots=True)
class AliasReport:
    normalized_alias: str
    targets: tuple[tuple[str, str], ...]
    source_rows: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class CanonicalTables:
    concepts: tuple[ConceptRecord, ...]
    aliases: tuple[AliasRecord, ...]
    duplicate_aliases: tuple[AliasReport, ...]
    conflicting_aliases: tuple[AliasReport, ...]
    preparation_manifest: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "preparation_manifest", MappingProxyType(dict(self.preparation_manifest))
        )


@dataclass(frozen=True, slots=True)
class PreparationPaths:
    concepts_path: Path
    aliases_path: Path
    duplicate_report_path: Path
    conflict_report_path: Path
    manifest_path: Path
    checksums: Mapping[str, str]


def prepare_canonical_tables(
    manifest: TerminologyManifest,
    icd_adapter: ICDAdapter,
    rxnorm_adapter: RxNormAdapter,
) -> CanonicalTables:
    """Verify local inputs and construct filtered, deterministic canonical tables."""
    manifest.validate(verify_paths=True)
    _require_supported(icd_adapter.supported_versions, manifest.icd.version, "ICD")
    _require_supported(rxnorm_adapter.supported_versions, manifest.rxnorm.release, "RxNorm")

    icd_concepts = tuple(icd_adapter.iter_concepts(manifest.icd.source_path, manifest.icd.version))
    rxnorm_concepts = tuple(
        rxnorm_adapter.iter_concepts(manifest.rxnorm.source_path, manifest.rxnorm.release)
    )
    _validate_system(icd_concepts, "ICD")
    _validate_system(rxnorm_concepts, "RXNORM")
    concepts = _deduplicate_concepts(
        [
            *(_filter_icd(record, manifest.icd) for record in icd_concepts),
            *(_filter_rxnorm(record, manifest.rxnorm) for record in rxnorm_concepts),
        ]
    )
    valid_targets = {(record.system, record.concept_id) for record in concepts}
    source_aliases = [
        *icd_adapter.iter_aliases(manifest.icd.source_path, manifest.icd.version),
        *rxnorm_adapter.iter_aliases(manifest.rxnorm.source_path, manifest.rxnorm.release),
        *_load_enrichment_aliases(manifest),
    ]
    filtered_source_aliases = tuple(
        sorted(
            (
                record
                for record in source_aliases
                if (record.system, record.concept_id) in valid_targets
            ),
            key=_alias_key,
        )
    )
    duplicate_aliases, conflicting_aliases = _alias_reports(filtered_source_aliases)
    filtered_aliases = _deduplicate_aliases(filtered_source_aliases)
    source_checksums = {
        "icd": manifest.icd.checksum_sha256,
        "rxnorm": manifest.rxnorm.checksum_sha256,
        **{source.name: source.checksum_sha256 for source in manifest.alias_enrichment_sources},
    }
    preparation_manifest = {
        "schema_version": 1,
        "icd_version": manifest.icd.version,
        "rxnorm_release": manifest.rxnorm.release,
        "source_checksums": dict(sorted(source_checksums.items())),
        "concept_count": len(concepts),
        "alias_count": len(filtered_aliases),
        "duplicate_alias_count": len(duplicate_aliases),
        "conflicting_alias_count": len(conflicting_aliases),
    }
    return CanonicalTables(
        tuple(sorted(concepts, key=_concept_key)),
        filtered_aliases,
        duplicate_aliases,
        conflicting_aliases,
        preparation_manifest,
    )


def prepare_from_manifest(
    manifest_path: str | Path,
    icd_adapter: ICDAdapter,
    rxnorm_adapter: RxNormAdapter,
) -> CanonicalTables:
    """Load a frozen terminology manifest and prepare its local canonical tables."""
    return prepare_canonical_tables(
        load_terminology_manifest(manifest_path), icd_adapter, rxnorm_adapter
    )


def write_canonical_tables(
    tables: CanonicalTables, output_directory: str | Path
) -> PreparationPaths:
    """Write stable JSONL tables and a checksummed preparation manifest locally."""
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    concepts_path = directory / "canonical_concepts.jsonl"
    aliases_path = directory / "canonical_aliases.jsonl"
    duplicate_path = directory / "duplicate_aliases.json"
    conflict_path = directory / "conflicting_aliases.json"
    _write_jsonl(concepts_path, (_concept_dict(record) for record in tables.concepts))
    _write_jsonl(aliases_path, (_alias_dict(record) for record in tables.aliases))
    _write_json(duplicate_path, [_report_dict(report) for report in tables.duplicate_aliases])
    _write_json(conflict_path, [_report_dict(report) for report in tables.conflicting_aliases])
    checksums = {
        "aliases": _checksum(aliases_path),
        "concepts": _checksum(concepts_path),
        "conflicting_aliases": _checksum(conflict_path),
        "duplicate_aliases": _checksum(duplicate_path),
    }
    body = {**tables.preparation_manifest, "artifact_checksums": dict(sorted(checksums.items()))}
    manifest_payload = {**body, "manifest_checksum": _canonical_checksum(body)}
    manifest_path = directory / "preparation_manifest.json"
    _write_json(manifest_path, manifest_payload)
    return PreparationPaths(
        concepts_path,
        aliases_path,
        duplicate_path,
        conflict_path,
        manifest_path,
        MappingProxyType(checksums),
    )


def _filter_icd(record: ConceptRecord, provenance: ICDProvenance) -> ConceptRecord | None:
    if not record.active and not provenance.include_inactive:
        return None
    return record if record.granularity in provenance.allowed_code_levels else None


def _filter_rxnorm(record: ConceptRecord, provenance: RxNormProvenance) -> ConceptRecord | None:
    if not record.active and not provenance.include_obsolete:
        return None
    return record if record.tty in provenance.allowed_ttys else None


def _deduplicate_concepts(records: Iterable[ConceptRecord | None]) -> tuple[ConceptRecord, ...]:
    unique: dict[tuple[str, str], ConceptRecord] = {}
    ordered = sorted((record for record in records if record is not None), key=_concept_source_key)
    for record in ordered:
        key = (record.system, record.concept_id)
        prior = unique.get(key)
        if prior is None:
            unique[key] = record
        elif _concept_content(prior) != _concept_content(record):
            raise ValueError(f"conflicting concept rows for {record.system}:{record.concept_id}")
    return tuple(unique.values())


def _deduplicate_aliases(records: tuple[AliasRecord, ...]) -> tuple[AliasRecord, ...]:
    unique: dict[tuple[str, str, str, str, str], AliasRecord] = {}
    for record in records:
        unique.setdefault(
            (
                record.system,
                record.concept_id,
                record.alias,
                record.alias_type,
                record.source_version,
            ),
            record,
        )
    return tuple(sorted(unique.values(), key=_alias_key))


def _alias_reports(
    aliases: tuple[AliasRecord, ...],
) -> tuple[tuple[AliasReport, ...], tuple[AliasReport, ...]]:
    grouped: dict[str, list[AliasRecord]] = defaultdict(list)
    for alias in aliases:
        grouped[alias.normalized_alias].append(alias)
    duplicate: list[AliasReport] = []
    conflict: list[AliasReport] = []
    for normalized, records in grouped.items():
        targets = tuple(sorted({(record.system, record.concept_id) for record in records}))
        report = AliasReport(
            normalized, targets, tuple(sorted((str(r.source_path), r.source_row) for r in records))
        )
        if len(records) > 1 and len(targets) == 1:
            duplicate.append(report)
        if len(targets) > 1:
            conflict.append(report)
    return tuple(sorted(duplicate, key=lambda item: item.normalized_alias)), tuple(
        sorted(conflict, key=lambda item: item.normalized_alias)
    )


def _load_enrichment_aliases(manifest: TerminologyManifest) -> tuple[AliasRecord, ...]:
    records: list[AliasRecord] = []
    for source in manifest.alias_enrichment_sources:
        if source.source_path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        loaded = yaml.safe_load(source.source_path.read_text(encoding="utf-8"))
        if loaded is None:
            continue
        rows = loaded.get("aliases", []) if isinstance(loaded, dict) else loaded
        if not isinstance(rows, list):
            raise ValueError(
                f"alias source {source.name} must be a list or contain an aliases list"
            )
        for offset, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise TypeError(f"alias source {source.name} row {offset} must be a mapping")
            records.append(
                AliasRecord(
                    str(row["system"]),
                    str(row["concept_id"]),
                    str(row["alias"]),
                    str(row.get("alias_type", source.kind)),
                    source.source_path,
                    offset,
                    source.version,
                )
            )
    return tuple(records)


def _zip_rows(source_path: Path, member: str, delimiter: str) -> Iterable[tuple[int, list[str]]]:
    with ZipFile(source_path) as archive, archive.open(member) as handle:
        for row, line in enumerate(handle, start=1):
            yield row, line.decode("utf-8").rstrip("\r\n").split(delimiter)


def _rxnorm_row_allowed(fields: list[str], allowed_ttys: frozenset[str]) -> bool:
    return (
        len(fields) > 16
        and fields[1] == "ENG"
        and fields[11] == "RXNORM"
        and fields[12] in allowed_ttys
    )


def _validate_system(records: Iterable[ConceptRecord], required_fragment: str) -> None:
    if any(required_fragment not in record.system.upper() for record in records):
        raise ValueError(f"{required_fragment} adapter yielded a record with another system")


def _require_supported(supported: frozenset[str], version: str, label: str) -> None:
    if version not in supported:
        raise ValueError(f"unsupported {label} version: {version}")


def _required_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")


def _source_trace(path: Path, row: int) -> None:
    if not isinstance(path, Path):
        raise TypeError("source_path must be a Path")
    if not isinstance(row, int) or isinstance(row, bool) or row < 1:
        raise ValueError("source_row must be a positive integer")


def _concept_key(record: ConceptRecord) -> tuple[str, str, str]:
    return record.system, record.concept_id, record.preferred_term


def _concept_source_key(record: ConceptRecord) -> tuple[str, str, str, int]:
    return record.system, record.concept_id, str(record.source_path), record.source_row


def _concept_content(record: ConceptRecord) -> tuple[Any, ...]:
    return (
        record.system,
        record.concept_id,
        record.preferred_term,
        record.active,
        record.granularity,
        record.tty,
        tuple(sorted(record.metadata.items())),
        record.source_version,
    )


def _alias_key(record: AliasRecord) -> tuple[str, str, str, str, int]:
    return (
        record.system,
        record.concept_id,
        record.normalized_alias,
        record.alias,
        record.source_row,
    )


def _concept_dict(record: ConceptRecord) -> dict[str, Any]:
    return {
        "active": record.active,
        "concept_id": record.concept_id,
        "granularity": record.granularity,
        "metadata": dict(sorted(record.metadata.items())),
        "preferred_term": record.preferred_term,
        "source_path": str(record.source_path),
        "source_row": record.source_row,
        "source_version": record.source_version,
        "system": record.system,
        "tty": record.tty,
    }


def _alias_dict(record: AliasRecord) -> dict[str, Any]:
    return {
        "alias": record.alias,
        "alias_type": record.alias_type,
        "concept_id": record.concept_id,
        "normalized_alias": record.normalized_alias,
        "source_path": str(record.source_path),
        "source_row": record.source_row,
        "source_version": record.source_version,
        "system": record.system,
    }


def _report_dict(report: AliasReport) -> dict[str, Any]:
    return {
        "normalized_alias": report.normalized_alias,
        "source_rows": [list(row) for row in report.source_rows],
        "targets": [list(target) for target in report.targets],
    }


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text("".join(_canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(_canonical_json(value) + "\n", encoding="utf-8")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _canonical_checksum(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
