"""Deterministic, traceable evaluation and experiment-reporting primitives."""

from __future__ import annotations

import json
import os
import platform
import random
import tempfile
from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from medlink_ie.annotation.gold import GoldEntity, GoldSample
from medlink_ie.domain import AssertionLabel, EntityType
from medlink_ie.evaluation.scorer import ScoreBreakdown, ScoringConfig, score_entities


@dataclass(frozen=True, slots=True)
class PredictionEntity:
    text: str
    start: int
    end: int
    type: EntityType
    assertions: tuple[AssertionLabel, ...] = ()
    candidates: tuple[str, ...] | None = None
    candidate_ranking: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "assertions", tuple(self.assertions))
        object.__setattr__(self, "candidate_ranking", tuple(self.candidate_ranking))
        if self.candidates is not None:
            object.__setattr__(self, "candidates", tuple(self.candidates))
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("prediction text must be a non-empty string")
        if (
            not isinstance(self.start, int)
            or not isinstance(self.end, int)
            or self.start < 0
            or self.end <= self.start
        ):
            raise ValueError("prediction span must be a non-empty non-negative interval")
        if not isinstance(self.type, EntityType):
            raise TypeError("prediction type must be an EntityType")
        if any(not isinstance(value, AssertionLabel) for value in self.assertions):
            raise TypeError("prediction assertions must contain AssertionLabel values")
        if self.candidates is not None and any(
            not isinstance(value, str) or not value for value in self.candidates
        ):
            raise ValueError("prediction candidates must contain non-empty strings")
        if any(not isinstance(value, str) or not value for value in self.candidate_ranking):
            raise ValueError("candidate_ranking must contain non-empty strings")

    def scorer_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "type": self.type.value,
            "position": [self.start, self.end],
            "assertions": [value.value for value in self.assertions],
            "candidates": None if self.candidates is None else list(self.candidates),
        }


