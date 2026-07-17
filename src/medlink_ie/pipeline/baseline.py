"""Deterministic orchestration and submission validation for existing components."""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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


@dataclass(frozen=True, slots=True)
class BatchReport:
    processed: tuple[str, ...]
    failures: tuple[dict[str, str], ...]
    trace_paths: tuple[str, ...]


class MedLinkPipeline:
    def __init__(
        self, proposers: Iterable[SpanProposer], config: PipelineConfig = PipelineConfig()
    ) -> None:
        self.proposers = tuple(proposers)
        self.config = config

    def predict_document(self, document: SourceDocument) -> tuple[FinalEntity, ...]:
        structure = StructuralAnalyzer().analyze(document)
        context = ProposalContext(document, build_text_views(document), structure=structure)
        proposals = tuple(p for proposer in self.proposers for p in proposer.propose(context))
        grounded = tuple(
            GroundedEvidence(p, g)
            for p in proposals
            if (g := ground_proposal(p, context)) is not None
        )
        clusters = BoundaryResolver(self.config.baseline).resolve(SpanClusterer().cluster(grounded))
        hypotheses = BasicAssertionEngine(self.config.baseline).apply(
            HeuristicTypeClassifier().classify(clusters, context), context
        )
        entities = []
        for hyp in hypotheses:
            entity_type, prob = max(
                hyp.type_probabilities.items(), key=lambda item: (item[1], item[0].value)
            )
            if prob < self.config.type_threshold:
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
        return deterministic_sort(tuple(entities))

    def predict_directory(self, input_dir: Path, output_dir: Path, trace_dir: Path) -> BatchReport:
        output_dir.mkdir(parents=True, exist_ok=True)
        trace_dir.mkdir(parents=True, exist_ok=True)
        processed = []
        failures = []
        traces = []
        for path in sorted(input_dir.glob("*.txt"), key=_numeric_path_key):
            try:
                raw = path.read_bytes()
                text = raw.decode("utf-8")
                doc = SourceDocument(path.stem, raw, text, "utf-8", False, "unknown")
                entities = self.predict_document(doc)
                atomic_write_json(output_dir / f"{path.stem}.json", [e.to_dict() for e in entities])
                atomic_write_json(
                    trace_dir / f"{path.stem}.trace.json",
                    {"document_id": path.stem, "entity_count": len(entities)},
                )
                processed.append(path.name)
                traces.append(str(trace_dir / f"{path.stem}.trace.json"))
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                failures.append({"file": path.name, "error": type(exc).__name__})
        return BatchReport(tuple(processed), tuple(failures), tuple(traces))


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        temporary = Path(handle.name)
    os.replace(temporary, path)


def package_output(output_dir: Path, zip_path: Path) -> None:
    with tempfile.NamedTemporaryFile(dir=zip_path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(output_dir.glob("*.json"), key=_numeric_path_key):
                archive.write(path, f"output/{path.name}")
        os.replace(temporary, zip_path)
    finally:
        temporary.unlink(missing_ok=True)


def pre_submit_validate(zip_path: Path, input_dir: Path) -> None:
    expected = [p.stem + ".json" for p in sorted(input_dir.glob("*.txt"), key=_numeric_path_key)]
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(archive.namelist())
        required = sorted(f"output/{name}" for name in expected)
        if names != required:
            raise ValueError("zip filenames or sample count mismatch")
        for source in sorted(input_dir.glob("*.txt"), key=_numeric_path_key):
            data = json.loads(archive.read(f"output/{source.stem}.json"))
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


def _numeric_path_key(path: Path) -> tuple[int, str]:
    match = re.search(r"\d+", path.stem)
    return (int(match.group()) if match else 10**18, path.name)
