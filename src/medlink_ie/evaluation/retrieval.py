"""Deterministic Recall@k evaluation for terminology candidate pools."""

from __future__ import annotations

from dataclasses import dataclass

from medlink_ie.terminology.retrieval import RetrievalResult


@dataclass(frozen=True, slots=True)
class RetrievalGoldMention:
    mention_id: str
    target_system: str
    target_concept_id: str
    results: tuple[RetrievalResult, ...]


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    mention_count: int
    recall_at_k: dict[int, float]
    missed_ids: tuple[str, ...]


def evaluate_retrieval(
    mentions: tuple[RetrievalGoldMention, ...], ks: tuple[int, ...] = (1, 2, 5)
) -> RetrievalEvaluation:
    """Report lexical Recall@k against positional gold mention identities."""
    if not mentions:
        return RetrievalEvaluation(0, {k: 0.0 for k in ks}, ())
    recalls: dict[int, float] = {}
    for k in ks:
        hits = sum(
            (item.target_system, item.target_concept_id)
            in {(result.system, result.concept_id) for result in item.results[:k]}
            for item in mentions
        )
        recalls[k] = hits / len(mentions)
    misses = tuple(
        item.mention_id
        for item in mentions
        if (item.target_system, item.target_concept_id)
        not in {(result.system, result.concept_id) for result in item.results}
    )
    return RetrievalEvaluation(len(mentions), recalls, misses)
