"""Deterministic orchestration and submission validation for existing components."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import tracemalloc
import zipfile
from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping

from medlink_ie.domain import AssertionLabel, EntityType, FinalEntity, SourceDocument
from medlink_ie.fusion.baseline import (
    BaselineConfig,
    BasicAssertionEngine,
    BoundaryResolver,
    GroundedEvidence,
    HeuristicTypeClassifier,
    SpanClusterer,
)
from medlink_ie.grounding import ground_proposal
from medlink_ie.normalization.text_views import build_text_views
from medlink_ie.proposals.contract import ProposalContext, SpanProposer
from medlink_ie.structure.analyzer import StructuralAnalyzer


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    type_threshold: float = 0.5
    assertion_threshold: float = 0.5
    baseline: BaselineConfig = BaselineConfig()


class ResumePolicy(str, Enum):
    """The explicit treatment of existing per-sample artifacts."""

    NEVER = "never"
    REUSE_VALID = "reuse_valid"
    FAIL_IF_EXISTS = "fail_if_exists"


@dataclass(frozen=True, slots=True)
class BatchConfig:
    """Bounded, deterministic execution controls for one directory run."""

    batch_size: int = 16
    resume_policy: ResumePolicy = ResumePolicy.NEVER
    timeout_seconds: float | None = None
    capture_memory: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.batch_size, bool) or self.batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive when configured")
        if not isinstance(self.resume_policy, ResumePolicy):
            raise TypeError("resume_policy must be a ResumePolicy")
        if not isinstance(self.capture_memory, bool):
            raise TypeError("capture_memory must be bool")


@dataclass(frozen=True, slots=True)
class BatchReport:
    processed: tuple[str, ...]
    failures: tuple[dict[str, str], ...]
    trace_paths: tuple[str, ...]
    resumed: tuple[str, ...] = ()
    abstentions: int = 0
    module_timing_ms: dict[str, float] | None = None
    peak_memory_bytes: int | None = None


class MedLinkPipeline:
    def __init__(
        self, proposers: Iterable[SpanProposer], config: PipelineConfig = PipelineConfig()
    ) -> None:
        self.proposers = tuple(proposers)
        self.config = config

    def predict_document(self, document: SourceDocument) -> tuple[FinalEntity, ...]:
        entities, _, _ = self._predict_document_observed(document)
        return entities

    def _predict_document_observed(
        self, document: SourceDocument
    ) -> tuple[tuple[FinalEntity, ...], dict[str, float], dict[str, int]]:
        timings: dict[str, float] = {}
        started = time.perf_counter()
        structure = StructuralAnalyzer().analyze(document)
        timings["structure"] = _elapsed_ms(started)
        started = time.perf_counter()
        context = ProposalContext(document, build_text_views(document), structure=structure)
        proposals = tuple(p for proposer in self.proposers for p in proposer.propose(context))
        timings["proposals"] = _elapsed_ms(started)
        started = time.perf_counter()
        grounded = tuple(
            GroundedEvidence(p, g)
            for p in proposals
            if (g := ground_proposal(p, context)) is not None
        )
        timings["grounding"] = _elapsed_ms(started)
        started = time.perf_counter()
        clusters = BoundaryResolver(self.config.baseline).resolve(SpanClusterer().cluster(grounded))
        timings["fusion"] = _elapsed_ms(started)
        started = time.perf_counter()
        hypotheses = BasicAssertionEngine(self.config.baseline).apply(
            HeuristicTypeClassifier().classify(clusters, context), context
        )
        timings["classification_assertion"] = _elapsed_ms(started)
        entities = []
        abstentions = 0
        for hyp in hypotheses:
            entity_type, prob = max(
                hyp.type_probabilities.items(), key=lambda item: (item[1], item[0].value)
            )
            if prob < self.config.type_threshold:
                abstentions += 1
                continue
            assertions = tuple(
                sorted(
                    (
                        label
                        for label, value in hyp.assertion_probabilities.items()
                        if value >= self.config.assertion_threshold
                    ),
                    key=lambda x: x.value,
                )
            )
            entities.append(
                FinalEntity(hyp.text, entity_type, (hyp.raw_start, hyp.raw_end), assertions, None)
            )
        validate_semantics(tuple(entities), document)
        return (
            deterministic_sort(tuple(entities)),
            timings,
            {
                "proposals": len(proposals),
                "grounded": len(grounded),
                "clusters": len(clusters),
                "hypotheses": len(hypotheses),
                "entities": len(entities),
                "abstentions": abstentions,
            },
        )

    def predict_directory(
        self,
        input_dir: Path,
        output_dir: Path,
        trace_dir: Path,
        batch_config: BatchConfig = BatchConfig(),
    ) -> BatchReport:
        """Predict a directory with isolated sample failures and resumable artifacts."""
        if not input_dir.is_dir():
            raise ValueError("input_dir must be an existing directory")
        return self.predict_paths(
            tuple(sorted(input_dir.glob("*.txt"), key=_numeric_path_key)),
            output_dir,
            trace_dir,
            batch_config,
        )

    def predict_paths(
        self,
        paths: tuple[Path, ...],
        output_dir: Path,
        trace_dir: Path,
        batch_config: BatchConfig = BatchConfig(),
    ) -> BatchReport:
        """Predict explicit source paths without widening a single-file run's scope."""
        if any(not path.is_file() for path in paths):
            raise ValueError("all inference paths must be existing files")
        output_dir.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)
        paths = tuple(sorted(paths, key=_numeric_path_key))
        manifest_path = trace_dir / "run_manifest.json"
        running = _run_manifest("running", paths, batch_config, self.config)
        atomic_write_json(manifest_path, running)
        processed: list[str] = []
        failures: list[dict[str, str]] = []
        traces: list[str] = []
        resumed: list[str] = []
        timing_totals: dict[str, float] = {}
        abstentions = 0
        memory_started = False
        if batch_config.capture_memory:
            tracemalloc.start()
            memory_started = True
        try:
            for batch in _batches(paths, batch_config.batch_size):
                for path in batch:
                    outcome = self._predict_one(path, output_dir, trace_dir, batch_config)
                    if outcome["status"] == "resumed":
                        resumed.append(path.name)
                        traces.append(str(outcome["trace_path"]))
                    elif outcome["status"] == "completed":
                        processed.append(path.name)
                        traces.append(str(outcome["trace_path"]))
                        abstentions += int(outcome["counts"]["abstentions"])
                        _add_timings(timing_totals, outcome["timings"])
                    else:
                        failures.append({"file": path.name, "category": str(outcome["category"])})
        finally:
            peak_memory = tracemalloc.get_traced_memory()[1] if memory_started else None
            if memory_started:
                tracemalloc.stop()
            finalized = _run_manifest("finalized", paths, batch_config, self.config)
            finalized["counts"] = {
                "completed": len(processed),
                "failed": len(failures),
                "resumed": len(resumed),
                "abstentions": abstentions,
            }
            finalized["failure_categories"] = _failure_counts(failures)
            finalized["module_timing_ms"] = dict(sorted(timing_totals.items()))
            finalized["peak_memory_bytes"] = peak_memory
            atomic_write_json(manifest_path, finalized)
        return BatchReport(
            tuple(processed),
            tuple(failures),
            tuple(traces),
            tuple(resumed),
            abstentions,
            dict(sorted(timing_totals.items())),
            peak_memory,
        )

    def _predict_one(
        self, path: Path, output_dir: Path, trace_dir: Path, batch_config: BatchConfig
    ) -> dict[str, Any]:
        output_path, trace_path = (
            output_dir / f"{path.stem}.json",
            trace_dir / f"{path.stem}.trace.json",
        )
        try:
            if _existing_artifact_policy(output_path, trace_path, batch_config.resume_policy):
                return {"status": "resumed", "trace_path": trace_path}
            started = time.perf_counter()
            raw = path.read_bytes()
            text = raw.decode("utf-8")
            document = SourceDocument(path.stem, raw, text, "utf-8", False, "unknown")
            entities, timings, counts = self._predict_document_observed(document)
            elapsed = _elapsed_ms(started)
            if (
                batch_config.timeout_seconds is not None
                and elapsed > batch_config.timeout_seconds * 1000
            ):
                return {"status": "failed", "category": "timeout"}
            payload = [entity.to_dict() for entity in entities]
            atomic_write_json(output_path, payload)
            try:
                atomic_write_json(
                    trace_path,
                    _sample_trace(path.stem, output_path, entities, timings, counts, elapsed),
                )
            except OSError:
                output_path.unlink(missing_ok=True)
                raise
            return {
                "status": "completed",
                "trace_path": trace_path,
                "timings": timings,
                "counts": counts,
            }
        except MemoryError:
            return {"status": "failed", "category": "oom"}
        except UnicodeError:
            return {"status": "failed", "category": "input_decode"}
        except (FileNotFoundError, PermissionError, OSError):
            return {"status": "failed", "category": "io"}
        except (ValueError, TypeError):
            return {"status": "failed", "category": "prediction"}


