"""Frozen-snapshot, deterministic diagnostics for terminology linking outputs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

_REQUIRED_VARIANTS = ("lexical", "dense", "fused", "reranked")
_RECALL_KS = (1, 5, 10, 20, 50)
_ERROR_BUCKETS = (
    "alias_missing",
    "retrieval_miss",
    "rerank_miss",
    "wrong_granularity",
    "structured_mismatch",
    "obsolete_concept",
    "ambiguous_gold",
)


CandidateKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class FrozenLinkingGold:
    """One frozen gold entity; this type deliberately has no query-construction fields."""

    sample_id: str
    entity_id: str
    entity_type: str
    terminology: str
    gold_concept_ids: tuple[str, ...]
    granularity: str | None
    gold_snapshot_checksum: str
    terminology_snapshot_checksum: str
    alias_present: bool

    def __post_init__(self) -> None:
        if not all(
            (
                self.sample_id,
                self.entity_id,
                self.entity_type,
                self.terminology,
                self.gold_snapshot_checksum,
                self.terminology_snapshot_checksum,
            )
        ):
            raise ValueError("frozen gold identity and snapshot checksums must be non-empty")
        object.__setattr__(self, "gold_concept_ids", tuple(sorted(set(self.gold_concept_ids))))

    @property
    def trace_id(self) -> str:
        return f"{self.sample_id}:{self.entity_id}"


@dataclass(frozen=True, slots=True)
class CandidatePrediction:
    terminology: str
    concept_id: str
    granularity: str | None
    obsolete: bool = False

    def __post_init__(self) -> None:
        if not self.terminology or not self.concept_id:
            raise ValueError("candidate terminology and concept_id must be non-empty")


@dataclass(frozen=True, slots=True)
class LinkingVariantPrediction:
    """Precomputed candidate output for one variant; evaluator never constructs queries."""

    ranked_candidates: tuple[CandidatePrediction, ...]
    final_candidates: tuple[CandidatePrediction, ...]
    structured_rejected_candidates: tuple[CandidatePrediction, ...] = ()

    def __post_init__(self) -> None:
        ranked = _deduplicate_ranked(self.ranked_candidates)
        object.__setattr__(self, "ranked_candidates", ranked)
        object.__setattr__(self, "final_candidates", _deduplicate_ranked(self.final_candidates))
        object.__setattr__(
            self,
            "structured_rejected_candidates",
            _deduplicate_ranked(self.structured_rejected_candidates),
        )


@dataclass(frozen=True, slots=True)
class LinkingVariantMetrics:
    entity_count: int
    exact_match_coverage: float
    recall_at_k: Mapping[int, float]
    mrr: float
    oracle_candidate_jaccard: float
    reranker_top1_accuracy: float
    final_candidate_jaccard: float
    abstention_precision: float
    abstention_coverage: float
    trace_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "recall_at_k", MappingProxyType(dict(self.recall_at_k)))


@dataclass(frozen=True, slots=True)
class LinkingEvaluationReport:
    gold_snapshot_checksum: str
    terminology_snapshot_checksum: str
    variants: Mapping[str, LinkingVariantMetrics]
    by_entity_type: Mapping[str, Mapping[str, LinkingVariantMetrics]]
    by_terminology: Mapping[str, Mapping[str, LinkingVariantMetrics]]
    error_buckets: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "variants", MappingProxyType(dict(self.variants)))
        object.__setattr__(
            self,
            "by_entity_type",
            MappingProxyType(
                {key: MappingProxyType(dict(value)) for key, value in self.by_entity_type.items()}
            ),
        )
        object.__setattr__(
            self,
            "by_terminology",
            MappingProxyType(
                {key: MappingProxyType(dict(value)) for key, value in self.by_terminology.items()}
            ),
        )
        object.__setattr__(self, "error_buckets", MappingProxyType(dict(self.error_buckets)))


def evaluate_linking(
    gold: tuple[FrozenLinkingGold, ...],
    variant_outputs: Mapping[str, tuple[LinkingVariantPrediction, ...]],
    gold_snapshot_checksum: str,
    terminology_snapshot_checksum: str,
) -> LinkingEvaluationReport:
    """Evaluate precomputed variants against matching immutable gold/snapshot identifiers."""
    _validate_inputs(gold, variant_outputs, gold_snapshot_checksum, terminology_snapshot_checksum)
    ordered_gold = tuple(sorted(gold, key=lambda item: (item.sample_id, item.entity_id)))
    ordered_outputs = {
        variant: tuple(
            prediction
            for _, prediction in sorted(
                zip(gold, variant_outputs[variant]),
                key=lambda item: (item[0].sample_id, item[0].entity_id),
            )
        )
        for variant in _REQUIRED_VARIANTS
    }
    variants = {
        variant: _metrics(ordered_gold, ordered_outputs[variant], variant == "reranked")
        for variant in _REQUIRED_VARIANTS
    }
    by_type = _group_metrics(ordered_gold, ordered_outputs, lambda item: item.entity_type)
    by_terminology = _group_metrics(ordered_gold, ordered_outputs, lambda item: item.terminology)
    errors = _error_buckets(ordered_gold, ordered_outputs)
    return LinkingEvaluationReport(
        gold_snapshot_checksum,
        terminology_snapshot_checksum,
        variants,
        by_type,
        by_terminology,
        errors,
    )


def _validate_inputs(
    gold: tuple[FrozenLinkingGold, ...],
    outputs: Mapping[str, tuple[LinkingVariantPrediction, ...]],
    gold_checksum: str,
    terminology_checksum: str,
) -> None:
    if set(outputs) != set(_REQUIRED_VARIANTS):
        raise ValueError("variant outputs must contain lexical, dense, fused, and reranked only")
    if len({item.trace_id for item in gold}) != len(gold):
        raise ValueError("duplicate sample/entity IDs are not allowed")
    if any(item.gold_snapshot_checksum != gold_checksum for item in gold):
        raise ValueError("gold snapshot checksum does not match evaluation input")
    if any(item.terminology_snapshot_checksum != terminology_checksum for item in gold):
        raise ValueError("terminology snapshot checksum does not match evaluation input")
    if any(len(outputs[variant]) != len(gold) for variant in _REQUIRED_VARIANTS):
        raise ValueError("each variant must provide one prediction per frozen gold entity")


def _group_metrics(
    gold: tuple[FrozenLinkingGold, ...],
    outputs: Mapping[str, tuple[LinkingVariantPrediction, ...]],
    key: Callable[[FrozenLinkingGold], str],
) -> Mapping[str, Mapping[str, LinkingVariantMetrics]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(gold):
        groups[key(item)].append(index)
    return {
        name: {
            variant: _metrics(
                tuple(gold[index] for index in indexes),
                tuple(outputs[variant][index] for index in indexes),
                variant == "reranked",
            )
            for variant in _REQUIRED_VARIANTS
        }
        for name, indexes in sorted(groups.items())
    }


def _metrics(
    gold: tuple[FrozenLinkingGold, ...],
    predictions: tuple[LinkingVariantPrediction, ...],
    is_reranked: bool,
) -> LinkingVariantMetrics:
    count = len(gold)
    if not count:
        return LinkingVariantMetrics(
            0, 0.0, {k: 0.0 for k in _RECALL_KS}, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, ()
        )
    exact = 0
    recalls = {k: 0 for k in _RECALL_KS}
    reciprocal_ranks: list[float] = []
    oracle: list[float] = []
    reranker_hits = 0
    reranker_denominator = 0
    jaccards: list[float] = []
    abstentions = 0
    correct_abstentions = 0
    for item, prediction in zip(gold, predictions):
        gold_keys = _gold_keys(item)
        ranked = tuple(_candidate_key(candidate) for candidate in prediction.ranked_candidates)
        pool = set(ranked)
        covered = gold_keys.issubset(pool)
        exact += int(covered)
        for k in _RECALL_KS:
            recalls[k] += int(gold_keys.issubset(set(ranked[:k])))
        first_rank = next(
            (index + 1 for index, candidate in enumerate(ranked) if candidate in gold_keys), None
        )
        reciprocal_ranks.append(0.0 if first_rank is None else 1.0 / first_rank)
        oracle.append(1.0 if covered else 0.0)
        if is_reranked and gold_keys:
            reranker_denominator += 1
            reranker_hits += int(bool(ranked) and ranked[0] in gold_keys)
        final = {_candidate_key(candidate) for candidate in prediction.final_candidates}
        jaccards.append(_jaccard(final, gold_keys))
        if not final:
            abstentions += 1
            correct_abstentions += int(not gold_keys)
    return LinkingVariantMetrics(
        count,
        exact / count,
        {k: recalls[k] / count for k in _RECALL_KS},
        sum(reciprocal_ranks) / count,
        sum(oracle) / count,
        reranker_hits / reranker_denominator if reranker_denominator else 0.0,
        sum(jaccards) / count,
        correct_abstentions / abstentions if abstentions else 0.0,
        abstentions / count,
        tuple(item.trace_id for item in gold),
    )


def _error_buckets(
    gold: tuple[FrozenLinkingGold, ...],
    outputs: Mapping[str, tuple[LinkingVariantPrediction, ...]],
) -> Mapping[str, tuple[str, ...]]:
    buckets: dict[str, set[str]] = defaultdict(set)
    for index, item in enumerate(gold):
        trace = item.trace_id
        gold_keys = _gold_keys(item)
        fused = outputs["fused"][index]
        reranked = outputs["reranked"][index]
        fused_pool = {_candidate_key(candidate) for candidate in fused.ranked_candidates}
        reranked_final = {_candidate_key(candidate) for candidate in reranked.final_candidates}
        if not item.alias_present:
            buckets["alias_missing"].add(trace)
        if gold_keys and not gold_keys.issubset(fused_pool):
            buckets["retrieval_miss"].add(trace)
        if gold_keys and gold_keys.issubset(fused_pool) and not gold_keys.issubset(reranked_final):
            buckets["rerank_miss"].add(trace)
        if item.granularity is not None and any(
            _candidate_key(candidate) in gold_keys
            and candidate.granularity is not None
            and candidate.granularity != item.granularity
            for candidate in reranked.ranked_candidates
        ):
            buckets["wrong_granularity"].add(trace)
        if gold_keys.intersection(
            {_candidate_key(candidate) for candidate in reranked.structured_rejected_candidates}
        ):
            buckets["structured_mismatch"].add(trace)
        if any(
            candidate.obsolete
            for candidate in reranked.ranked_candidates
            if _candidate_key(candidate) in reranked_final
        ):
            buckets["obsolete_concept"].add(trace)
        if len(gold_keys) > 1:
            buckets["ambiguous_gold"].add(trace)
    return MappingProxyType({name: tuple(sorted(buckets[name])) for name in _ERROR_BUCKETS})


def _deduplicate_ranked(
    candidates: tuple[CandidatePrediction, ...],
) -> tuple[CandidatePrediction, ...]:
    unique: dict[tuple[str, str], CandidatePrediction] = {}
    for candidate in candidates:
        unique.setdefault((candidate.terminology, candidate.concept_id), candidate)
    return tuple(unique.values())


def _gold_keys(item: FrozenLinkingGold) -> set[CandidateKey]:
    return {(item.terminology, concept_id) for concept_id in item.gold_concept_ids}


def _candidate_key(candidate: CandidatePrediction) -> CandidateKey:
    return candidate.terminology, candidate.concept_id


def _jaccard(left: set[CandidateKey], right: set[CandidateKey]) -> float:
    return len(left & right) / len(left | right) if left or right else 1.0
