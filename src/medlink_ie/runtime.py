"""Strict, deterministic runtime configuration for MedLink-IE commands."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigError(ValueError):
    """Raised when a runtime configuration is unsafe, invalid, or unsupported."""


_SECRET_PARTS = ("secret", "password", "token", "api_key", "apikey", "credential")
_ROOT_KEYS = frozenset(
    {
        "profile",
        "seed",
        "offline",
        "feature_flags",
        "paths",
        "terminology",
        "batch",
        "artifacts",
    }
)
_PATH_KEYS = frozenset(
    {
        "run_dir",
        "input",
        "output_dir",
        "trace_dir",
        "package_path",
        "gold",
        "predictions",
    }
)
_TERMINOLOGY_KEYS = frozenset({"manifest", "output_dir"})
_BATCH_KEYS = frozenset({"batch_size", "resume_policy", "timeout_seconds", "capture_memory"})
_ARTIFACT_KEYS = frozenset({"inventory"})


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    """Explicitly enabled execution features."""

    llm: bool = False
    dense: bool = False
    reranker: bool = False
    ontology: bool = False
    fuzzy_grounding: bool = False


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Resolved paths used by the command layer."""

    run_dir: Path
    input: Path | None = None
    output_dir: Path | None = None
    trace_dir: Path | None = None
    package_path: Path | None = None
    gold: Path | None = None
    predictions: Path | None = None


@dataclass(frozen=True, slots=True)
class TerminologySettings:
    """Optional frozen-local terminology preparation inputs."""

    manifest: Path | None = None
    output_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class BatchSettings:
    """CLI-exposed batch controls consumed by the local pipeline."""

    batch_size: int = 16
    resume_policy: str = "never"
    timeout_seconds: float | None = None
    capture_memory: bool = True


