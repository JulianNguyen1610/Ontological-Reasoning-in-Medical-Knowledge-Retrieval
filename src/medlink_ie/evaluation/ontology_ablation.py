"""Controlled OFF/always-on/gated ontology ablation evaluation."""

from __future__ import annotations

import time
import tracemalloc
from dataclasses import dataclass, replace
from typing import Any, Mapping

from medlink_ie.evaluation.scorer import score_entities
from medlink_ie.linking.ontology import (
    OntologyMode,
    OntologyRequest,
    OntologyReranker,
    OntologyRerankerConfig,
    OntologySnapshot,
)


@dataclass(frozen=True, slots=True)
class AblationCase:
    case_id: str
    gold_entities: tuple[Mapping[str, Any], ...]
    base_predictions: tuple[Mapping[str, Any], ...]
    prediction_index: int
    request: OntologyRequest

    def __post_init__(self) -> None:
        object.__setattr__(self, "gold_entities", tuple(dict(item) for item in self.gold_entities))
        object.__setattr__(
            self, "base_predictions", tuple(dict(item) for item in self.base_predictions)
        )
        if not self.case_id or not 0 <= self.prediction_index < len(self.base_predictions):
            raise ValueError("ablation case requires an ID and valid prediction index")


@dataclass(frozen=True, slots=True)
class AblationConfig:
    minimum_score_delta: float
    latency_penalty_per_ms: float

    def __post_init__(self) -> None:
        if self.minimum_score_delta < 0.0 or self.latency_penalty_per_ms < 0.0:
            raise ValueError("ablation thresholds must be non-negative")


@dataclass(frozen=True, slots=True)
class VariantMetrics:
    name: str
    official_score: float
    candidate_jaccard: float
    latency_ms: float
    peak_memory_bytes: int
    per_case_scores: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MergeDecision:
    enabled: bool
    reason: str
    score_delta: float
    latency_cost_ms: float
    net_delta: float


@dataclass(frozen=True, slots=True)
class OntologyAblationReport:
    variants: tuple[VariantMetrics, ...]
    merge: MergeDecision


def run_ontology_ablation(
    cases: tuple[AblationCase, ...],
    snapshot: OntologySnapshot,
    base_config: OntologyRerankerConfig,
    config: AblationConfig,
) -> OntologyAblationReport:
    """Evaluate identical cases under OFF, always-on, and gated-on variants."""
    if not cases:
        raise ValueError("ablation requires cases")
    variants = tuple(
        _measure(name, mode, cases, snapshot, base_config)
        for name, mode in (
            ("off", OntologyMode.OFF),
            ("always_on", OntologyMode.ALWAYS_ON),
            ("gated_on", OntologyMode.GATED),
        )
    )
    by_name = {variant.name: variant for variant in variants}
    off, gated = by_name["off"], by_name["gated_on"]
    score_delta = gated.official_score - off.official_score
    latency_cost = gated.latency_ms - off.latency_ms
    net_delta = score_delta - config.latency_penalty_per_ms * max(latency_cost, 0.0)
    stable = all(
        gated_score >= off_score
        for gated_score, off_score in zip(gated.per_case_scores, off.per_case_scores)
    )
    enabled = stable and score_delta >= config.minimum_score_delta and net_delta > 0.0
    reason = "enabled" if enabled else "insufficient_stable_score_delta"
    return OntologyAblationReport(
        variants, MergeDecision(enabled, reason, score_delta, latency_cost, net_delta)
    )


def _measure(
    name: str,
    mode: OntologyMode,
    cases: tuple[AblationCase, ...],
    snapshot: OntologySnapshot,
    base_config: OntologyRerankerConfig,
) -> VariantMetrics:
    reranker = OntologyReranker(snapshot, replace(base_config, mode=mode))
    tracemalloc.start()
    start = time.perf_counter_ns()
    breakdowns = []
    for case in cases:
        prediction = [dict(item) for item in case.base_predictions]
        result = reranker.rerank(case.request)
        prediction[case.prediction_index]["candidates"] = [
            item.concept_id for item in result.candidates
        ]
        breakdowns.append(score_entities(case.gold_entities, tuple(prediction)))
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return VariantMetrics(
        name,
        sum(item.final_score for item in breakdowns) / len(breakdowns),
        sum(item.candidate_jaccard for item in breakdowns) / len(breakdowns),
        elapsed_ms,
        peak,
        tuple(item.final_score for item in breakdowns),
    )
