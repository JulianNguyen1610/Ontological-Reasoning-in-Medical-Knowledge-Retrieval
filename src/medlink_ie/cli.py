"""Safe, deterministic command-line interface for MedLink-IE."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from enum import IntEnum
from pathlib import Path
from typing import Callable

from medlink_ie.pipeline import (
    BatchConfig,
    MedLinkPipeline,
    ResumePolicy,
    atomic_write_json,
    package_output,
    pre_submit_validate,
)
from medlink_ie.provenance import (
    load_artifact_inventory,
    load_terminology_manifest,
    verify_artifact_inventory,
    write_preflight_artifacts,
)
from medlink_ie.runtime import ConfigError, RuntimeConfig, load_config, save_resolved_config
from medlink_ie.terminology.preparation import (
    ICD10ZipAdapter,
    RxNormZipAdapter,
    prepare_from_manifest,
    write_canonical_tables,
)


class ExitCode(IntEnum):
    """Stable process outcomes suitable for automation."""

    OK = 0
    USAGE = 2
    CONFIG = 3
    RUNTIME = 4
    VALIDATION = 5
    UNSUPPORTED = 6


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser."""
    parser = argparse.ArgumentParser(
        prog="medlink-ie", description="Deterministic offline MedLink-IE"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    config_commands = (
        "validate-config",
        "offline-preflight",
        "prepare-terminology",
        "infer",
        "evaluate",
        "package",
        "validate-submit",
        "show-manifest",
    )
    for name in config_commands:
        child = commands.add_parser(name)
        child.add_argument("--config", required=True, help="strict YAML runtime configuration")
    final_gate = commands.add_parser("final-gate")
    final_gate.add_argument("--config", required=True, help="strict YAML runtime configuration")
    final_gate.add_argument(
        "--smoke-config", default="examples/smoke/config.yaml", help="smoke runtime configuration"
    )
    final_gate.add_argument("--recorded-commit", help="commit accepted for a dirty worktree")
    for name in ("train", "benchmark"):
        child = commands.add_parser(name)
        child.add_argument("module", help="supported module name")
        child.add_argument("--config", required=True, help="strict YAML runtime configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one MedLink-IE command and return a stable exit code."""
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else int(ExitCode.USAGE)
    try:
        config = load_config(args.config)
        save_resolved_config(config)
        handlers: dict[str, Callable[[RuntimeConfig, argparse.Namespace], None]] = {
            "validate-config": _validate_config,
            "offline-preflight": _offline_preflight,
            "final-gate": _final_gate,
            "prepare-terminology": _prepare_terminology,
            "infer": _infer,
            "evaluate": _evaluate,
            "package": _package,
            "validate-submit": _validate_submit,
            "show-manifest": _show_manifest,
            "train": _unsupported,
            "benchmark": _unsupported,
        }
        handlers[args.command](config, args)
    except ConfigError as error:
        return _safe_error(ExitCode.CONFIG, error)
    except (ValueError, TypeError, FileNotFoundError, OSError) as error:
        return _safe_error(ExitCode.VALIDATION, error)
    except NotImplementedError as error:
        return _safe_error(ExitCode.UNSUPPORTED, error)
    return int(ExitCode.OK)


def _validate_config(config: RuntimeConfig, _: argparse.Namespace) -> None:
    print(f"valid configuration: profile={config.profile}; offline=true")


def _offline_preflight(config: RuntimeConfig, _: argparse.Namespace) -> None:
    inventory_path = _required(config.artifacts.inventory, "artifacts.inventory")
    report = verify_artifact_inventory(load_artifact_inventory(inventory_path))
    report_path, environment_path = write_preflight_artifacts(config.paths.run_dir, report)
    print(f"preflight={report_path}; environment={environment_path}")
    if not report.ok:
        raise ValueError(
            f"offline preflight found {report.required_failure_count} required artifact failure(s)"
        )


def _final_gate(config: RuntimeConfig, args: argparse.Namespace) -> None:
    from medlink_ie.readiness import run_final_gate

    report = run_final_gate(
        config, Path(args.smoke_config).resolve(), recorded_commit=args.recorded_commit
    )
    atomic_write_json(config.paths.run_dir / "final_gate.json", report.to_dict())
    print(f"final gate: {'passed' if report.passed else 'failed'}")
    if not report.passed:
        raise ValueError("final submission-readiness gate failed; see final_gate.json")


def _prepare_terminology(config: RuntimeConfig, _: argparse.Namespace) -> None:
    manifest_path = _required(config.terminology.manifest, "terminology.manifest")
    destination = config.terminology.output_dir or config.paths.run_dir / "terminology"
    manifest = load_terminology_manifest(manifest_path)
    tables = prepare_from_manifest(
        manifest_path,
        ICD10ZipAdapter(frozenset({manifest.icd.version})),
        RxNormZipAdapter(
            frozenset({manifest.rxnorm.release}), frozenset(manifest.rxnorm.allowed_ttys)
        ),
    )
    paths = write_canonical_tables(tables, destination)
    print(paths.manifest_path)


def _infer(config: RuntimeConfig, _: argparse.Namespace) -> None:
    source = _required(config.paths.input, "paths.input")
    output_dir = config.paths.output_dir or config.paths.run_dir / "output"
    trace_dir = config.paths.trace_dir or config.paths.run_dir / "traces"
    files = (source,) if source.is_file() else tuple(sorted(source.glob("*.txt")))
    if not files:
        raise ValueError("paths.input must be a text file or directory containing .txt files")
    pipeline = MedLinkPipeline(())
    batch = BatchConfig(
        batch_size=config.batch.batch_size,
        resume_policy=ResumePolicy(config.batch.resume_policy),
        timeout_seconds=config.batch.timeout_seconds,
        capture_memory=config.batch.capture_memory,
    )
    report = pipeline.predict_paths(files, output_dir, trace_dir, batch)
    atomic_write_json(config.paths.run_dir / "infer_summary.json", asdict(report))
    if report.failures:
        raise ValueError("one or more input files could not be processed; see infer_summary.json")


def _evaluate(config: RuntimeConfig, _: argparse.Namespace) -> None:
    gold = _required(config.paths.gold, "paths.gold")
    predictions = _required(config.paths.predictions, "paths.predictions")
    gold_value, predicted_value = _json_array(gold), _json_array(predictions)
    from medlink_ie.evaluation.scorer import score_entities

    score = score_entities(gold_value, predicted_value)
    atomic_write_json(config.paths.run_dir / "evaluation.json", asdict(score))
    print(f"final_score={score.final_score:.6f}")


def _package(config: RuntimeConfig, _: argparse.Namespace) -> None:
    output_dir = config.paths.output_dir or config.paths.run_dir / "output"
    package_path = config.paths.package_path or config.paths.run_dir / "submission.zip"
    package_output(output_dir, package_path)
    print(package_path)


def _validate_submit(config: RuntimeConfig, _: argparse.Namespace) -> None:
    package_path = config.paths.package_path or config.paths.run_dir / "submission.zip"
    pre_submit_validate(package_path, _required(config.paths.input, "paths.input"))
    print("submission validation passed")


def _show_manifest(config: RuntimeConfig, _: argparse.Namespace) -> None:
    manifest_path = _required(config.terminology.manifest, "terminology.manifest")
    manifest = load_terminology_manifest(manifest_path)
    print(
        json.dumps(
            {"icd_version": manifest.icd.version, "rxnorm_release": manifest.rxnorm.release},
            sort_keys=True,
        )
    )


def _unsupported(_: RuntimeConfig, args: argparse.Namespace) -> None:
    raise NotImplementedError(f"{args.command} is not supported for module {args.module}")


def _json_array(path: Path) -> list[dict[str, object]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("evaluation files must be JSON arrays of entity objects")
    return value


def _required(value: Path | None, field_name: str) -> Path:
    if value is None:
        raise ValueError(f"{field_name} is required for this command")
    return value


def _safe_error(code: ExitCode, error: Exception) -> int:
    print(f"medlink-ie: {error}", file=sys.stderr)
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