@dataclass(frozen=True, slots=True)
class ArtifactSettings:
    """Optional inventory defining the complete offline artifact set."""

    inventory: Path | None = None


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Fully validated command configuration with paths anchored at its file."""

    profile: str
    seed: int
    offline: bool
    feature_flags: FeatureFlags
    paths: RuntimePaths
    terminology: TerminologySettings = field(default_factory=TerminologySettings)
    batch: BatchSettings = field(default_factory=BatchSettings)
    artifacts: ArtifactSettings = field(default_factory=ArtifactSettings)
    config_path: Path = Path(".")

    def resolved_dict(self) -> dict[str, Any]:
        """Return a stable JSON-safe snapshot without configuration secrets."""
        data = asdict(self)
        data["config_path"] = str(self.config_path)
        _stringify_paths(data)
        return data


def load_config(path: str | Path) -> RuntimeConfig:
    """Load one YAML config, reject unknown keys, and resolve all relative paths."""
    config_path = Path(path).resolve()
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigError("configuration file does not exist") from error
    except yaml.YAMLError as error:
        raise ConfigError("configuration file is not valid YAML") from error
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, Mapping) or any(not isinstance(key, str) for key in loaded):
        raise ConfigError("configuration root must be a mapping with string keys")
    _reject_secrets(loaded)
    _reject_unknown(loaded, _ROOT_KEYS, "configuration")
    base = config_path.parent
    profile = _profile(loaded.get("profile", "mvp_deterministic"))
    offline = _bool(loaded.get("offline", True), "offline")
    if not offline:
        raise ConfigError("offline must be true; network-backed execution is prohibited")
    seed = _nonnegative_int(loaded.get("seed", 42), "seed")
    flags = _feature_flags(loaded.get("feature_flags", {}))
    paths = _paths(loaded.get("paths", {}), base)
    terminology = _terminology(loaded.get("terminology", {}), base)
    batch = _batch(loaded.get("batch", {}))
    artifacts = _artifacts(loaded.get("artifacts", {}), base)
    config = RuntimeConfig(
        profile, seed, offline, flags, paths, terminology, batch, artifacts, config_path
    )
    _validate_combinations(config)
    return config


def save_resolved_config(config: RuntimeConfig) -> Path:
    """Persist the validated snapshot in the configured run artifact directory."""
    config.paths.run_dir.mkdir(parents=True, exist_ok=True)
    target = config.paths.run_dir / "resolved_config.json"
    target.write_text(
        json.dumps(config.resolved_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def _profile(value: object) -> str:
    aliases = {
        "mvp": "mvp_deterministic",
        "mvp_deterministic": "mvp_deterministic",
        "competition": "competition_full",
        "competition_full": "competition_full",
        "fast": "fast_fallback",
        "fast_fallback": "fast_fallback",
    }
    if not isinstance(value, str) or value not in aliases:
        allowed = ", ".join(sorted(aliases))
        raise ConfigError(f"profile must be one of: {allowed}")
    return aliases[value]


def _feature_flags(value: object) -> FeatureFlags:
    if not isinstance(value, Mapping):
        raise ConfigError("feature_flags must be a mapping")
    expected = frozenset(FeatureFlags.__dataclass_fields__)
    _reject_unknown(value, expected, "feature_flags")
    flags = {name: _bool(value.get(name, False), f"feature_flags.{name}") for name in expected}
    return FeatureFlags(**flags)


def _paths(value: object, base: Path) -> RuntimePaths:
    if not isinstance(value, Mapping):
        raise ConfigError("paths must be a mapping")
    _reject_unknown(value, _PATH_KEYS, "paths")
    run_dir = _path(value.get("run_dir", "artifacts/run"), "paths.run_dir", base)
    values = {
        name: _optional_path(value.get(name), f"paths.{name}", base)
        for name in _PATH_KEYS - {"run_dir"}
    }
    return RuntimePaths(run_dir=run_dir, **values)


def _terminology(value: object, base: Path) -> TerminologySettings:
    if not isinstance(value, Mapping):
        raise ConfigError("terminology must be a mapping")
    _reject_unknown(value, _TERMINOLOGY_KEYS, "terminology")
    return TerminologySettings(
        manifest=_optional_path(value.get("manifest"), "terminology.manifest", base),
        output_dir=_optional_path(value.get("output_dir"), "terminology.output_dir", base),
    )


def _batch(value: object) -> BatchSettings:
    if not isinstance(value, Mapping):
        raise ConfigError("batch must be a mapping")
    _reject_unknown(value, _BATCH_KEYS, "batch")
    batch_size = _nonnegative_int(value.get("batch_size", 16), "batch.batch_size")
    if batch_size == 0:
        raise ConfigError("batch.batch_size must be positive")
    resume_policy = value.get("resume_policy", "never")
    if resume_policy not in {"never", "reuse_valid", "fail_if_exists"}:
        raise ConfigError("batch.resume_policy must be never, reuse_valid, or fail_if_exists")
    timeout = value.get("timeout_seconds")
    if timeout is not None and (
        isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0
    ):
        raise ConfigError("batch.timeout_seconds must be positive when configured")
    return BatchSettings(
        batch_size=batch_size,
        resume_policy=resume_policy,
        timeout_seconds=None if timeout is None else float(timeout),
        capture_memory=_bool(value.get("capture_memory", True), "batch.capture_memory"),
    )


def _artifacts(value: object, base: Path) -> ArtifactSettings:
    if not isinstance(value, Mapping):
        raise ConfigError("artifacts must be a mapping")
    _reject_unknown(value, _ARTIFACT_KEYS, "artifacts")
    return ArtifactSettings(_optional_path(value.get("inventory"), "artifacts.inventory", base))


def _validate_combinations(config: RuntimeConfig) -> None:
    flags = config.feature_flags
    if flags.reranker and not flags.dense:
        raise ConfigError("feature_flags.reranker requires feature_flags.dense")
    if flags.ontology and not flags.reranker:
        raise ConfigError("feature_flags.ontology requires feature_flags.reranker")
    mvp_incompatible = flags.llm or flags.dense or flags.reranker or flags.ontology
    if config.profile == "mvp_deterministic" and mvp_incompatible:
        raise ConfigError("mvp_deterministic supports only rule-based and fuzzy grounding features")
    if config.profile == "fast_fallback" and any(asdict(flags).values()):
        raise ConfigError("fast_fallback does not permit optional feature flags")
    if flags.llm and config.profile != "competition_full":
        raise ConfigError("feature_flags.llm requires profile competition_full")


def _reject_secrets(value: object, location: str = "configuration") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConfigError(f"{location} keys must be strings")
            if any(part in key.casefold() for part in _SECRET_PARTS):
                raise ConfigError(
                    f"secret-like configuration field is not permitted: {location}.{key}"
                )
            _reject_secrets(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, f"{location}[{index}]")


def _reject_unknown(value: Mapping[str, object], expected: frozenset[str], location: str) -> None:
    for key in value:
        if key not in expected:
            raise ConfigError(f"unknown {location} key: {key}")


def _bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field_name} must be boolean")
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{field_name} must be a non-negative integer")
    return value


def _path(value: object, field_name: str, base: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field_name} must be a non-empty path string")
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _optional_path(value: object, field_name: str, base: Path) -> Path | None:
    return None if value is None else _path(value, field_name, base)


def _stringify_paths(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, Path):
                value[key] = str(item)
            else:
                _stringify_paths(item)
