from __future__ import annotations

from medlink_ie.evaluation.linking import (
    CandidatePrediction,
    FrozenLinkingGold,
    LinkingVariantPrediction,
    evaluate_linking,
)


def _prediction(
    ranked: tuple[CandidatePrediction, ...],
    final: tuple[CandidatePrediction, ...],
    rejected: tuple[CandidatePrediction, ...] = (),
) -> LinkingVariantPrediction:
    return LinkingVariantPrediction(ranked, final, rejected)


def test_linking_report_variants_metrics_groups_and_diagnostics() -> None:
    gold = (
        FrozenLinkingGold(
            "s1",
            "e1",
            "THUOC",
            "RXNORM",
            ("r1",),
            "ingredient",
            "gold-v1",
            "term-v1",
            alias_present=True,
        ),
        FrozenLinkingGold(
            "s1",
            "e2",
            "CHAN_DOAN",
            "ICD-10",
            ("i1", "i2"),
            "category_3",
            "gold-v1",
            "term-v1",
            alias_present=False,
        ),
    )
    variants = {
        "lexical": (
            _prediction(
                (CandidatePrediction("RXNORM", "r1", "ingredient"),),
                (CandidatePrediction("RXNORM", "r1", "ingredient"),),
            ),
            _prediction((), ()),
        ),
        "dense": (
            _prediction(
                (CandidatePrediction("RXNORM", "r1", "ingredient"),),
                (CandidatePrediction("RXNORM", "r1", "ingredient"),),
            ),
            _prediction(
                (CandidatePrediction("ICD-10", "i1", "subcategory_4"),),
                (CandidatePrediction("ICD-10", "i1", "subcategory_4"),),
            ),
        ),
        "fused": (
            _prediction(
                (
                    CandidatePrediction("RXNORM", "wrong", "ingredient"),
                    CandidatePrediction("RXNORM", "r1", "ingredient"),
                ),
                (CandidatePrediction("RXNORM", "r1", "ingredient"),),
            ),
            _prediction(
                (
                    CandidatePrediction("ICD-10", "i1", "subcategory_4"),
                    CandidatePrediction("ICD-10", "i2", "subcategory_4"),
                    CandidatePrediction("ICD-10", "extra", "category_3"),
                ),
                (CandidatePrediction("ICD-10", "i1", "subcategory_4"),),
            ),
        ),
        "reranked": (
            _prediction(
                (
                    CandidatePrediction("RXNORM", "r1", "ingredient"),
                    CandidatePrediction("RXNORM", "wrong", "ingredient"),
                ),
                (CandidatePrediction("RXNORM", "r1", "ingredient"),),
            ),
            _prediction(
                (
                    CandidatePrediction("ICD-10", "i1", "subcategory_4"),
                    CandidatePrediction("ICD-10", "i2", "subcategory_4"),
                ),
                (CandidatePrediction("ICD-10", "i1", "subcategory_4"),),
                (CandidatePrediction("ICD-10", "i2", "subcategory_4"),),
            ),
        ),
    }
    report = evaluate_linking(gold, variants, "gold-v1", "term-v1")

    assert report.variants["lexical"].recall_at_k[1] == 0.5
    assert report.variants["fused"].recall_at_k[5] == 1.0
    assert report.variants["fused"].final_candidate_jaccard == 0.75
    assert report.variants["reranked"].reranker_top1_accuracy == 1.0
    assert report.error_buckets["alias_missing"] == ("s1:e2",)
    assert report.error_buckets["wrong_granularity"] == ("s1:e2",)
    assert report.error_buckets["rerank_miss"] == ("s1:e2",)
    assert report.error_buckets["structured_mismatch"] == ("s1:e2",)
    assert report.error_buckets["ambiguous_gold"] == ("s1:e2",)


def test_abstention_and_snapshot_validation_are_deterministic() -> None:
    gold = (
        FrozenLinkingGold(
            "s2", "e1", "THUOC", "RXNORM", (), None, "gold-v1", "term-v1", alias_present=True
        ),
    )
    variants = {name: (_prediction((), ()),) for name in ("lexical", "dense", "fused", "reranked")}
    report = evaluate_linking(gold, variants, "gold-v1", "term-v1")
    assert report.variants["fused"].abstention_precision == 1.0
    assert report.variants["fused"].abstention_coverage == 1.0

    try:
        evaluate_linking(gold, variants, "wrong", "term-v1")
    except ValueError as error:
        assert "gold snapshot" in str(error)
    else:
        raise AssertionError("expected frozen snapshot validation")


def test_candidate_identity_requires_matching_terminology() -> None:
    gold = (
        FrozenLinkingGold(
            "s3", "e1", "THUOC", "RXNORM", ("shared",), None, "gold-v1", "term-v1", True
        ),
    )
    wrong_system = CandidatePrediction("ICD-10", "shared", None)
    variants = {
        name: (_prediction((wrong_system,), (wrong_system,)),)
        for name in ("lexical", "dense", "fused", "reranked")
    }
    report = evaluate_linking(gold, variants, "gold-v1", "term-v1")
    assert report.variants["reranked"].recall_at_k[1] == 0.0
    assert report.variants["reranked"].final_candidate_jaccard == 0.0
    assert report.error_buckets["retrieval_miss"] == ("s3:e1",)
