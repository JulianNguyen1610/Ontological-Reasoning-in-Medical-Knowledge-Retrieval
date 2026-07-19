"""Deterministic local evaluation utilities."""

from .linking import (
    CandidatePrediction,
    FrozenLinkingGold,
    LinkingEvaluationReport,
    LinkingVariantPrediction,
    evaluate_linking,
)
from .ontology_ablation import (
    AblationCase,
    AblationConfig,
    MergeDecision,
    OntologyAblationReport,
    VariantMetrics,
    run_ontology_ablation,
)
from .reporting import (
    EvaluationReport,
    PredictionEntity,
    PredictionSample,
    RunComparison,
    RunManifest,
    compare_runs,
    evaluate_predictions,
    write_reports,
)
from .retrieval import RetrievalEvaluation, RetrievalGoldMention, evaluate_retrieval
from .scorer import ScoreBreakdown, ScoringConfig, score_entities

__all__ = [
    "EvaluationReport",
    "AblationCase",
    "AblationConfig",
    "CandidatePrediction",
    "FrozenLinkingGold",
    "LinkingEvaluationReport",
    "LinkingVariantPrediction",
    "MergeDecision",
    "OntologyAblationReport",
    "PredictionEntity",
    "PredictionSample",
    "RunComparison",
    "RunManifest",
    "RetrievalEvaluation",
    "RetrievalGoldMention",
    "ScoreBreakdown",
    "ScoringConfig",
    "VariantMetrics",
    "compare_runs",
    "evaluate_predictions",
    "evaluate_linking",
    "evaluate_retrieval",
    "score_entities",
    "run_ontology_ablation",
    "write_reports",
]
