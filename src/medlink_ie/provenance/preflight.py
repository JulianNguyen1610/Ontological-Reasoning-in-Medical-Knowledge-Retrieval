"""Offline artifact inventory validation and environment reporting."""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import yaml

_MAX_MODEL_PARAMETERS = 9_000_000_000
_ROOT_KEYS = frozenset({"schema_version", "artifacts"})
_ARTIFACT_KEYS = frozenset(
    {"name", "path", "size_bytes", "sha256", "license", "required", "parameter_count"}
)


@dataclass(frozen=True, slots=True)
class ArtifactInventoryItem:
    """One declared local artifact; paths are resolved from the inventory file."""

    name: str
    path: Path
    size_bytes: int
    sha256: str
    license: str
    required: bool
    parameter_count: int | None = None


@dataclass(frozen=True, slots=True)
class ArtifactInventory:
    """The complete, versioned inventory used for an offline run."""

    path: Path
    artifacts: tuple[ArtifactInventoryItem, ...]


@dataclass(frozen=True, slots=True)
class ArtifactCheck:
    """Non-sensitive verification outcome for a single local file."""

    name: str
    path: str
    required: bool
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Safe report produced without reading artifact content beyond checksumming."""

    inventory_path: str
    artifacts: tuple[ArtifactCheck, ...]
    required_failure_count: int
    network_accessed: bool = False

    @property
    def ok(self) -> bool:
        """Whether every required artifact passed verification."""
        return self.required_failure_count == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report deterministically for run artifacts."""
        return {
            "artifacts": [
                {
                    "detail": item.detail,
                    "name": item.name,
                    "path": item.path,
                    "required": item.required,
                    "status": item.status,
                }
                for item in self.artifacts
            ],
            "inventory_path": self.inventory_path,
            "network_accessed": self.network_accessed,
            "ok": self.ok,
            "required_failure_count": self.required_failure_count,
        }


def load_artifact_inventory(path: str | Path) -> ArtifactInventory:
    """Load a strict inventory without contacting a registry or artifact store."""
    inventory_path = Path(path).resolve()
    try:
        data = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError("artifact inventory file does not exist") from error
    except yaml.YAMLError as error:
        raise ValueError("artifact inventory is not valid YAML") from error
    if not isinstance(data, Mapping):
        raise ValueError("artifact inventory must be a mapping")
    _unknown(data, _ROOT_KEYS, "artifact inventory")
    if data.get("schema_version") != 1:
        raise ValueError("unsupported artifact inventory schema_version")
    rows = data.get("artifacts")
    if not isinstance(rows, list) or not rows:
        raise ValueError("artifact inventory requires a non-empty artifacts list")
    artifacts = tuple(_item(row, inventory_path.parent) for row in rows)
    names = [item.name for item in artifacts]
    if len(set(names)) != len(names):
        raise ValueError("artifact inventory names must be unique")
    return ArtifactInventory(inventory_path, artifacts)


def verify_artifact_inventory(inventory: ArtifactInventory) -> PreflightReport:
    """Verify size, digest, and parameter limits using only declared local paths."""
    checks = tuple(_verify(item) for item in inventory.artifacts)
    failures = sum(item.required and item.status != "verified" for item in checks)
    return PreflightReport(str(inventory.path), checks, failures)


def environment_report() -> dict[str, Any]:
    """Return hardware/environment facts without dumping the process environment."""
    return {
        "cpu_count": os.cpu_count(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "gpu": _gpu_report(),
        "network_policy": "offline",
    }


def write_preflight_artifacts(directory: Path, report: PreflightReport) -> tuple[Path, Path]:
    """Write safe preflight and hardware reports to an existing run-artifact directory."""
    directory.mkdir(parents=True, exist_ok=True)
    preflight_path, environment_path = (
        directory / "offline_preflight.json",
        directory / "environment.json",
    )
    preflight_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    environment_path.write_text(
        json.dumps(environment_report(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return preflight_path, environment_path


def _item(value: object, base: Path) -> ArtifactInventoryItem:
    if not isinstance(value, Mapping):
        raise ValueError("artifact inventory item must be a mapping")
    _unknown(value, _ARTIFACT_KEYS, "artifact inventory item")
    name = _text(value.get("name"), "artifact name")
    relative_path = _text(value.get("path"), "artifact path")
    size = value.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("artifact size_bytes must be a non-negative integer")
    digest = _text(value.get("sha256"), "artifact sha256").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("artifact sha256 must be a SHA-256 hexadecimal digest")
    license_value = _text(value.get("license"), "artifact license")
    required = value.get("required")
    if not isinstance(required, bool):
        raise ValueError("artifact required must be boolean")
    parameter_count = value.get("parameter_count")
    if parameter_count is not None and (
        isinstance(parameter_count, bool)
        or not isinstance(parameter_count, int)
        or parameter_count < 1
    ):
        raise ValueError("artifact parameter_count must be a positive integer when set")
    source = Path(relative_path)
    return ArtifactInventoryItem(
        name,
        source if source.is_absolute() else (base / source).resolve(),
        size,
        digest,
        license_value,
        required,
        parameter_count,
    )


def _verify(item: ArtifactInventoryItem) -> ArtifactCheck:
    if item.parameter_count is not None and item.parameter_count > _MAX_MODEL_PARAMETERS:
        return _check(item, "invalid", "parameter_count exceeds 9B limit")
    if not item.path.is_file():
        return _check(
            item, "missing", "local artifact is missing; supply the declared file offline"
        )
    if item.path.stat().st_size != item.size_bytes:
        return _check(item, "size_mismatch", "local artifact size differs from inventory")
    if _checksum(item.path) != item.sha256:
        return _check(item, "checksum_mismatch", "local artifact checksum differs from inventory")
    return _check(item, "verified", "verified locally")


def _check(item: ArtifactInventoryItem, status: str, detail: str) -> ArtifactCheck:
    return ArtifactCheck(item.name, str(item.path), item.required, status, detail)


def _checksum(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _unknown(value: Mapping[str, object], allowed: frozenset[str], location: str) -> None:
    for key in value:
        if key not in allowed:
            raise ValueError(f"unknown {location} key: {key}")


def _gpu_report() -> dict[str, Any]:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return {"available": False, "reason": "torch_not_installed"}
    return {
        "available": bool(torch.cuda.is_available()),
        "device_count": int(torch.cuda.device_count()),
        "runtime": str(torch.version.cuda),
    }
