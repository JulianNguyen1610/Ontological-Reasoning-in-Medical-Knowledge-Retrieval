from medlink_ie.domain import GroundedSpan, GroundingMethod, ProposalSource, SourceDocument
from medlink_ie.fusion.baseline import (
    BaselineConfig,
    BasicAssertionEngine,
    BoundaryResolver,
    GroundedEvidence,
    HeuristicTypeClassifier,
    SpanClusterer,
)
from medlink_ie.normalization.text_views import build_text_views
from medlink_ie.proposals import ProposalContext, ProposalEvidence, SpanProposal
from medlink_ie.structure.analyzer import StructuralAnalyzer


def test_baseline_clusters_types_and_scopes_assertions():
    text = "Family history\nmẹ phủ nhận đau ngực nhưng tăng huyết áp."
    doc = SourceDocument("x", text.encode(), text, "utf-8", False, "none")
    ctx = ProposalContext(doc, build_text_views(doc), structure=StructuralAnalyzer().analyze(doc))
    s = text.index("đau ngực")
    p = SpanProposal.create(
        ctx,
        ProposalSource.CONCEPT_RULES,
        "x",
        "raw",
        s,
        s + 7,
        0.9,
        (
            ProposalEvidence(
                "rule_match", "x", "1", {"provisional_type_distribution": {"symptom": 0.9}}
            ),
        ),
    )
    g = GroundedSpan(p.proposal_id, s, s + 7, "đau ngực", GroundingMethod.EXACT_RAW, 1)
    clusters = BoundaryResolver(BaselineConfig()).resolve(
        SpanClusterer().cluster((GroundedEvidence(p, g),))
    )
    hyp = HeuristicTypeClassifier().classify(clusters, ctx)
    out = BasicAssertionEngine(BaselineConfig()).apply(hyp, ctx)[0]
    assert (
        out.type_probabilities
        and out.assertion_probabilities
        and "assertion_scoped" in out.decision_trace.decisions
    )
    assert out.structured_slots["assertion_decisions"]


def _evidence(ctx, text, source, metadata=None):
    start = ctx.document.raw_text.index(text)
    proposal = SpanProposal.create(
        ctx,
        source,
        "test",
        "raw",
        start,
        start + len(text),
        0.9,
        (ProposalEvidence("rule_match", "test", "1", metadata or {}),),
    )
    return GroundedEvidence(
        proposal,
        GroundedSpan(
            proposal.proposal_id, start, start + len(text), text, GroundingMethod.EXACT_RAW, 1.0
        ),
    )


def test_conflicts_same_span_and_nested_medication_are_deterministic():
    text = "amlodipine 5 mg đau ngực"
    doc = SourceDocument("x", text.encode(), text, "utf-8", False, "none")
    ctx = ProposalContext(doc, build_text_views(doc), structure=StructuralAnalyzer().analyze(doc))
    medication = _evidence(ctx, "amlodipine 5 mg", ProposalSource.MEDICATION_RULES)
    nested = _evidence(ctx, "5 mg", ProposalSource.SPAN_MODEL)
    symptom = _evidence(
        ctx,
        "đau ngực",
        ProposalSource.CONCEPT_RULES,
        {"provisional_type_distribution": {"symptom": 0.9}},
    )
    resolved = BoundaryResolver(BaselineConfig()).resolve(
        SpanClusterer().cluster((medication, nested, symptom))
    )
    assert [(cluster.start, cluster.end) for cluster in resolved] == sorted(
        (cluster.start, cluster.end) for cluster in resolved
    )
    typed = HeuristicTypeClassifier().classify(resolved, ctx)
    assert any(
        max(item.type_probabilities, key=item.type_probabilities.get).value == "THUỐC"
        for item in typed
    )


def test_contrast_family_history_and_lab_mask_are_scoped():
    text = "Tiền sử gia đình\nmẹ không đau ngực nhưng sốt. Glucose 5 mmol/L"
    doc = SourceDocument("x", text.encode(), text, "utf-8", False, "none")
    ctx = ProposalContext(doc, build_text_views(doc), structure=StructuralAnalyzer().analyze(doc))
    pain = _evidence(
        ctx,
        "đau ngực",
        ProposalSource.CONCEPT_RULES,
        {"provisional_type_distribution": {"symptom": 1.0}},
    )
    fever = _evidence(
        ctx,
        "sốt",
        ProposalSource.CONCEPT_RULES,
        {"provisional_type_distribution": {"symptom": 1.0}},
    )
    glucose = _evidence(ctx, "Glucose", ProposalSource.LAB_RULES, {"proposal_kind": "test_name"})
    clusters = BoundaryResolver(BaselineConfig()).resolve(
        SpanClusterer().cluster((pain, fever, glucose))
    )
    output = BasicAssertionEngine(BaselineConfig()).apply(
        HeuristicTypeClassifier().classify(clusters, ctx), ctx
    )
    by_text = {item.text: item for item in output}
    assert by_text["đau ngực"].assertion_probabilities
    assert (
        by_text["sốt"].assertion_probabilities.get(
            __import__("medlink_ie.domain", fromlist=["AssertionLabel"]).AssertionLabel.NEGATED
        )
        == 0.0
    )
    assert all(value == 0.0 for value in by_text["Glucose"].assertion_probabilities.values())


def test_same_interval_different_type_is_fused_not_duplicated():
    text = "đau"
    doc = SourceDocument("x", text.encode(), text, "utf-8", False, "none")
    ctx = ProposalContext(doc, build_text_views(doc), structure=StructuralAnalyzer().analyze(doc))
    symptom = _evidence(
        ctx,
        "đau",
        ProposalSource.CONCEPT_RULES,
        {"provisional_type_distribution": {"symptom": 1.0}},
    )
    diagnosis = _evidence(
        ctx, "đau", ProposalSource.SPAN_MODEL, {"provisional_type_distribution": {"diagnosis": 1.0}}
    )
    clusters = SpanClusterer().cluster((symptom, diagnosis))
    assert len(clusters) == 1
    hypothesis = HeuristicTypeClassifier(BaselineConfig(min_type_margin=0.0)).classify(
        clusters, ctx
    )[0]
    assert hypothesis.structured_slots["independent_sources"] == 2


def test_list_history_keeps_hypothesis_and_sets_historical_assertion():
    text = "Tiền sử bệnh\n1. đau ngực"
    doc = SourceDocument("x", text.encode(), text, "utf-8", False, "none")
    ctx = ProposalContext(doc, build_text_views(doc), structure=StructuralAnalyzer().analyze(doc))
    evidence = _evidence(
        ctx,
        "đau ngực",
        ProposalSource.CONCEPT_RULES,
        {"provisional_type_distribution": {"symptom": 1.0}},
    )
    clusters = BoundaryResolver(BaselineConfig()).resolve(SpanClusterer().cluster((evidence,)))
    result = BasicAssertionEngine(BaselineConfig()).apply(
        HeuristicTypeClassifier().classify(clusters, ctx), ctx
    )[0]
    historical = __import__(
        "medlink_ie.domain", fromlist=["AssertionLabel"]
    ).AssertionLabel.HISTORICAL
    assert result.assertion_probabilities[historical] > 0.0
    assert result.candidate_scores == ()
