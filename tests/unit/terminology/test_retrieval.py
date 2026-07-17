from __future__ import annotations

from pathlib import Path

from medlink_ie.evaluation.retrieval import RetrievalGoldMention, evaluate_retrieval
from medlink_ie.terminology.clinical_filtering import retrieve_medication_candidates
from medlink_ie.terminology.preparation import AliasRecord, CanonicalTables, ConceptRecord
from medlink_ie.terminology.retrieval import (
    LexicalRetrievalConfig,
    RetrievalFilters,
    build_lexical_index,
    write_index_artifact,
)


def _tables(tmp_path: Path) -> CanonicalTables:
    concepts = (
        ConceptRecord("ICD-10", "D1", "Đau đầu", True, "category_3", None, tmp_path, 1, "v1"),
        ConceptRecord("ICD-10", "D2", "Headache", True, "category_3", None, tmp_path, 2, "v1"),
        ConceptRecord("RXNORM", "R1", "Metoprolol", True, "ingredient", "IN", tmp_path, 3, "v1"),
        ConceptRecord(
            "RXNORM", "R2", "Metoprolol succinate", True, "ingredient", "IN", tmp_path, 4, "v1"
        ),
        ConceptRecord(
            "RXNORM", "OLD", "Inactive drug", False, "ingredient", "IN", tmp_path, 5, "v1"
        ),
    )
    aliases = (
        AliasRecord("ICD-10", "D1", "Đau đầu", "preferred", tmp_path, 1, "v1"),
        AliasRecord("ICD-10", "D2", "đau đầu", "synonym", tmp_path, 2, "v1"),
        AliasRecord("RXNORM", "R1", "metoprolol", "preferred", tmp_path, 3, "v1"),
        AliasRecord("RXNORM", "R1", "metoprolol", "synonym", tmp_path, 4, "v1"),
        AliasRecord("RXNORM", "R2", "metoprolol-succinate", "preferred", tmp_path, 5, "v1"),
        AliasRecord("RXNORM", "OLD", "old drug", "preferred", tmp_path, 6, "v1"),
    )
    return CanonicalTables(concepts, aliases, (), (), {"schema_version": 1})


def test_exact_and_accentless_retrieval_keep_ambiguity_and_channel_scores(tmp_path: Path) -> None:
    index = build_lexical_index(_tables(tmp_path))

    exact = index.search("Đau đầu")
    assert [(result.system, result.concept_id) for result in exact] == [
        ("ICD-10", "D1"),
        ("ICD-10", "D2"),
    ]
    assert {evidence.channel for evidence in exact[0].evidence} == {
        "accentless_exact",
        "bm25",
        "exact_alias",
        "ngram",
    }

    accentless = index.search("dau dau")
    assert [(result.system, result.concept_id) for result in accentless] == [
        ("ICD-10", "D1"),
        ("ICD-10", "D2"),
    ]
    assert "accentless_exact" in {evidence.channel for evidence in accentless[0].evidence}


def test_punctuation_typos_filters_and_empty_query(tmp_path: Path) -> None:
    index = build_lexical_index(
        _tables(tmp_path),
        LexicalRetrievalConfig(ngram_min=2, ngram_max=4),
        {"diagnosis": ("ICD-10",), "medication": ("RXNORM",)},
    )

    hyphen_variant = index.search("metoprolol succinate")
    assert hyphen_variant[0].concept_id == "R2"
    typo = index.search("metoprolal")
    assert typo[0].concept_id == "R1"
    assert index.search("") == ()

    medication = index.search("metoprolol", RetrievalFilters(entity_types=("medication",)))
    assert {result.system for result in medication} == {"RXNORM"}
    wrong_type = index.search("metoprolol", RetrievalFilters(entity_types=("diagnosis",)))
    assert wrong_type == ()
    wrong_system = index.search("Đau đầu", RetrievalFilters(terminologies=("RXNORM",)))
    assert wrong_system == ()
    assert all(result.concept_id != "OLD" for result in index.search("old drug"))


def test_artifact_checksum_and_stable_tie_breaking(tmp_path: Path) -> None:
    index = build_lexical_index(_tables(tmp_path))
    first = index.search("dau dau")
    second = index.search("dau dau")
    assert first == second
    assert [result.concept_id for result in first] == ["D1", "D2"]

    artifact = write_index_artifact(index, tmp_path / "lexical_index.json")
    assert artifact.path.exists()
    assert len(artifact.checksum_sha256) == 64
    assert artifact.config["ngram_min"] == 3


def test_gold_recall_and_parser_slot_candidate_filtering(tmp_path: Path) -> None:
    index = build_lexical_index(
        _tables(tmp_path), type_to_terminologies={"medication": ("RXNORM",)}
    )
    parsed, results = retrieve_medication_candidates("metoprolol 25 mg XL", index)
    assert parsed.slots.ingredient_surface is not None
    assert [item.concept_id for item in results] == ["R1", "R2"]
    evaluation = evaluate_retrieval((RetrievalGoldMention("gold-1", "RXNORM", "R1", results),))
    assert evaluation.recall_at_k[1] == 1.0
    assert evaluation.missed_ids == ()
