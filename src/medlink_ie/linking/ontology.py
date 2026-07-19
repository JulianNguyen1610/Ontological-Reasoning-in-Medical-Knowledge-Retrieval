"""Gated, snapshot-only ontology features for candidate reranking."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from medlink_ie.domain import EntityType
from medlink_ie.linking.candidate_fusion import FusedCandidate, StructuredFeatures


class OntologyMode(str, Enum):
    OFF = "off"
    ALWAYS_ON = "always_on"
    GATED = "gated"


@dataclass(frozen=True, slots=True)
class GateConfig:
    max_simple_candidates: int
    minimum_simple_margin: float
    maximum_simple_aliases: int
    maximum_simple_uncertainty: float

    def __post_init__(self) -> None:
        if self.max_simple_candidates < 1 or self.maximum_simple_aliases < 1:
            raise ValueError("gate counts must be positive")
        if (
            not 0.0 <= self.minimum_simple_margin <= 1.0
            or not 0.0 <= self.maximum_simple_uncertainty <= 1.0
        ):
            raise ValueError("gate probability thresholds must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ScoreAdjustments:
    compatible_type_bonus: float
    hierarchy_conflict_penalty: float
    medication_match_bonus: float
    medication_mismatch_penalty: float
    hard_medication_ingredient_match: bool

    def __post_init__(self) -> None:
        if any(value < 0.0 for value in self._numeric_values()):
            raise ValueError("ontology adjustment magnitudes must be non-negative")

    def _numeric_values(self) -> tuple[float, ...]:
        return (
            self.compatible_type_bonus,
            self.hierarchy_conflict_penalty,
            self.medication_match_bonus,
            self.medication_mismatch_penalty,
        )


@dataclass(frozen=True, slots=True)
class OntologyRerankerConfig:
    enabled: bool
    mode: OntologyMode | str
    gate: GateConfig
    adjustments: ScoreAdjustments

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", OntologyMode(self.mode))
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")


@dataclass(frozen=True, slots=True)
class OntologyConcept:
    terminology: str
    concept_id: str
    parents: tuple[str, ...] = ()
    siblings: tuple[str, ...] = ()
    ingredient: str | None = None
    strength: str | None = None
    dose_form: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parents", tuple(self.parents))
        object.__setattr__(self, "siblings", tuple(self.siblings))
        if not self.terminology or not self.concept_id:
            raise ValueError("ontology concepts require terminology and concept_id")


@dataclass(frozen=True, slots=True)
class OntologySnapshot:
    concepts: Mapping[tuple[str, str], OntologyConcept]

    def __post_init__(self) -> None:
        concepts = dict(self.concepts)
        if any(
            key != (concept.terminology, concept.concept_id) for key, concept in concepts.items()
        ):
            raise ValueError("snapshot keys must match concept identities")
        object.__setattr__(self, "concepts", MappingProxyType(concepts))


@dataclass(frozen=True, slots=True)
class OntologyRequest:
    entity_type: EntityType
    candidates: tuple[FusedCandidate, ...]
    exact_match: bool
    alias_ambiguity: int
    hierarchy_conflict: bool
    structured_features: StructuredFeatures
    model_uncertainty: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        if not isinstance(self.entity_type, EntityType):
            raise TypeError("entity_type must be EntityType")
        if any(not isinstance(candidate, FusedCandidate) for candidate in self.candidates):
            raise TypeError("candidates must contain FusedCandidate values")
        if self.alias_ambiguity < 1 or not 0.0 <= self.model_uncertainty <= 1.0:
            raise ValueError("invalid ontology gate inputs")


@dataclass(frozen=True, slots=True)
class ScoreAdjustmentTrace:
    terminology: str
    concept_id: str
    delta: float
    reason: str


@dataclass(frozen=True, slots=True)
class OntologyRerankResult:
    candidates: tuple[FusedCandidate, ...]
    adjustments: tuple[ScoreAdjustmentTrace, ...]
    applied: bool
    gate_reason: str


class OntologyReranker:
    """Pure snapshot-only candidate adjustment with a no-ontology fallback."""

    def __init__(self, snapshot: OntologySnapshot, config: OntologyRerankerConfig) -> None:
        self.snapshot = snapshot
        self.config = config

    def rerank(self, request: OntologyRequest) -> OntologyRerankResult:
        _validate_snapshot_candidates(request.candidates, self.snapshot)
        gate_reason = self._gate_reason(request)
        if not self.config.enabled or self.config.mode is OntologyMode.OFF:
            return OntologyRerankResult(request.candidates, (), False, "feature_disabled")
        if self.config.mode is OntologyMode.GATED and gate_reason is not None:
            return OntologyRerankResult(request.candidates, (), False, gate_reason)
        traces: list[ScoreAdjustmentTrace] = []
        scored: list[FusedCandidate] = []
        for candidate in request.candidates:
            concept = self.snapshot.concepts[(candidate.terminology, candidate.concept_id)]
            adjusted, candidate_traces = _adjust(
                candidate, concept, request, self.config.adjustments
            )
            traces.extend(candidate_traces)
            if adjusted is not None:
                scored.append(adjusted)
        return OntologyRerankResult(
            tuple(
                sorted(
                    scored, key=lambda item: (-item.fused_score, item.terminology, item.concept_id)
                )
            ),
            tuple(traces),
            True,
            "always_on" if self.config.mode is OntologyMode.ALWAYS_ON else "gated_on",
        )

    def _gate_reason(self, request: OntologyRequest) -> str | None:
        if request.exact_match and len(request.candidates) == 1:
            return "unique_exact_match"
        if (
            len(request.candidates) <= self.config.gate.max_simple_candidates
            and request.alias_ambiguity <= self.config.gate.maximum_simple_aliases
            and _margin(request.candidates) >= self.config.gate.minimum_simple_margin
            and not request.hierarchy_conflict
            and request.model_uncertainty <= self.config.gate.maximum_simple_uncertainty
            and request.structured_features.kind != "medication"
        ):
            return "high_margin_simple_case"
        return None


def _validate_snapshot_candidates(
    candidates: tuple[FusedCandidate, ...], snapshot: OntologySnapshot
) -> None:
    if any((item.terminology, item.concept_id) not in snapshot.concepts for item in candidates):
        raise ValueError("ontology reranking accepts only candidates in the terminology snapshot")


def _adjust(
    candidate: FusedCandidate,
    concept: OntologyConcept,
    request: OntologyRequest,
    config: ScoreAdjustments,
) -> tuple[FusedCandidate | None, tuple[ScoreAdjustmentTrace, ...]]:
    traces: list[ScoreAdjustmentTrace] = []
    if not _compatible(request.entity_type, candidate.terminology):
        return None, (
            ScoreAdjustmentTrace(
                candidate.terminology, candidate.concept_id, 0.0, "hard_type_incompatible"
            ),
        )
    delta = config.compatible_type_bonus
    traces.append(
        ScoreAdjustmentTrace(candidate.terminology, candidate.concept_id, delta, "type_compatible")
    )
    if request.hierarchy_conflict:
        delta -= config.hierarchy_conflict_penalty
        traces.append(
            ScoreAdjustmentTrace(
                candidate.terminology,
                candidate.concept_id,
                -config.hierarchy_conflict_penalty,
                "hierarchy_conflict",
            )
        )
    if request.entity_type is EntityType.MEDICATION:
        medication_delta, medication_trace, hard_reject = _medication_adjustment(
            candidate, concept, request.structured_features, config
        )
        if hard_reject:
            return None, (medication_trace,)
        delta += medication_delta
        if medication_trace.delta:
            traces.append(medication_trace)
    return (
        FusedCandidate(
            candidate.terminology,
            candidate.concept_id,
            candidate.channel_scores,
            candidate.fused_score + delta,
            candidate.source_evidence,
            candidate.metadata,
        ),
        tuple(traces),
    )


def _medication_adjustment(
    candidate: FusedCandidate,
    concept: OntologyConcept,
    features: StructuredFeatures,
    config: ScoreAdjustments,
) -> tuple[float, ScoreAdjustmentTrace, bool]:
    ingredient = features.values.get("ingredient", ())
    strength = features.values.get("strength", ())
    dose_form = features.values.get("dose_form", ())
    if ingredient and concept.ingredient not in ingredient:
        trace = ScoreAdjustmentTrace(
            candidate.terminology, candidate.concept_id, 0.0, "hard_ingredient_mismatch"
        )
        if config.hard_medication_ingredient_match:
            return 0.0, trace, True
        return (
            -config.medication_mismatch_penalty,
            replace(trace, delta=-config.medication_mismatch_penalty),
            False,
        )
    values = (
        (ingredient, concept.ingredient),
        (strength, concept.strength),
        (dose_form, concept.dose_form),
    )
    if any(expected and observed in expected for expected, observed in values):
        return (
            config.medication_match_bonus,
            ScoreAdjustmentTrace(
                candidate.terminology,
                candidate.concept_id,
                config.medication_match_bonus,
                "medication_feature_match",
            ),
            False,
        )
    return (
        0.0,
        ScoreAdjustmentTrace(
            candidate.terminology, candidate.concept_id, 0.0, "no_medication_feature"
        ),
        False,
    )


def _compatible(entity_type: EntityType, terminology: str) -> bool:
    return (
        (entity_type is EntityType.DIAGNOSIS and terminology.startswith("ICD"))
        or (entity_type is EntityType.MEDICATION and terminology == "RxNorm")
        or entity_type not in {EntityType.DIAGNOSIS, EntityType.MEDICATION}
    )


def _margin(candidates: tuple[FusedCandidate, ...]) -> float:
    scores = sorted((candidate.fused_score for candidate in candidates), reverse=True)
    return scores[0] - scores[1] if len(scores) > 1 else 1.0
