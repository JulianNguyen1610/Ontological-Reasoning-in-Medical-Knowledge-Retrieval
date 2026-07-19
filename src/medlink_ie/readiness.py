"""Automated, evidence-backed submission-readiness checks."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable

from medlink_ie.pipeline import atomic_write_json
from medlink_ie.provenance import (
    load_artifact_inventory,
    verify_artifact_inventory,
    write_preflight_artifacts,
)
from medlink_ie.runtime import RuntimeConfig


@dataclass(frozen=True, slots=True)
class GateCheck:
    """One safe, named readiness outcome."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class GateReport:
    """Deterministic report written by the final submission gate."""

    checks: tuple[GateCheck, ...]

    @property
    def passed(self) -> bool:
        """Whether every required check passed."""
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        """Serialize the report without clinical source text."""
        return {
            "checks": [
                {"detail": check.detail, "name": check.name, "passed": check.passed}
                for check in self.checks
            ],
            "passed": self.passed,
        }


def run_final_gate(
    config: RuntimeConfig,
    smoke_config: Path,
    recorded_commit: str | None = None,
    command_runner: Callable[[list[str], Path], bool] | None = None,
) -> GateReport:
    """Run the local-only final gate and persist its safe report in ``run_dir``."""
    root = _project_root(config.config_path)
    runner = command_runner or _run_command
    checks: list[GateCheck] = [_git_check(root, recorded_commit)]
    checks.append(GateCheck("config", True, "strict configuration already validated"))
    checks.append(_repository_check(root, config))
    checks.extend(_artifact_checks(config))
    checks.append(_network_policy_check(config))
    checks.append(
        GateCheck(
            "tests",
            runner([sys.executable, "-m", "pytest", "-q"], root),
            "pytest completed" if runner is not _run_command else "pytest subprocess completed",
        )
    )
    checks.extend(_smoke_checks(smoke_config, root, runner))
    report = GateReport(tuple(checks))
    atomic_write_json(config.paths.run_dir / "final_gate.json", report.to_dict())
    return report


def validate_run_manifest(trace_directory: Path) -> GateCheck:
    """Check that the batch lifecycle manifest is finalized and internally complete."""
    manifest_path = trace_directory / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        counts = manifest["counts"]
        complete = counts["completed"] + counts["failed"] + counts["resumed"]
        expected = len(manifest["sample_order"])
        valid = manifest["status"] == "finalized" and complete == expected
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return GateCheck("run_manifest", False, "missing, invalid, or incomplete run manifest")
    return GateCheck(
        "run_manifest",
        valid,
        "finalized and complete" if valid else "run manifest counts do not match sample order",
    )


def _git_check(root: Path, recorded_commit: str | None) -> GateCheck:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False
    )
    if status.returncode != 0:
        return GateCheck("git", False, "git status could not be determined")
    if not status.stdout.strip():
        return GateCheck("git", True, "working tree is clean")
    if recorded_commit is None:
        return GateCheck("git", False, "working tree is dirty; supply --recorded-commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    matches = head.returncode == 0 and head.stdout.strip() == recorded_commit
    return GateCheck(
        "git",
        matches,
        "recorded commit matches HEAD" if matches else "recorded commit does not match HEAD",
    )


def _repository_check(root: Path, config: RuntimeConfig) -> GateCheck:
    required = (
        root / "README.md",
        root / "requirements.lock",
        root / "src" / "medlink_ie",
        root / "specs" / "TASK_CONTRACT.md",
        root / "specs" / "artifact_inventory.yaml",
        config.paths.input,
    )
    missing = [
        "paths.input" if path is None else path.name
        for path in required
        if path is None or not path.exists()
    ]
    return GateCheck(
        "required_inputs",
        not missing,
        "required source/data/docs present" if not missing else "missing: " + ", ".join(missing),
    )


def _artifact_checks(config: RuntimeConfig) -> tuple[GateCheck, ...]:
    if config.artifacts.inventory is None:
        return (GateCheck("artifacts", False, "artifacts.inventory is required for final gate"),)
    report = verify_artifact_inventory(load_artifact_inventory(config.artifacts.inventory))
    write_preflight_artifacts(config.paths.run_dir, report)
    valid_models = all(item.status != "invalid" for item in report.artifacts)
    return (
        GateCheck(
            "artifact_checksums",
            report.ok,
            "required artifacts verified" if report.ok else "required artifact verification failed",
        ),
        GateCheck(
            "model_parameter_limit",
            valid_models,
            "declared models comply with <=9B"
            if valid_models
            else "model parameter limit violation",
        ),
    )


def _network_policy_check(config: RuntimeConfig) -> GateCheck:
    try:
        preflight = json.loads(
            (config.paths.run_dir / "offline_preflight.json").read_text(encoding="utf-8")
        )
        preflight_offline = preflight["network_accessed"] is False
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        preflight_offline = False
    passed = config.offline and preflight_offline
    return GateCheck(
        "network_policy",
        passed,
        "offline policy enabled; artifact preflight recorded no network access"
        if passed
        else "offline policy or network-free preflight evidence is missing",
    )


def _smoke_checks(
    smoke_config: Path, root: Path, runner: Callable[[list[str], Path], bool]
) -> tuple[GateCheck, ...]:
    if not smoke_config.is_file():
        return (GateCheck("smoke", False, "smoke configuration is missing"),)
    inferred = runner(
        [sys.executable, "-m", "medlink_ie.cli", "infer", "--config", str(smoke_config)], root
    )
    if not inferred:
        return (GateCheck("smoke", False, "smoke inference failed"),)
    from medlink_ie.runtime import load_config

    config = load_config(smoke_config)
    traces = config.paths.trace_dir or config.paths.run_dir / "traces"
    return (
        GateCheck("smoke", True, "smoke inference completed"),
        validate_run_manifest(traces),
        _output_check(config),
    )


def _output_check(config: RuntimeConfig) -> GateCheck:
    output = config.paths.output_dir or config.paths.run_dir / "output"
    source = config.paths.input
    if source is None:
        return GateCheck("output_validation", False, "smoke input is missing")
    expected = (source,) if source.is_file() else tuple(sorted(source.glob("*.txt")))
    try:
        from medlink_ie.pipeline.baseline import validate_json_schema

        for path in expected:
            validate_json_schema(
                json.loads((output / f"{path.stem}.json").read_text(encoding="utf-8"))
            )
        expected_hashes = config.config_path.parent / "expected_hashes.yaml"
        if expected_hashes.is_file():
            import yaml

            hashes = yaml.safe_load(expected_hashes.read_text(encoding="utf-8"))
            values = hashes.get("outputs", {}) if isinstance(hashes, dict) else {}
            if not isinstance(values, dict):
                raise ValueError("expected_hashes outputs must be a mapping")
            for name, digest in values.items():
                if not isinstance(name, str) or not isinstance(digest, str):
                    raise ValueError("expected_hashes entries must be strings")
                if sha256((output / name).read_bytes()).hexdigest() != digest:
                    return GateCheck("output_validation", False, "smoke output hash mismatch")
    except (OSError, ValueError, json.JSONDecodeError):
        return GateCheck("output_validation", False, "smoke output is missing or invalid")
    return GateCheck("output_validation", True, "smoke submission JSON validated")


def _project_root(start: Path) -> Path:
    for candidate in (start.parent, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ValueError("project root with pyproject.toml could not be located")


def _run_command(command: list[str], cwd: Path) -> bool:
    return subprocess.run(command, cwd=cwd, check=False).returncode == 0
