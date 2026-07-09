import json

from data_generation.generators.note_labeler import NoteLabeler


class MockTeacherLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def call_text_gen(self, prompt, system_prompt="", temperature=0.7, max_tokens=500):
        self.calls.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.response


def test_parse_provenance_correctly():
    note = "BN đau ngực."
    response = json.dumps(
        {
            "entities": [
                {
                    "text": "đau ngực",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": [],
                    "candidates": [],
                    "confidence": 0.83,
                    "rationale_short": "triệu chứng chính",
                }
            ]
        },
        ensure_ascii=False,
    )
    labeler = NoteLabeler(MockTeacherLLM(response))

    result = labeler.label_note(
        note,
        metadata={
            "source_id": "public_001",
            "source_type": "public_note",
            "teacher_model": "gpt-teacher",
            "prompt_version": "v1",
        },
    )

    assert result["label_provenance"]["source_id"] == "public_001"
    assert result["label_provenance"]["source_type"] == "public_note"
    assert result["label_provenance"]["teacher_model"] == "gpt-teacher"
    assert result["label_provenance"]["prompt_version"] == "v1"
    assert result["label_provenance"]["label_style"] == "weak_supervision"
    assert result["label_provenance"]["labeling_status"] == "success"
    assert result["label_provenance"]["teacher_parse_success"] is True


def test_confidence_is_preserved_on_entity():
    note = "BN đau ngực, Troponin I tăng."
    response = json.dumps(
        {
            "entities": [
                {
                    "text": "đau ngực",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": [],
                    "candidates": [],
                    "confidence": 0.83,
                    "rationale_short": "triệu chứng nêu rõ",
                },
                {
                    "text": "Troponin I",
                    "type": "TÊN_XÉT_NGHIỆM",
                    "assertions": [],
                    "candidates": [],
                    "confidence": "1.4",
                    "rationale_short": "xét nghiệm trực tiếp",
                },
            ]
        },
        ensure_ascii=False,
    )
    labeler = NoteLabeler(MockTeacherLLM(response))

    result = labeler.label_note(note)

    assert result["entities"][0]["teacher_confidence"] == 0.83
    assert result["entities"][0]["teacher_rationale_short"] == "triệu chứng nêu rõ"
    assert result["entities"][1]["teacher_confidence"] == 1.0


def test_invalid_confidence_does_not_crash():
    note = "BN đau ngực."
    response = json.dumps(
        {
            "entities": [
                {
                    "text": "đau ngực",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": [],
                    "candidates": [],
                    "confidence": "không rõ",
                    "rationale_short": "nêu trong note",
                }
            ]
        },
        ensure_ascii=False,
    )
    labeler = NoteLabeler(MockTeacherLLM(response))

    result = labeler.label_note(note)

    assert len(result["entities"]) == 1
    assert result["entities"][0]["teacher_confidence"] is None


def test_low_confidence_filtering_works():
    note = "BN đau ngực, Troponin I tăng."
    response = json.dumps(
        {
            "entities": [
                {
                    "text": "đau ngực",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": [],
                    "candidates": [],
                    "confidence": 0.3,
                    "rationale_short": "mơ hồ",
                },
                {
                    "text": "Troponin I",
                    "type": "TÊN_XÉT_NGHIỆM",
                    "assertions": [],
                    "candidates": [],
                    "confidence": 0.9,
                    "rationale_short": "trực tiếp",
                },
            ]
        },
        ensure_ascii=False,
    )
    labeler = NoteLabeler(MockTeacherLLM(response))

    result = labeler.label_note(note, min_confidence=0.5)

    assert len(result["entities"]) == 1
    assert result["entities"][0]["text"] == "Troponin I"
    assert result["label_provenance"]["dropped_low_confidence_entities"] == 1


def test_missing_entity_span_is_rejected():
    note = "BN đau ngực."
    response = json.dumps(
        {
            "entities": [
                {
                    "text": "đau ngực",
                    "type": "TRIỆU_CHỨNG",
                    "assertions": [],
                    "candidates": [],
                    "confidence": 0.9,
                    "rationale_short": "trực tiếp",
                },
                {
                    "text": "aspirin 81 mg",
                    "type": "THUỐC",
                    "assertions": [],
                    "candidates": [],
                    "confidence": 0.8,
                    "rationale_short": "suy luận",
                },
            ]
        },
        ensure_ascii=False,
    )
    labeler = NoteLabeler(MockTeacherLLM(response))

    result = labeler.label_note(note)

    assert len(result["entities"]) == 1
    assert result["entities"][0]["text"] == "đau ngực"


def test_malformed_json_from_teacher_is_handled_safely():
    note = "BN đau ngực."
    labeler = NoteLabeler(MockTeacherLLM("{not valid json"))

    result = labeler.label_note(note)

    assert result["entities"] == []
    assert result["generation_mode"] == "note_to_label"
    assert result["label_provenance"]["labeling_status"] == "teacher_parse_failed"
    assert result["label_provenance"]["teacher_parse_success"] is False


def test_teacher_empty_output_is_auditable():
    note = "BN ổn định."
    response = json.dumps({"entities": []}, ensure_ascii=False)
    labeler = NoteLabeler(MockTeacherLLM(response))

    result = labeler.label_note(note)

    assert result["entities"] == []
    assert result["label_provenance"]["labeling_status"] == "teacher_returned_no_entities"
    assert result["label_provenance"]["teacher_parse_success"] is True


def test_teacher_entities_dropped_after_validation_are_marked():
    note = "BN đau ngực."
    response = json.dumps(
        {
            "entities": [
                {
                    "text": "aspirin 81 mg",
                    "type": "THUỐC",
                    "assertions": [],
                    "candidates": [],
                    "confidence": 0.7,
                    "rationale_short": "hallucinated",
                }
            ]
        },
        ensure_ascii=False,
    )
    labeler = NoteLabeler(MockTeacherLLM(response))

    result = labeler.label_note(note)

    assert result["entities"] == []
    assert result["label_provenance"]["labeling_status"] == "no_valid_entities_after_validation"