def deterministic_sort(entities: tuple[FinalEntity, ...]) -> tuple[FinalEntity, ...]:
    return tuple(
        sorted(entities, key=lambda e: (e.position[0], e.position[1], e.type.value, e.text))
    )


def validate_semantics(entities: tuple[FinalEntity, ...], document: SourceDocument) -> None:
    seen = set()
    for entity in entities:
        entity.validate_semantics(document)
        if entity in seen:
            raise ValueError("duplicate output object")
        seen.add(entity)
        if entity.type not in EntityType or any(
            label not in AssertionLabel for label in entity.assertions
        ):
            raise ValueError("invalid enum")
        if entity.candidates is not None and entity.type not in {
            EntityType.DIAGNOSIS,
            EntityType.MEDICATION,
        }:
            raise ValueError("candidates are inapplicable")


def validate_json_schema(value: object) -> None:
    if not isinstance(value, list):
        raise ValueError("submission must be a JSON array")
    allowed = {"text", "type", "position", "assertions", "candidates"}
    for item in value:
        if not isinstance(item, dict) or set(item) != allowed:
            raise ValueError("invalid submission object keys")
        if any(key in item for key in {"trace", "confidence", "score"}):
            raise ValueError("debug field")


def atomic_write_json(path: Path, value: object) -> None:
    """Write JSON durably; a failed replacement never leaves a success target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def package_output(output_dir: Path, zip_path: Path) -> None:
    paths = tuple(sorted(output_dir.glob("*.json"), key=_numeric_path_key))
    if any(path.name.startswith(".") for path in paths):
        raise ValueError("hidden output files are forbidden")
    with tempfile.NamedTemporaryFile(dir=zip_path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                info = zipfile.ZipInfo(f"output/{path.name}", (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, zip_path)
    finally:
        temporary.unlink(missing_ok=True)


def pre_submit_validate(
    zip_path: Path,
    input_dir: Path,
    terminology_codes: Mapping[EntityType, frozenset[str]] | None = None,
) -> None:
    expected = [p.stem + ".json" for p in sorted(input_dir.glob("*.txt"), key=_numeric_path_key)]
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("submission is not a readable zip")
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        required = sorted(f"output/{name}" for name in expected)
        if names != required:
            raise ValueError("zip filenames or sample count mismatch")
        for source in sorted(input_dir.glob("*.txt"), key=_numeric_path_key):
            payload = archive.read(f"output/{source.stem}.json")
            try:
                data = json.loads(payload.decode("utf-8"), parse_constant=_reject_json_constant)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("submission JSON must be UTF-8 and finite") from error
            validate_json_schema(data)
            raw = source.read_bytes()
            doc = SourceDocument(source.stem, raw, raw.decode("utf-8"), "utf-8", False, "unknown")
            entities = tuple(
                FinalEntity(
                    item["text"],
                    EntityType(item["type"]),
                    tuple(item["position"]),
                    tuple(AssertionLabel(x) for x in item["assertions"]),
                    tuple(item["candidates"]) if item["candidates"] is not None else None,
                )
                for item in data
            )
            validate_semantics(entities, doc)
            if tuple(entities) != deterministic_sort(entities):
                raise ValueError("entities are not deterministically ordered")
            for entity in entities:
                if entity.candidates is not None and len(set(entity.candidates)) != len(
                    entity.candidates
                ):
                    raise ValueError("duplicate candidate code")
                if entity.candidates and terminology_codes is not None:
                    allowed_codes = terminology_codes.get(entity.type, frozenset())
                    if any(code not in allowed_codes for code in entity.candidates):
                        raise ValueError("candidate is absent from frozen terminology")


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _numeric_path_key(path: Path) -> tuple[int, str]:
    match = re.search(r"\d+", path.stem)
    return (int(match.group()) if match else 10**18, path.name)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _batches(paths: tuple[Path, ...], batch_size: int) -> Iterable[tuple[Path, ...]]:
    for index in range(0, len(paths), batch_size):
        yield paths[index : index + batch_size]


def _existing_artifact_policy(output_path: Path, trace_path: Path, policy: ResumePolicy) -> bool:
    if not output_path.exists() and not trace_path.exists():
        return False
    if policy is ResumePolicy.NEVER:
        return False
    if policy is ResumePolicy.FAIL_IF_EXISTS:
        raise ValueError("existing artifacts are forbidden by resume policy")
    if not output_path.is_file() or not trace_path.is_file():
        return False
    try:
        output = json.loads(output_path.read_text(encoding="utf-8"))
        validate_json_schema(output)
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(trace, dict)
        and trace.get("status") == "completed"
        and trace.get("output_sha256") == _file_checksum(output_path)
    )


def _sample_trace(
    document_id: str,
    output_path: Path,
    entities: tuple[FinalEntity, ...],
    timings: dict[str, float],
    counts: dict[str, int],
    elapsed_ms: float,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "status": "completed",
        "output_sha256": _file_checksum(output_path),
        "elapsed_ms": elapsed_ms,
        "module_timing_ms": dict(sorted(timings.items())),
        "counts": dict(sorted(counts.items())),
        "per_entity_decisions": [
            {
                "decision": "accepted",
                "entity_index": index,
                "start": entity.position[0],
                "end": entity.position[1],
                "type": entity.type.value,
                "assertion_count": len(entity.assertions),
                "candidate_count": 0 if entity.candidates is None else len(entity.candidates),
            }
            for index, entity in enumerate(entities)
        ],
    }


def _run_manifest(
    status: str,
    paths: tuple[Path, ...],
    batch_config: BatchConfig,
    pipeline_config: PipelineConfig,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "sample_order": [path.name for path in paths],
        "batch_config": {
            "batch_size": batch_config.batch_size,
            "resume_policy": batch_config.resume_policy.value,
            "timeout_seconds": batch_config.timeout_seconds,
            "capture_memory": batch_config.capture_memory,
        },
        "pipeline_config": asdict(pipeline_config),
        "counts": {"completed": 0, "failed": 0, "resumed": 0, "abstentions": 0},
    }


def _file_checksum(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _add_timings(total: dict[str, float], additions: object) -> None:
    if not isinstance(additions, dict):
        raise TypeError("timings must be a dictionary")
    for name, value in additions.items():
        if not isinstance(name, str) or not isinstance(value, float):
            raise TypeError("timings must map names to floats")
        total[name] = round(total.get(name, 0.0) + value, 3)


def _failure_counts(failures: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for failure in failures:
        category = failure["category"]
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))
