"""Typed, local-only validation for terminology and artifact manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml


_SUPPORTED_ICD_VARIANTS = frozenset({"ICD-10", "ICD-10-CM", "ICD-11"})
_SHA256_LENGTH = 64
_MAX_MODEL_PARAMETERS = 9_000_000_000
_SECRET_KEY_PARTS = ("secret", "password", "token", "api_key", "apikey", "credential")


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return MappingProxyType(dict(value))


def _required_str(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip() or value == "TBD":
        raise ValueError(f"{field_name} must be a non-empty, finalized string")
    return value


def _required_date(data: Mapping[str, Any], field_name: str) -> date:
    value = data.get(field_name)
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value or value == "TBD":
        raise ValueError(f"{field_name} must be an ISO-8601 date")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO-8601 date") from error


def _required_checksum(data: Mapping[str, Any], field_name: str = "checksum_sha256") -> str:
    checksum = _required_str(data, field_name).lower()
    _validate_checksum_text(checksum, field_name)
    return checksum


def _validate_checksum_text(checksum: str, field_name: str = "checksum_sha256") -> None:
    if len(checksum) != _SHA256_LENGTH or any(char not in "0123456789abcdef" for char in checksum):
        raise ValueError(f"{field_name} must be a SHA-256 hexadecimal digest")


def _validate_nonempty_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")


def _required_int(data: Mapping[str, Any], field_name: str) -> int:
    value = data.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _required_string_tuple(data: Mapping[str, Any], field_name: str) -> tuple[str, ...]:
    value = data.get(field_name)
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field_name} must be a non-empty list of strings")
    return tuple(value)


def _path_from(data: Mapping[str, Any], field_name: str, base_path: Path | None) -> Path:
    path = Path(_required_str(data, field_name))
    return path if path.is_absolute() or base_path is None else base_path / path


def _validate_no_secrets(value: object, path: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            if any(part in key.casefold() for part in _SECRET_KEY_PARTS):
                raise ValueError(f"secret-like field is not permitted: {path}.{key}")
            _validate_no_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_no_secrets(item, f"{path}[{index}]")


def _verify_checksum(path: Path, expected_checksum: str) -> None:
    if not path.is_file():
        raise ValueError(f"manifest path is not a file: {path}")
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_checksum:
        raise ValueError(f"checksum mismatch for {path}")


@dataclass(frozen=True, slots=True)
class ICDProvenance:
    source: str
    variant: str
    version: str
    release_date: date
    source_path: Path
    checksum_sha256: str
    license_or_usage_basis: str
    include_inactive: bool
    allowed_code_levels: tuple[str, ...]

    def validate(self, verify_path: bool = False) -> None:
        _validate_nonempty_text(self.source, "source")
        _validate_nonempty_text(self.version, "version")
        _validate_nonempty_text(self.license_or_usage_basis, "license_or_usage_basis")
        _validate_checksum_text(self.checksum_sha256)
        if self.variant not in _SUPPORTED_ICD_VARIANTS:
            raise ValueError(f"unsupported ICD variant: {self.variant}")
        if not isinstance(self.include_inactive, bool):
            raise TypeError("include_inactive must be bool")
        if verify_path:
            _verify_checksum(self.source_path, self.checksum_sha256)


@dataclass(frozen=True, slots=True)
class RxNormProvenance:
    source: str
    release: str
    release_date: date
    source_path: Path
    checksum_sha256: str
    license_or_usage_basis: str
    include_obsolete: bool
    allowed_ttys: tuple[str, ...]
    granularity: str

    def validate(self, verify_path: bool = False) -> None:
        _validate_nonempty_text(self.source, "source")
        _validate_nonempty_text(self.release, "release")
        _validate_nonempty_text(self.license_or_usage_basis, "license_or_usage_basis")
        _validate_checksum_text(self.checksum_sha256)
        if not isinstance(self.include_obsolete, bool):
            raise TypeError("include_obsolete must be bool")
        if not self.granularity:
            raise ValueError("granularity must not be empty")
        if verify_path:
            _verify_checksum(self.source_path, self.checksum_sha256)


@dataclass(frozen=True, slots=True)
class AliasEnrichmentSource:
    name: str
    kind: str
    source: str
    version: str
    source_path: Path
    checksum_sha256: str
    license_or_usage_basis: str

    def validate(self, verify_path: bool = False) -> None:
        _validate_nonempty_text(self.name, "name")
        _validate_nonempty_text(self.source, "source")
        _validate_nonempty_text(self.version, "version")
        _validate_nonempty_text(self.license_or_usage_basis, "license_or_usage_basis")
        _validate_checksum_text(self.checksum_sha256)
        if self.kind not in {"alias", "enrichment"}:
            raise ValueError("kind must be alias or enrichment")
        if verify_path:
            _verify_checksum(self.source_path, self.checksum_sha256)


@dataclass(frozen=True, slots=True)
class TerminologyManifest:
    schema_version: int
    icd: ICDProvenance
    rxnorm: RxNormProvenance
    alias_enrichment_sources: tuple[AliasEnrichmentSource, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], base_path: Path | None = None) -> "TerminologyManifest":
        _validate_no_secrets(data)
        root = _mapping(data, "manifest")
        if _required_int(root, "schema_version") != 1:
            raise ValueError("unsupported terminology manifest schema_version")
        icd_data = _mapping(root.get("icd"), "icd")
        rxnorm_data = _mapping(root.get("rxnorm"), "rxnorm")
        icd = ICDProvenance(
            _required_str(icd_data, "source"), _required_str(icd_data, "variant"),
            _required_str(icd_data, "version"), _required_date(icd_data, "release_date"),
            _path_from(icd_data, "source_path", base_path), _required_checksum(icd_data),
            _required_str(icd_data, "license_or_usage_basis"),
            icd_data.get("include_inactive"), _required_string_tuple(icd_data, "allowed_code_levels"),
        )
        rxnorm = RxNormProvenance(
            _required_str(rxnorm_data, "source"), _required_str(rxnorm_data, "release"),
            _required_date(rxnorm_data, "release_date"), _path_from(rxnorm_data, "source_path", base_path),
            _required_checksum(rxnorm_data), _required_str(rxnorm_data, "license_or_usage_basis"),
            rxnorm_data.get("include_obsolete"), _required_string_tuple(rxnorm_data, "allowed_ttys"),
            _required_str(rxnorm_data, "granularity"),
        )
        sources_data = root.get("alias_enrichment_sources", [])
        if not isinstance(sources_data, list) or not sources_data:
            raise ValueError("alias_enrichment_sources must be a non-empty list")
        sources = tuple(
            AliasEnrichmentSource(
                _required_str(item_data := _mapping(item, "alias_enrichment_sources item"), "name"),
                _required_str(item_data, "kind"), _required_str(item_data, "source"),
                _required_str(item_data, "version"), _path_from(item_data, "source_path", base_path),
                _required_checksum(item_data), _required_str(item_data, "license_or_usage_basis"),
            )
            for item in sources_data
        )
        manifest = cls(1, icd, rxnorm, sources)
        manifest.validate()
        return manifest

    def validate(self, verify_paths: bool = False) -> None:
        self.icd.validate(verify_paths)
        self.rxnorm.validate(verify_paths)
        for source in self.alias_enrichment_sources:
            source.validate(verify_paths)


@dataclass(frozen=True, slots=True)
class ModelArtifact:
    model_name: str
    parameter_count: int | None
    path: Path
    checksum_sha256: str
    training_config: Mapping[str, Any] = field(default_factory=dict)
    dataset_versions: Mapping[str, str] = field(default_factory=dict)
    code_commit: str = ""
    seed: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "training_config", _mapping(self.training_config, "training_config"))
        object.__setattr__(self, "dataset_versions", _mapping(self.dataset_versions, "dataset_versions"))

    def validate(self, verify_path: bool = False) -> None:
        _validate_nonempty_text(self.model_name, "model_name")
        _validate_nonempty_text(self.code_commit, "code_commit")
        _validate_checksum_text(self.checksum_sha256)
        if self.parameter_count is not None and self.parameter_count > _MAX_MODEL_PARAMETERS:
            raise ValueError("declared model parameter_count must not exceed 9B")
        if self.parameter_count is not None and self.parameter_count < 1:
            raise ValueError("parameter_count must be positive when declared")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if verify_path:
            _verify_checksum(self.path, self.checksum_sha256)


@dataclass(frozen=True, slots=True)
class SyntheticDataProvenance:
    generator_name: str
    generator_version: str
    path: Path
    checksum_sha256: str
    generation_config: Mapping[str, Any]
    dataset_versions: Mapping[str, str]
    code_commit: str
    seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "generation_config", _mapping(self.generation_config, "generation_config"))
        object.__setattr__(self, "dataset_versions", _mapping(self.dataset_versions, "dataset_versions"))

    def validate(self, verify_path: bool = False) -> None:
        _validate_nonempty_text(self.generator_name, "generator_name")
        _validate_nonempty_text(self.generator_version, "generator_version")
        _validate_nonempty_text(self.code_commit, "code_commit")
        _validate_checksum_text(self.checksum_sha256)
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if verify_path:
            _verify_checksum(self.path, self.checksum_sha256)


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    schema_version: int
    model_artifacts: tuple[ModelArtifact, ...]
    synthetic_data: SyntheticDataProvenance

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], base_path: Path | None = None) -> "ArtifactManifest":
        _validate_no_secrets(data)
        root = _mapping(data, "manifest")
        if _required_int(root, "schema_version") != 1:
            raise ValueError("unsupported artifact manifest schema_version")
        models_data = root.get("model_artifacts")
        if not isinstance(models_data, list) or not models_data:
            raise ValueError("model_artifacts must be a non-empty list")
        models = tuple(_model_from_mapping(_mapping(item, "model_artifact"), base_path) for item in models_data)
        synthetic = _synthetic_from_mapping(_mapping(root.get("synthetic_data"), "synthetic_data"), base_path)
        manifest = cls(1, models, synthetic)
        manifest.validate()
        return manifest

    def validate(self, verify_paths: bool = False) -> None:
        for artifact in self.model_artifacts:
            artifact.validate(verify_paths)
        self.synthetic_data.validate(verify_paths)


def _model_from_mapping(data: Mapping[str, Any], base_path: Path | None) -> ModelArtifact:
    parameter_count = data.get("parameter_count")
    if parameter_count is not None and (isinstance(parameter_count, bool) or not isinstance(parameter_count, int)):
        raise TypeError("parameter_count must be an integer or null")
    return ModelArtifact(
        _required_str(data, "model_name"), parameter_count, _path_from(data, "path", base_path),
        _required_checksum(data), _mapping(data.get("training_config"), "training_config"),
        _mapping(data.get("dataset_versions"), "dataset_versions"), _required_str(data, "code_commit"),
        _required_int(data, "seed"),
    )


def _synthetic_from_mapping(data: Mapping[str, Any], base_path: Path | None) -> SyntheticDataProvenance:
    return SyntheticDataProvenance(
        _required_str(data, "generator_name"), _required_str(data, "generator_version"),
        _path_from(data, "path", base_path), _required_checksum(data),
        _mapping(data.get("generation_config"), "generation_config"),
        _mapping(data.get("dataset_versions"), "dataset_versions"), _required_str(data, "code_commit"),
        _required_int(data, "seed"),
    )


def _load_yaml(path: str | Path) -> tuple[Mapping[str, Any], Path]:
    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return _mapping(loaded, "manifest"), manifest_path.parent


def load_terminology_manifest(path: str | Path, verify_paths: bool = False) -> TerminologyManifest:
    data, base_path = _load_yaml(path)
    manifest = TerminologyManifest.from_mapping(data, base_path)
    manifest.validate(verify_paths)
    return manifest


def load_artifact_manifest(path: str | Path, verify_paths: bool = False) -> ArtifactManifest:
    data, base_path = _load_yaml(path)
    manifest = ArtifactManifest.from_mapping(data, base_path)
    manifest.validate(verify_paths)
    return manifest
