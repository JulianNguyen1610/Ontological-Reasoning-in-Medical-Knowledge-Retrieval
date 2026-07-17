"""Deterministic, configuration-driven fusion baseline for grounded proposals."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from medlink_ie.domain import (
    AssertionLabel,
    DecisionTrace,
    EntityHypothesis,
    EntityType,
    GroundedSpan,
    GroundingMethod,
    ProposalSource,
)
from medlink_ie.proposals.contract import ProposalContext, SpanProposal


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    """All tunable baseline policy values; no acceptance threshold is implicit."""

    min_cluster_support: float = 0.50
    min_overlap_ratio: float = 0.80
    min_boundary_agreement: float = 0.50
    min_type_confidence: float = 0.50
    min_type_margin: float = 0.05
    assertion_score: float = 0.90
    allow_nested: bool = True
    allow_partial_overlap: bool = False
    lab_assertion_hard_mask: bool = True
    grounding_weights: Mapping[GroundingMethod, float] = field(
        default_factory=lambda: {
            GroundingMethod.EXACT_RAW: 1.00,
            GroundingMethod.EXACT_VIEW: 0.90,
            GroundingMethod.CASE_INSENSITIVE: 0.80,
            GroundingMethod.TOKEN_ALIGNED: 0.70,
            GroundingMethod.FUZZY_RAW: 0.00,
        }
    )
    negation_cues: tuple[str, ...] = ("không", "phủ nhận", "không có")
    contrast_cues: tuple[str, ...] = ("nhưng", "tuy nhiên", "but", "however")
    family_cues: tuple[str, ...] = ("gia đình", "mẹ", "bố", "cha", "anh", "chị")
    historical_cues: tuple[str, ...] = ("tiền sử", "trước đây", "đã từng")

    def __post_init__(self) -> None:
        for name in (
            "min_cluster_support",
            "min_overlap_ratio",
            "min_boundary_agreement",
            "min_type_confidence",
            "min_type_margin",
            "assertion_score",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if set(self.grounding_weights) != set(GroundingMethod):
            raise ValueError("grounding_weights must cover every GroundingMethod")


@dataclass(frozen=True, slots=True)
class GroundedEvidence:
    proposal: SpanProposal
    grounded: GroundedSpan


@dataclass(frozen=True, slots=True)
class SpanCluster:
    start: int
    end: int
    members: tuple[GroundedEvidence, ...]
    trace: DecisionTrace


def _overlap(left: SpanCluster, right: SpanCluster) -> int:
    return max(0, min(left.end, right.end) - max(left.start, right.start))


def _ratio(left: SpanCluster, right: SpanCluster) -> float:
    overlap = _overlap(left, right)
    return overlap / min(left.end - left.start, right.end - right.start)


class SpanClusterer:
    def __init__(self, config: BaselineConfig = BaselineConfig()) -> None:
        self.config = config

    def cluster(self, evidence: tuple[GroundedEvidence, ...]) -> tuple[SpanCluster, ...]:
        """Cluster only exact spans or compatible high-overlap identical text."""
        ordered = sorted(
            evidence,
            key=lambda item: (
                item.grounded.raw_start,
                item.grounded.raw_end,
                item.proposal.proposal_id,
            ),
        )
        groups: list[list[GroundedEvidence]] = []
        for item in ordered:
            for group in groups:
                first = group[0].grounded
                same = (first.raw_start, first.raw_end) == (
                    item.grounded.raw_start,
                    item.grounded.raw_end,
                )
                overlap = max(
                    0,
                    min(first.raw_end, item.grounded.raw_end)
                    - max(first.raw_start, item.grounded.raw_start),
                )
                smaller = min(
                    first.raw_end - first.raw_start, item.grounded.raw_end - item.grounded.raw_start
                )
                compatible = (
                    overlap / smaller >= self.config.min_overlap_ratio
                    and first.text.casefold() == item.grounded.text.casefold()
                )
                if same or compatible:
                    group.append(item)
                    break
            else:
                groups.append([item])
        return tuple(
            SpanCluster(
                min(member.grounded.raw_start for member in group),
                max(member.grounded.raw_end for member in group),
                tuple(group),
                DecisionTrace(("cluster:kept:exact_or_compatible_overlap",)),
            )
            for group in groups
        )


class BoundaryResolver:
    def __init__(self, config: BaselineConfig) -> None:
        self.config = config

    def resolve(self, clusters: tuple[SpanCluster, ...]) -> tuple[SpanCluster, ...]:
        """Resolve conflicts deterministically without blindly unioning intervals."""
        chosen: list[SpanCluster] = []
        for cluster in sorted(
            clusters, key=lambda item: (-self._score(item), item.start, item.end)
        ):
            agreement = len({item.proposal.source for item in cluster.members}) / len(
                cluster.members
            )
            if (
                self._score(cluster) < self.config.min_cluster_support
                or agreement < self.config.min_boundary_agreement
            ):
                continue
            conflicts = [other for other in chosen if _overlap(cluster, other)]
            nested = any(
                (cluster.start <= other.start and other.end <= cluster.end)
                or (other.start <= cluster.start and cluster.end <= other.end)
                for other in conflicts
            )
            if conflicts and (
                not self.config.allow_nested
                or (not nested and not self.config.allow_partial_overlap)
            ):
                continue
            chosen.append(
                replace(
                    cluster,
                    trace=DecisionTrace(
                        cluster.trace.decisions + ("boundary:kept:threshold_and_overlap_policy",)
                    ),
                )
            )
        return tuple(sorted(chosen, key=lambda item: (item.start, item.end)))

    def _score(self, cluster: SpanCluster) -> float:
        values = [
            item.grounded.confidence
            * item.proposal.score
            * self.config.grounding_weights[item.grounded.method]
            for item in cluster.members
        ]
        return sum(values) / len(values)


class HeuristicTypeClassifier:
    def __init__(self, config: BaselineConfig = BaselineConfig()) -> None:
        self.config = config

    def classify(
        self, clusters: tuple[SpanCluster, ...], context: ProposalContext
    ) -> tuple[EntityHypothesis, ...]:
        hypotheses: list[EntityHypothesis] = []
        for cluster in clusters:
            scores = {kind: 0.0 for kind in EntityType}
            sources = {item.proposal.source for item in cluster.members}
            for item in cluster.members:
                trust = context.source_trust.trust_for(item.proposal.source).weight
                weight = (
                    trust
                    * item.proposal.score
                    * self.config.grounding_weights[item.grounded.method]
                )
                meta = item.proposal.evidence[0].metadata if item.proposal.evidence else {}
                distribution = meta.get("provisional_type_distribution", {})
                for label, value in distribution.items():
                    target = {"symptom": EntityType.SYMPTOM, "diagnosis": EntityType.DIAGNOSIS}.get(
                        label
                    )
                    if target is not None:
                        scores[target] += weight * float(value)
                kind = meta.get("proposal_kind")
                if kind == "test_name":
                    scores[EntityType.TEST_NAME] += weight
                if kind == "test_result":
                    scores[EntityType.TEST_RESULT] += weight
                if item.proposal.source is ProposalSource.MEDICATION_RULES:
                    scores[EntityType.MEDICATION] += weight
                if meta.get("dictionary_evidence"):
                    scores[EntityType.DIAGNOSIS] += weight
            total = sum(scores.values()) or 1.0
            probabilities = {kind: score / total for kind, score in scores.items()}
            best, second = sorted(probabilities.values(), reverse=True)[:2]
            if (
                best < self.config.min_type_confidence
                or best - second < self.config.min_type_margin
            ):
                continue
            trace = DecisionTrace(
                cluster.trace.decisions + (f"type:kept:best={best:.3f}:margin={best - second:.3f}",)
            )
            hypotheses.append(
                EntityHypothesis(
                    cluster.start,
                    cluster.end,
                    context.document.raw_text[cluster.start : cluster.end],
                    tuple(sorted(sources, key=lambda source: source.value)),
                    {
                        source: max(
                            item.grounded.confidence
                            for item in cluster.members
                            if item.proposal.source is source
                        )
                        for source in sources
                    },
                    probabilities,
                    {},
                    {
                        "independent_sources": len(sources),
                        "boundary_agreement": len(sources) / len(cluster.members),
                    },
                    (),
                    trace,
                )
            )
        return tuple(hypotheses)


class BasicAssertionEngine:
    def __init__(self, config: BaselineConfig) -> None:
        self.config = config

    def apply(
        self, hypotheses: tuple[EntityHypothesis, ...], context: ProposalContext
    ) -> tuple[EntityHypothesis, ...]:
        output: list[EntityHypothesis] = []
        for hypothesis in hypotheses:
            scope, section_label = self._scope(context, hypothesis.raw_start)
            probabilities = {label: 0.0 for label in AssertionLabel}
            if section_label == "family_history" or any(
                cue in scope for cue in self.config.family_cues
            ):
                probabilities[AssertionLabel.FAMILY] = self.config.assertion_score
            if section_label in {"medical_history", "medication_history"} or any(
                cue in scope for cue in self.config.historical_cues
            ):
                probabilities[AssertionLabel.HISTORICAL] = self.config.assertion_score
            local = self._after_last_contrast(scope)
            if any(cue in local for cue in self.config.negation_cues):
                probabilities[AssertionLabel.NEGATED] = self.config.assertion_score
            top_type = max(
                hypothesis.type_probabilities,
                key=lambda entity_type: hypothesis.type_probabilities[entity_type],
            )
            if self.config.lab_assertion_hard_mask and top_type in {
                EntityType.TEST_NAME,
                EntityType.TEST_RESULT,
            }:
                probabilities = {label: 0.0 for label in AssertionLabel}
                reason = "assertion:masked:lab_type"
            else:
                reason = "assertion:kept:cue_and_local_scope"
            output.append(
                replace(
                    hypothesis,
                    assertion_probabilities=probabilities,
                    decision_trace=DecisionTrace(
                        hypothesis.decision_trace.decisions + ("assertion_scoped", reason)
                    ),
                )
            )
        return tuple(output)

    def _scope(self, context: ProposalContext, start: int) -> tuple[str, str | None]:
        text = context.document.raw_text
        clause = next(
            (
                item
                for item in (context.structure.clauses if context.structure else ())
                if item.start <= start < item.end
            ),
            None,
        )
        section = next(
            (
                item
                for item in (context.structure.sections if context.structure else ())
                if item.start <= start < item.end
            ),
            None,
        )
        left = clause.start if clause else text.rfind("\n", 0, start) + 1
        return text[left:start].casefold(), section.label if section else None

    def _after_last_contrast(self, scope: str) -> str:
        positions = [scope.rfind(cue) for cue in self.config.contrast_cues]
        return scope[max(positions) + 1 :] if max(positions) >= 0 else scope
