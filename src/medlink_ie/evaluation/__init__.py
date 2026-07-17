"""Deterministic local evaluation utilities."""

from .linking import (
    CandidatePrediction,
    FrozenLinkingGold,
    LinkingEvaluationReport,
    LinkingVariantPrediction,
    evaluate_linking,
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
    "CandidatePrediction",
    "FrozenLinkingGold",
    "LinkingEvaluationReport",
    "LinkingVariantPrediction",
    "PredictionEntity",
    "PredictionSample",
    "RunComparison",
    "RunManifest",
    "RetrievalEvaluation",
    "RetrievalGoldMention",
    "ScoreBreakdown",
    "ScoringConfig",
    "compare_runs",
    "evaluate_predictions",
    "evaluate_linking",
    "evaluate_retrieval",
    "score_entities",
    "write_reports",
]
