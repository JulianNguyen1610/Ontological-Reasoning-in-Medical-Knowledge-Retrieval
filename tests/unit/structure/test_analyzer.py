from __future__ import annotations

from medlink_ie.domain import SourceDocument
from medlink_ie.structure.analyzer import StructuralAnalyzer


def _document(text: str) -> SourceDocument:
    return SourceDocument("note", text.encode("utf-8"), text, "utf-8", False, "none")


def _texts(text: str, units: object) -> list[str]:
    return [text[unit.start : unit.end] for unit in units]  # type: ignore[union-attr]


def _assert_raw_spans(text: str, structure: object) -> None:
    for units in (
        structure.sections,
        structure.list_blocks,
        structure.list_items,
        structure.sentences,
        structure.clauses,
    ):
        for unit in units:
            unit.validate(text)


def test_medication_history_becomes_section_and_newline_medication_list() -> None:
    text = "Thuốc trước nhập viện:\nAspirin 81 mg po daily\nMetformin 500 mg bid\n"
    structure = StructuralAnalyzer().analyze(_document(text))

    assert structure.sections[0].label == "medication_history"
    assert structure.list_blocks[0].rule_ids == ("list.medication_lines",)
    assert _texts(text, structure.list_items) == ["Aspirin 81 mg po daily", "Metformin 500 mg bid"]
    assert all(item.parent_list_id == structure.list_blocks[0].unit_id for item in structure.list_items)
    _assert_raw_spans(text, structure)


def test_lab_report_lines_remain_distinct_sentences_with_section_context() -> None:
    text = "Cận lâm sàng:\nGlucose: 5.6 mmol/L\nHbA1c: 6.2%\n"
    structure = StructuralAnalyzer().analyze(_document(text))

    assert structure.sections[0].label == "laboratory"
    assert _texts(text, structure.sentences) == ["Cận lâm sàng:", "Glucose: 5.6 mmol/L", "HbA1c: 6.2%"]
    assert all(sentence.parent_section_id == structure.sections[0].unit_id for sentence in structure.sentences)
    _assert_raw_spans(text, structure)


def test_numbered_and_bullet_lists_are_grouped_with_parent_child_links() -> None:
    text = "1. Aspirin\n2. Metformin\n\n- Không sốt\n• Ho nhiều\n"
    structure = StructuralAnalyzer().analyze(_document(text))

    assert len(structure.list_blocks) == 2
    assert [block.rule_ids for block in structure.list_blocks] == [
        ("list.numbered",),
        ("list.bullet",),
    ]
    assert _texts(text, structure.list_items) == ["1. Aspirin", "2. Metformin", "- Không sốt", "• Ho nhiều"]
    _assert_raw_spans(text, structure)


def test_abbreviations_decimals_and_dosage_colons_do_not_force_sentence_splits() -> None:
    text = "BS. kê amlodipine 5.5 mg q6h:prn. Nhiệt độ 37.5 C."
    structure = StructuralAnalyzer().analyze(_document(text))

    assert _texts(text, structure.sentences) == [
        "BS. kê amlodipine 5.5 mg q6h:prn.",
        "Nhiệt độ 37.5 C.",
    ]
    _assert_raw_spans(text, structure)


def test_contrast_clause_segmentation_keeps_cue_for_future_scope_logic() -> None:
    text = "Không sốt nhưng ho nhiều"
    structure = StructuralAnalyzer().analyze(_document(text))

    assert _texts(text, structure.clauses) == ["Không sốt ", "nhưng ho nhiều"]
    assert structure.clauses[1].cue == "nhưng"
    assert structure.clauses[1].rule_ids == ("clause.contrast.nhung",)
    assert all(clause.parent_sentence_id == structure.sentences[0].unit_id for clause in structure.clauses)
    _assert_raw_spans(text, structure)


def test_crlf_multiline_text_uses_raw_boundaries_without_translation() -> None:
    text = "Chẩn đoán:\r\n- Viêm phổi\r\n- Tăng huyết áp\r\n"
    structure = StructuralAnalyzer().analyze(_document(text))

    assert text[structure.sections[0].start : structure.sections[0].end] == text
    assert _texts(text, structure.list_items) == ["- Viêm phổi", "- Tăng huyết áp"]
    _assert_raw_spans(text, structure)


def test_empty_and_one_line_documents_are_valid() -> None:
    analyzer = StructuralAnalyzer()

    empty = analyzer.analyze(_document(""))
    one_line = analyzer.analyze(_document("Ho, sốt."))

    assert empty.sections == empty.list_blocks == empty.list_items == empty.sentences == empty.clauses == ()
    assert _texts("Ho, sốt.", one_line.sentences) == ["Ho, sốt."]
    _assert_raw_spans("Ho, sốt.", one_line)


def test_analysis_ordering_is_deterministic() -> None:
    document = _document("Khám hiện tại:\n- Ho\n- Sốt\n")
    analyzer = StructuralAnalyzer()

    assert analyzer.analyze(document).to_dict() == analyzer.analyze(document).to_dict()
