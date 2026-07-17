"""Deterministic candidate fusion, compatibility checks, selection, and negatives."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

CandidateKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class FusionConfig:
    """Calibrated local channel weights and candidate-set selection threshold."""

    weights: Mapping[str, float]
    minimum_confidence: float
    artifact_checksum: str

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("weights must not be empty")
        normalized = dict(self.weights)
        if any(
            not key or not math.isfinite(value) or value < 0 for key, value in normalized.items()
        ):
            raise ValueError("weights must be finite non-negative values")
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between zero and one")
        if not self.artifact_checksum:
            raise ValueError("artifact_checksum must be non-empty")
        object.__setattr__(self, "weights", MappingProxyType(normalized))

    @classmethod
    def load(cls, path: str | Path) -> "FusionConfig":
        """Load a local JSON configuration and bind behavior to its checksum."""
        artifact_path = Path(path)
        payload_bytes = artifact_path.read_bytes()
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported fusion config schema_version")
        weights = payload.get("weights")
        threshold = payload.get("minimum_confidence")
        if not isinstance(weights, dict) or not isinstance(threshold, (int, float)):
            raise TypeError("fusion config must contain weights and minimum_confidence")
        return cls(
            {str(key): float(value) for key, value in weights.items()},
            float(threshold),
            sha256(payload_bytes).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class StructuredFeatures:
    """Explicit mention-derived features; assertion labels are intentionally non-filtering."""

    kind: str
    values: Mapping[str, tuple[str, ...] | list[str]]
    assertion_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"", "medication", "laboratory"}:
            raise ValueError("kind must be medication, laboratory, or empty")
        normalized = {
            key: tuple(_normalize(value) for value in raw_values)
            for key, raw_values in self.values.items()
        }
        object.__setattr__(self, "values", MappingProxyType(normalized))
        object.__setattr__(self, "assertion_labels", tuple(self.assertion_labels))

    @classmethod
    def empty(cls) -> "StructuredFeatures":
        return cls("", {})


@dataclass(frozen=True, slots=True)
class CandidateInput:
    """One canonical-table candidate and uncombined retrieval evidence."""

    terminology: str
    concept_id: str
    channel_scores: Mapping[str, float]
    metadata: Mapping[str, Any]
    source_evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.terminology or not self.concept_id:
            raise ValueError("terminology and concept_id must be non-empty")
        scores = dict(self.channel_scores)
        if any(not math.isfinite(score) for score in scores.values()):
            raise ValueError("channel scores must be finite")
        object.__setattr__(self, "channel_scores", MappingProxyType(scores))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "source_evidence", tuple(sorted(set(self.source_evidence))))


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    terminology: str
    concept_id: str
    channel_scores: Mapping[str, float]
    fused_score: float
    source_evidence: tuple[str, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel_scores", MappingProxyType(dict(self.channel_scores)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    terminology: str
    concept_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    candidates: tuple[FusedCandidate, ...]
    ranked_candidates: tuple[FusedCandidate, ...]
    rejected: tuple[RejectedCandidate, ...]
    utility: float
    config_checksum: str


@dataclass(frozen=True, slots=True)
class CandidateSetOracleObservation:
    """One privacy-safe gold comparison for candidate-pool and final-set analysis."""

    sample_id: str
    gold_candidates: tuple[CandidateKey, ...]
    selection: CandidateSelection

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("sample_id must be non-empty")
        if any(not system or not concept_id for system, concept_id in self.gold_candidates):
            raise ValueError("gold candidate identities must be non-empty")
        if len(set(self.gold_candidates)) != len(self.gold_candidates):
            raise ValueError("gold candidate identities must be unique")


@dataclass(frozen=True, slots=True)
class CandidateSetOracleAnalysis:
    """Aggregate retrieval-oracle and final candidate-set quality on frozen gold."""

    sample_count: int
    retrieval_oracle_recall: float
    final_candidate_jaccard: float
    exact_set_rate: float


def fuse_and_select(
    candidates: tuple[CandidateInput, ...],
    config: FusionConfig,
    structured: StructuredFeatures,
) -> CandidateSelection:
    """Fuse preserved evidence, explicitly filter incompatible candidates, then select a set."""
    deduplicated = _deduplicate(candidates)
    accepted: list[FusedCandidate] = []
    rejected: list[RejectedCandidate] = []
    for candidate in deduplicated:
        reason = _compatibility_rejection(candidate, structured)
        if reason is not None:
            rejected.append(RejectedCandidate(candidate.terminology, candidate.concept_id, reason))
            continue
        accepted.append(
            FusedCandidate(
                candidate.terminology,
                candidate.concept_id,
                candidate.channel_scores,
                _fuse(candidate.channel_scores, config),
                candidate.source_evidence,
                candidate.metadata,
            )
        )
    ordered = tuple(
        sorted(accepted, key=lambda item: (-item.fused_score, item.terminology, item.concept_id))
    )
    if not ordered or ordered[0].fused_score < config.minimum_confidence:
        return CandidateSelection(
            (), (), tuple(sorted(rejected, key=_rejected_key)), 0.0, config.artifact_checksum
        )
    selection, utility = _select_expected_jaccard(ordered)
    return CandidateSelection(
        selection,
        ordered,
        tuple(sorted(rejected, key=_rejected_key)),
        utility,
        config.artifact_checksum,
    )


def generate_hard_negatives(
    gold_candidates: tuple[CandidateKey, ...],
    catalog: tuple[CandidateInput, ...],
) -> tuple[CandidateInput, ...]:
    """Generate canonical-table ICD hierarchy and RxNorm ingredient/form/strength negatives."""
    gold_keys = set(gold_candidates)
    gold = [candidate for candidate in catalog if _candidate_key(candidate) in gold_keys]
    negatives: dict[tuple[str, str], CandidateInput] = {}
    for candidate in catalog:
        if _candidate_key(candidate) in gold_keys:
            continue
        if any(_is_hard_negative(candidate, positive) for positive in gold):
            negatives[(candidate.terminology, candidate.concept_id)] = candidate
    return tuple(sorted(negatives.values(), key=lambda item: (item.terminology, item.concept_id)))


def evaluate_candidate_set_oracle(
    observations: tuple[CandidateSetOracleObservation, ...],
) -> CandidateSetOracleAnalysis:
    """Report pool coverage separately from selected-set Jaccard using frozen gold identities."""
    if not observations:
        return CandidateSetOracleAnalysis(0, 0.0, 0.0, 0.0)
    oracle_recalls: list[float] = []
    jaccards: list[float] = []
    exact_matches = 0
    for observation in observations:
        gold = set(observation.gold_candidates)
        pool = {_candidate_key(item) for item in observation.selection.ranked_candidates}
        final = {_candidate_key(item) for item in observation.selection.candidates}
        oracle_recalls.append(1.0 if not gold else len(gold & pool) / len(gold))
        union = gold | final
        jaccard = 1.0 if not union else len(gold & final) / len(union)
        jaccards.append(jaccard)
        exact_matches += int(gold == final)
    count = len(observations)
    return CandidateSetOracleAnalysis(
        count,
        sum(oracle_recalls) / count,
        sum(jaccards) / count,
        exact_matches / count,
    )


def _deduplicate(candidates: tuple[CandidateInput, ...]) -> tuple[CandidateInput, ...]:
    merged: dict[tuple[str, str], CandidateInput] = {}
    for candidate in sorted(candidates, key=lambda item: (item.terminology, item.concept_id)):
        key = candidate.terminology, candidate.concept_id
        prior = merged.get(key)
        if prior is None:
            merged[key] = candidate
            continue
        scores = {
            channel: max(
                prior.channel_scores.get(channel, float("-inf")),
                candidate.channel_scores.get(channel, float("-inf")),
            )
            for channel in prior.channel_scores.keys() | candidate.channel_scores.keys()
        }
        metadata = dict(prior.metadata)
        metadata.update(candidate.metadata)
        merged[key] = CandidateInput(
            candidate.terminology,
            candidate.concept_id,
            scores,
            metadata,
            tuple(sorted(set(prior.source_evidence) | set(candidate.source_evidence))),
        )
    return tuple(merged.values())


def _compatibility_rejection(
    candidate: CandidateInput, structured: StructuredFeatures
) -> str | None:
    if structured.kind == "medication":
        for feature in ("ingredients", "strengths", "forms"):
            query_values = structured.values.get(feature, ())
            candidate_values = _metadata_values(candidate.metadata, feature)
            if (
                query_values
                and candidate_values
                and not set(query_values).issubset(candidate_values)
            ):
                return "explicit_" + feature + "_conflict"
    if structured.kind == "laboratory":
        for feature in ("test_names", "units"):
            query_values = structured.values.get(feature, ())
            candidate_values = _metadata_values(candidate.metadata, feature)
            if (
                query_values
                and candidate_values
                and not set(query_values).issubset(candidate_values)
            ):
                return "explicit_" + feature + "_conflict"
    return None


def _fuse(scores: Mapping[str, float], config: FusionConfig) -> float:
    return min(
        1.0,
        max(
            0.0, sum(config.weights.get(channel, 0.0) * score for channel, score in scores.items())
        ),
    )


def _select_expected_jaccard(
    candidates: tuple[FusedCandidate, ...],
) -> tuple[tuple[FusedCandidate, ...], float]:
    total_expected_relevant = sum(candidate.fused_score for candidate in candidates)
    best: tuple[FusedCandidate, ...] = ()
    best_utility = 0.0
    expected_intersection = 0.0
    for size, candidate in enumerate(candidates, start=1):
        expected_intersection += candidate.fused_score
        expected_union = total_expected_relevant + size - expected_intersection
        utility = expected_intersection / expected_union if expected_union else 0.0
        if utility > best_utility:
            best = candidates[:size]
            best_utility = utility
    return best, best_utility


def _is_hard_negative(candidate: CandidateInput, gold: CandidateInput) -> bool:
    if candidate.terminology != gold.terminology:
        return False
    if candidate.terminology.upper().startswith("ICD"):
        candidate_parent = candidate.metadata.get("parent_id")
        gold_parent = gold.metadata.get("parent_id")
        return (
            candidate_parent == gold.concept_id
            or gold_parent == candidate.concept_id
            or candidate_parent is not None
            and candidate_parent == gold_parent
        )
    if candidate.terminology.upper().startswith("RXNORM"):
        candidate_ingredients = _metadata_values(candidate.metadata, "ingredients")
        gold_ingredients = _metadata_values(gold.metadata, "ingredients")
        if not candidate_ingredients.intersection(gold_ingredients):
            return False
        return any(
            _metadata_values(candidate.metadata, field) != _metadata_values(gold.metadata, field)
            for field in ("ingredients", "strengths", "forms")
        )
    return False


def _metadata_values(metadata: Mapping[str, Any], field: str) -> set[str]:
    raw = metadata.get(field, ())
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, (tuple, list, set)):
        return set()
    return {_normalize(str(value)) for value in raw}


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _rejected_key(item: RejectedCandidate) -> tuple[str, str, str]:
    return item.terminology, item.concept_id, item.reason


def _candidate_key(candidate: CandidateInput | FusedCandidate) -> CandidateKey:
    return candidate.terminology, candidate.concept_id