@dataclass(frozen=True, slots=True)
class PredictionSample:
    sample_id: str
    entities: tuple[PredictionEntity, ...] = ()
    latency_ms: float | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "entities", tuple(self.entities))
        if not isinstance(self.sample_id, str) or not self.sample_id:
            raise ValueError("prediction sample_id must be a non-empty string")
        if any(not isinstance(entity, PredictionEntity) for entity in self.entities):
            raise TypeError("prediction entities must contain PredictionEntity values")
        if self.latency_ms is not None and (
            not isinstance(self.latency_ms, (int, float)) or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be a non-negative number or None")
        if self.failure_reason is not None and (
            not isinstance(self.failure_reason, str) or not self.failure_reason
        ):
            raise ValueError("failure_reason must be a non-empty string or None")


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    config_hash: str
    data_manifests: Mapping[str, str]
    model_artifacts: Mapping[str, str]
    terminology_snapshot: str
    code_commit: str
    seed: int
    environment: Mapping[str, str]
    feature_flags: Mapping[str, bool]

    @classmethod
    def create(
        cls,
        run_id: str,
        config: Mapping[str, Any],
        data_manifests: Mapping[str, str],
        model_artifacts: Mapping[str, str],
        terminology_snapshot: str,
        code_commit: str,
        seed: int,
        environment: Mapping[str, str] | None = None,
        feature_flags: Mapping[str, bool] | None = None,
    ) -> "RunManifest":
        environment_data = {"python": platform.python_version(), "platform": platform.platform()}
        environment_data.update(environment or {})
        return cls(
            run_id,
            _hash_json(config),
            MappingProxyType(dict(data_manifests)),
            MappingProxyType(dict(model_artifacts)),
            terminology_snapshot,
            code_commit,
            seed,
            MappingProxyType(environment_data),
            MappingProxyType(dict(feature_flags or {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_hash": self.config_hash,
            "data_manifests": dict(sorted(self.data_manifests.items())),
            "model_artifacts": dict(sorted(self.model_artifacts.items())),
            "terminology_snapshot": self.terminology_snapshot,
            "code_commit": self.code_commit,
            "seed": self.seed,
            "environment": dict(sorted(self.environment.items())),
            "feature_flags": dict(sorted(self.feature_flags.items())),
        }


@dataclass(frozen=True, slots=True)
class TraceMetric:
    value: float
    traces: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TypeMetric:
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    false_negative: int
    traces: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssertionMetrics:
    by_label: Mapping[str, TypeMetric]
    scope_error: TraceMetric


@dataclass(frozen=True, slots=True)
class LinkingMetrics:
    recall_at_k: Mapping[int, float]
    mrr: float
    oracle_candidate_score: float
    final_jaccard: float
    traces: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SystemMetrics:
    mean_latency_ms: float
    max_latency_ms: float
    failure_count: int
    failure_reasons: Mapping[str, int]
    traces: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    manifest: RunManifest
    scorer: TraceMetric
    extraction_by_type: Mapping[str, TypeMetric]
    boundary_error: TraceMetric
    assertions: AssertionMetrics
    linking: LinkingMetrics
    system: SystemMetrics
    error_taxonomy: Mapping[str, tuple[str, ...]]
    per_sample_scores: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "scorer": _trace_metric_dict(self.scorer),
            "extraction_by_type": {
                key: _type_metric_dict(value)
                for key, value in sorted(self.extraction_by_type.items())
            },
            "boundary_error": _trace_metric_dict(self.boundary_error),
            "assertions": {
                "by_label": {
                    key: _type_metric_dict(value)
                    for key, value in sorted(self.assertions.by_label.items())
                },
                "scope_error": _trace_metric_dict(self.assertions.scope_error),
            },
            "linking": {
                "recall_at_k": {
                    str(key): value for key, value in sorted(self.linking.recall_at_k.items())
                },
                "mrr": self.linking.mrr,
                "oracle_candidate_score": self.linking.oracle_candidate_score,
                "final_jaccard": self.linking.final_jaccard,
                "traces": list(self.linking.traces),
            },
            "system": {
                "mean_latency_ms": self.system.mean_latency_ms,
                "max_latency_ms": self.system.max_latency_ms,
                "failure_count": self.system.failure_count,
                "failure_reasons": dict(sorted(self.system.failure_reasons.items())),
                "traces": list(self.system.traces),
            },
            "error_taxonomy": {
                key: list(value) for key, value in sorted(self.error_taxonomy.items())
            },
            "per_sample_scores": dict(sorted(self.per_sample_scores.items())),
        }

    def to_markdown(self) -> str:
        lines = [f"# Evaluation report: {self.manifest.run_id}", "", "## Primary metrics", ""]
        lines.extend(
            (
                f"- Scorer final score: {self.scorer.value:.4f}",
                f"- Boundary errors: {self.boundary_error.value:.0f}",
                f"- Linking MRR: {self.linking.mrr:.4f}",
                f"- Failures: {self.system.failure_count}",
            )
        )
        lines.extend(("", "## Error taxonomy", ""))
        lines.extend(
            f"- {name}: {len(traces)}" for name, traces in sorted(self.error_taxonomy.items())
        )
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class RunComparison:
    baseline_run_id: str
    candidate_run_id: str
    delta_final_score: float
    confidence_interval: tuple[float, float]
    statistically_relevant: bool
    changed_error_buckets: Mapping[str, int]


def evaluate_predictions(
    gold_samples: Iterable[GoldSample],
    prediction_samples: Iterable[PredictionSample],
    manifest: RunManifest,
    scorer_config: ScoringConfig | None = None,
) -> EvaluationReport:
    """Evaluate immutable prediction/gold objects with local deterministic metrics."""
    gold_values = tuple(gold_samples)
    prediction_values = tuple(prediction_samples)
    gold = {sample.sample_id: sample for sample in gold_values}
    predictions = {sample.sample_id: sample for sample in prediction_values}
    if set(gold) != set(predictions):
        raise ValueError("gold and prediction sample IDs must match exactly")
    if len(gold) != len(gold_values) or len(predictions) != len(prediction_values):
        raise ValueError("duplicate sample IDs are not allowed")
    breakdowns: list[ScoreBreakdown] = []
    per_sample_scores: dict[str, float] = {}
    type_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    type_traces: dict[str, set[str]] = defaultdict(set)
    assertion_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    assertion_traces: dict[str, set[str]] = defaultdict(set)
    taxonomy: dict[str, set[str]] = defaultdict(set)
    boundary_traces: set[str] = set()
    scope_traces: set[str] = set()
    linking_values: list[tuple[float, float, float, float, float, str]] = []
    for sample_id in sorted(gold):
        gold_sample, prediction = gold[sample_id], predictions[sample_id]
        score = score_entities(
            _gold_scorer_entities(gold_sample),
            [entity.scorer_dict() for entity in prediction.entities],
            scorer_config,
        )
        breakdowns.append(score)
        per_sample_scores[sample_id] = score.final_score
        pairs, missing, extra = _align(gold_sample.entities, prediction.entities)
        _collect_extraction(
            sample_id,
            gold_sample.entities,
            prediction.entities,
            pairs,
            missing,
            extra,
            type_counts,
            type_traces,
            taxonomy,
            boundary_traces,
        )
        _collect_assertions(
            sample_id,
            pairs,
            gold_sample.entities,
            prediction.entities,
            assertion_counts,
            assertion_traces,
            taxonomy,
            scope_traces,
        )
        linking_values.extend(
            _collect_linking(sample_id, gold_sample.entities, prediction.entities, pairs, taxonomy)
        )
        if prediction.failure_reason is not None:
            taxonomy["failure"].add(sample_id)
    scorer = TraceMetric(_mean([value.final_score for value in breakdowns]), tuple(sorted(gold)))
    extraction = MappingProxyType(
        {
            key: _metric(values[0], values[1], values[2], type_traces[key])
            for key, values in type_counts.items()
        }
    )
    assertions = AssertionMetrics(
        MappingProxyType(
            {
                key: _metric(values[0], values[1], values[2], assertion_traces[key])
                for key, values in assertion_counts.items()
            }
        ),
        TraceMetric(float(len(scope_traces)), tuple(sorted(scope_traces))),
    )
    latencies = [
        float(item.latency_ms) for item in predictions.values() if item.latency_ms is not None
    ]
    failures: defaultdict[str, int] = defaultdict(int)
    for prediction in predictions.values():
        if prediction.failure_reason is not None:
            failures[prediction.failure_reason] += 1
    return EvaluationReport(
        manifest,
        scorer,
        extraction,
        TraceMetric(float(len(boundary_traces)), tuple(sorted(boundary_traces))),
        assertions,
        _linking_metrics(linking_values),
        SystemMetrics(
            _mean(latencies),
            max(latencies, default=0.0),
            sum(failures.values()),
            MappingProxyType(dict(failures)),
            tuple(sorted(predictions)),
        ),
        MappingProxyType({key: tuple(sorted(value)) for key, value in sorted(taxonomy.items())}),
        MappingProxyType(per_sample_scores),
    )


def compare_runs(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    bootstrap_samples: int = 1000,
    seed: int = 0,
) -> RunComparison:
    """Compare paired sample scores with deterministic bootstrap confidence intervals."""
    if set(baseline.per_sample_scores) != set(candidate.per_sample_scores):
        raise ValueError("runs must cover the same sample IDs")
    identifiers = tuple(sorted(baseline.per_sample_scores))
    differences = [
        candidate.per_sample_scores[key] - baseline.per_sample_scores[key] for key in identifiers
    ]
    delta = _mean(differences)
    rng = random.Random(seed)
    draws = sorted(
        _mean([differences[rng.randrange(len(differences))] for _ in differences])
        for _ in range(bootstrap_samples)
    )
    lower, upper = (
        draws[int(0.025 * (bootstrap_samples - 1))],
        draws[int(0.975 * (bootstrap_samples - 1))],
    )
    buckets = set(baseline.error_taxonomy) | set(candidate.error_taxonomy)
    changed = {
        name: len(candidate.error_taxonomy.get(name, ()))
        - len(baseline.error_taxonomy.get(name, ()))
        for name in sorted(buckets)
    }
    return RunComparison(
        baseline.manifest.run_id,
        candidate.manifest.run_id,
        delta,
        (lower, upper),
        lower > 0 or upper < 0,
        MappingProxyType(changed),
    )


def write_reports(directory: Path, report: EvaluationReport) -> tuple[Path, Path]:
    """Write privacy-safe JSON and Markdown reports, refusing to overwrite existing files."""
    directory.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path = directory / "report.json", directory / "report.md"
    if json_path.exists() or markdown_path.exists():
        raise FileExistsError("report paths already exist")
    _atomic_write(
        json_path, json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    _atomic_write(markdown_path, report.to_markdown())
    return json_path, markdown_path


def _gold_scorer_entities(sample: GoldSample) -> list[dict[str, Any]]:
    return [
        {
            "text": entity.text,
            "type": entity.type.value,
            "position": [entity.start, entity.end],
            "assertions": [item.value for item in entity.assertions],
            "candidates": None if entity.candidates is None else list(entity.candidates),
        }
        for entity in sample.entities
    ]


def _align(
    gold: tuple[GoldEntity, ...], prediction: tuple[PredictionEntity, ...]
) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    pool: dict[tuple[int, int, EntityType], deque[int]] = defaultdict(deque)
    for index, prediction_entity in enumerate(prediction):
        pool[(prediction_entity.start, prediction_entity.end, prediction_entity.type)].append(index)
    pairs, missing = [], set()
    for index, gold_entity in enumerate(gold):
        queue = pool[(gold_entity.start, gold_entity.end, gold_entity.type)]
        if queue:
            pairs.append((index, queue.popleft()))
        else:
            missing.add(index)
    return pairs, missing, {index for values in pool.values() for index in values}


def _collect_extraction(
    sample_id: str,
    gold: tuple[GoldEntity, ...],
    prediction: tuple[PredictionEntity, ...],
    pairs: list[tuple[int, int]],
    missing: set[int],
    extra: set[int],
    counts: dict[str, list[int]],
    traces: dict[str, set[str]],
    taxonomy: dict[str, set[str]],
    boundary: set[str],
) -> None:
    for gold_index, _ in pairs:
        key, trace = gold[gold_index].type.value, f"{sample_id}:g{gold_index}"
        counts[key][0] += 1
        traces[key].add(trace)
    for gold_index in sorted(missing):
        gold_entity = gold[gold_index]
        trace = f"{sample_id}:g{gold_index}"
        counts[gold_entity.type.value][2] += 1
        traces[gold_entity.type.value].add(trace)
        overlaps = [
            item
            for item in prediction
            if _overlap(gold_entity.start, gold_entity.end, item.start, item.end)
        ]
        if any(item.type is gold_entity.type for item in overlaps):
            taxonomy["boundary_error"].add(trace)
            boundary.add(trace)
        elif overlaps:
            taxonomy["type_error"].add(trace)
        else:
            taxonomy["missing_entity"].add(trace)
    for prediction_index in sorted(extra):
        prediction_entity = prediction[prediction_index]
        trace = f"{sample_id}:p{prediction_index}"
        counts[prediction_entity.type.value][1] += 1
        traces[prediction_entity.type.value].add(trace)
        if not any(
            _overlap(prediction_entity.start, prediction_entity.end, item.start, item.end)
            for item in gold
        ):
            taxonomy["spurious_entity"].add(trace)


def _collect_assertions(
    sample_id: str,
    pairs: list[tuple[int, int]],
    gold: tuple[GoldEntity, ...],
    prediction: tuple[PredictionEntity, ...],
    counts: dict[str, list[int]],
    traces: dict[str, set[str]],
    taxonomy: dict[str, set[str]],
    scope: set[str],
) -> None:
    for gold_index, prediction_index in pairs:
        left = gold[gold_index]
        right = prediction[prediction_index]
        for label in set(left.assertions) | set(right.assertions):
            key, trace = label.value, f"{sample_id}:g{gold_index}"
            if label in left.assertions and label in right.assertions:
                counts[key][0] += 1
            elif label in right.assertions:
                counts[key][1] += 1
                taxonomy["assertion_label_error"].add(trace)
            else:
                counts[key][2] += 1
                taxonomy["assertion_label_error"].add(trace)
            traces[key].add(trace)
    for gold_index, left in enumerate(gold):
        for right in prediction:
            if (
                left.type is right.type
                and _overlap(left.start, left.end, right.start, right.end)
                and (left.start, left.end) != (right.start, right.end)
                and set(left.assertions) & set(right.assertions)
            ):
                trace = f"{sample_id}:g{gold_index}"
                scope.add(trace)
                taxonomy["assertion_scope_error"].add(trace)


def _collect_linking(
    sample_id: str,
    gold: tuple[GoldEntity, ...],
    prediction: tuple[PredictionEntity, ...],
    pairs: list[tuple[int, int]],
    taxonomy: dict[str, set[str]],
) -> list[tuple[float, float, float, float, float, str]]:
    values: list[tuple[float, float, float, float, float, str]] = []
    for gold_index, prediction_index in pairs:
        left = gold[gold_index]
        right = prediction[prediction_index]
        if left.candidates is None:
            continue
        trace = f"{sample_id}:g{gold_index}"
        target, ranking = set(left.candidates), right.candidate_ranking
        rank = next(
            (index + 1 for index, candidate in enumerate(ranking) if candidate in target), None
        )
        recall_1, recall_5 = (
            float(rank is not None and rank <= 1),
            float(rank is not None and rank <= 5),
        )
        mrr = 0.0 if rank is None else 1.0 / rank
        predicted = set(right.candidates or ())
        oracle = float(bool(predicted & target))
        jaccard = (
            1.0
            if not predicted and not target
            else len(predicted & target) / len(predicted | target)
        )
        if not oracle:
            taxonomy["linking_miss"].add(trace)
        values.append((recall_1, recall_5, mrr, oracle, jaccard, trace))
    return values


def _linking_metrics(values: list[tuple[float, float, float, float, float, str]]) -> LinkingMetrics:
    return LinkingMetrics(
        {
            1: _mean([value[0] for value in values]),
            2: _mean([float(value[2] >= 0.5) for value in values]),
            5: _mean([value[1] for value in values]),
        },
        _mean([value[2] for value in values]),
        _mean([value[3] for value in values]),
        _mean([value[4] for value in values]),
        tuple(sorted(value[5] for value in values)),
    )


def _metric(tp: int, fp: int, fn: int, traces: set[str]) -> TypeMetric:
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return TypeMetric(
        precision,
        recall,
        0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall),
        tp,
        fp,
        fn,
        tuple(sorted(traces)),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return left_start < right_end and right_start < left_end


def _mean(values: list[float]) -> float:
    return 0.0 if not values else sum(values) / len(values)


def _hash_json(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _trace_metric_dict(value: TraceMetric) -> dict[str, Any]:
    return {"value": value.value, "traces": list(value.traces)}


def _type_metric_dict(value: TypeMetric) -> dict[str, Any]:
    return {
        "precision": value.precision,
        "recall": value.recall,
        "f1": value.f1,
        "true_positive": value.true_positive,
        "false_positive": value.false_positive,
        "false_negative": value.false_negative,
        "traces": list(value.traces),
    }


def _atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    os.replace(temporary, path)
