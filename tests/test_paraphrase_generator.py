import json

from data_generation.generators.paraphrase_generator import ParaphraseGenerator


class MockLLMClient:
    def __init__(self, text_response: str):
        self.text_response = text_response
        self.prompts = []

    def call_text_gen(self, prompt, system_prompt="", temperature=0.7, max_tokens=500):
        self.prompts.append(
            {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self.text_response


def _build_sample():
    return {
        "text": "BN vào viện vì đau ngực, xét nghiệm Troponin I tăng. Chẩn đoán nhồi máu cơ tim cấp. Dùng aspirin 81 mg po daily.",
        "entities": [
            {
                "text": "đau ngực",
                "type": "TRIỆU_CHỨNG",
                "assertions": [],
                "candidates": [],
                "position": [16, 24],
            },
            {
                "text": "Troponin I",
                "type": "TÊN_XÉT_NGHIỆM",
                "assertions": [],
                "candidates": [],
                "position": [37, 47],
            },
            {
                "text": "tăng",
                "type": "KẾT_QUẢ_XÉT_NGHIỆM",
                "assertions": ["isHistorical"],
                "candidates": [],
                "position": [48, 52],
            },
            {
                "text": "nhồi máu cơ tim cấp",
                "type": "CHẨN_ĐOÁN",
                "assertions": [],
                "candidates": ["I21.9"],
                "position": [64, 83],
            },
            {
                "text": "aspirin 81 mg po daily",
                "type": "THUỐC",
                "assertions": [],
                "candidates": ["1191"],
                "position": [90, 113],
            },
        ],
        "scenario_id": "scenario_001",
    }


def test_strict_mode_keeps_literal_entity_text():
    response = json.dumps(
        {
            "note_rewritten": (
                "NB nhập viện do đau ngực. CLS ghi nhận Troponin I tăng. "
                "Tại viện chẩn đoán nhồi máu cơ tim cấp và cho aspirin 81 mg po daily."
            ),
            "entities_rewritten": [
                {"source_text": "đau ngực", "rewritten_text": "đau ngực", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
                {"source_text": "Troponin I", "rewritten_text": "Troponin I", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
                {"source_text": "tăng", "rewritten_text": "tăng", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": ["isHistorical"], "candidates": []},
                {"source_text": "nhồi máu cơ tim cấp", "rewritten_text": "nhồi máu cơ tim cấp", "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["I21.9"]},
                {"source_text": "aspirin 81 mg po daily", "rewritten_text": "aspirin 81 mg po daily", "type": "THUỐC", "assertions": [], "candidates": ["1191"]},
            ],
        },
        ensure_ascii=False,
    )
    generator = ParaphraseGenerator(MockLLMClient(response))

    result = generator.paraphrase_sample(
        _build_sample(),
        style_target="progress_note",
        paraphrase_mode="strict_preserve",
    )

    assert result is not None
    assert result["paraphrase_mode"] == "strict_preserve"
    assert result["source_scenario_id"] == "scenario_001"
    assert [entity["text"] for entity in result["entities"]] == [
        "đau ngực",
        "Troponin I",
        "tăng",
        "nhồi máu cơ tim cấp",
        "aspirin 81 mg po daily",
    ]


def test_semantic_mode_allows_surface_change_without_metadata_drift():
    response = json.dumps(
        {
            "note_rewritten": (
                "NB nhập viện vì đau ngực trái. Men tim Troponin I tăng. "
                "Kết luận NMCT cấp, điều trị aspirin 81 mg uống mỗi ngày."
            ),
            "entities_rewritten": [
                {"source_text": "đau ngực", "rewritten_text": "đau ngực trái", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
                {"source_text": "Troponin I", "rewritten_text": "Troponin I", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
                {"source_text": "tăng", "rewritten_text": "tăng", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": ["isHistorical"], "candidates": []},
                {"source_text": "nhồi máu cơ tim cấp", "rewritten_text": "NMCT cấp", "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["I21.9"]},
                {"source_text": "aspirin 81 mg po daily", "rewritten_text": "aspirin 81 mg uống mỗi ngày", "type": "THUỐC", "assertions": [], "candidates": ["1191"]},
            ],
        },
        ensure_ascii=False,
    )
    generator = ParaphraseGenerator(MockLLMClient(response))

    result = generator.paraphrase_sample(
        _build_sample(),
        style_target="clinical_note",
        paraphrase_mode="semantic_preserve",
    )

    assert result is not None
    assert result["paraphrase_mode"] == "semantic_preserve"
    assert [entity["type"] for entity in result["entities"]] == [
        "TRIỆU_CHỨNG",
        "TÊN_XÉT_NGHIỆM",
        "KẾT_QUẢ_XÉT_NGHIỆM",
        "CHẨN_ĐOÁN",
        "THUỐC",
    ]
    assert result["entities"][0]["text"] == "đau ngực trái"
    assert result["entities"][2]["assertions"] == ["isHistorical"]
    assert result["entities"][3]["candidates"] == ["I21.9"]
    assert result["entities"][4]["candidates"] == ["1191"]


def test_reject_if_mapping_missing_entity():
    response = json.dumps(
        {
            "note_rewritten": "NB đau ngực, Troponin I tăng, nhồi máu cơ tim cấp, aspirin 81 mg po daily.",
            "entities_rewritten": [
                {"source_text": "đau ngực", "rewritten_text": "đau ngực", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
                {"source_text": "Troponin I", "rewritten_text": "Troponin I", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
            ],
        },
        ensure_ascii=False,
    )
    generator = ParaphraseGenerator(MockLLMClient(response))

    result = generator.paraphrase_sample(
        _build_sample(),
        style_target="clinical_note",
        paraphrase_mode="semantic_preserve",
    )

    assert result is None


def test_reject_if_rewritten_entity_cannot_be_located():
    response = json.dumps(
        {
            "note_rewritten": (
                "NB nhập viện vì đau ngực. Men tim Troponin I tăng. "
                "Kết luận NMCT cấp, điều trị aspirin."
            ),
            "entities_rewritten": [
                {"source_text": "đau ngực", "rewritten_text": "đau ngực", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
                {"source_text": "Troponin I", "rewritten_text": "Troponin I", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
                {"source_text": "tăng", "rewritten_text": "tăng", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": ["isHistorical"], "candidates": []},
                {"source_text": "nhồi máu cơ tim cấp", "rewritten_text": "NMCT cấp", "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["I21.9"]},
                {"source_text": "aspirin 81 mg po daily", "rewritten_text": "aspirin 81 mg uống mỗi ngày", "type": "THUỐC", "assertions": [], "candidates": ["1191"]},
            ],
        },
        ensure_ascii=False,
    )
    generator = ParaphraseGenerator(MockLLMClient(response))

    result = generator.paraphrase_sample(
        _build_sample(),
        style_target="discharge_summary",
        paraphrase_mode="semantic_preserve",
    )

    assert result is None


def test_positions_match_relocated_text():
    response = json.dumps(
        {
            "note_rewritten": (
                "Tóm tắt vào viện: đau ngực trái kéo dài. "
                "Xét nghiệm Troponin I tăng, phù hợp NMCT cấp. "
                "Điều trị aspirin 81 mg uống mỗi ngày."
            ),
            "entities_rewritten": [
                {"source_text": "đau ngực", "rewritten_text": "đau ngực trái", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
                {"source_text": "Troponin I", "rewritten_text": "Troponin I", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
                {"source_text": "tăng", "rewritten_text": "tăng", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": ["isHistorical"], "candidates": []},
                {"source_text": "nhồi máu cơ tim cấp", "rewritten_text": "NMCT cấp", "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["I21.9"]},
                {"source_text": "aspirin 81 mg po daily", "rewritten_text": "aspirin 81 mg uống mỗi ngày", "type": "THUỐC", "assertions": [], "candidates": ["1191"]},
            ],
        },
        ensure_ascii=False,
    )
    generator = ParaphraseGenerator(MockLLMClient(response))

    result = generator.paraphrase_sample(
        _build_sample(),
        style_target="admission_note",
        paraphrase_mode="semantic_preserve",
    )

    assert result is not None
    for entity in result["entities"]:
        start, end = entity["position"]
        assert result["text"][start:end] == entity["text"]


def test_reject_if_metadata_drifts_in_semantic_mode():
    response = json.dumps(
        {
            "note_rewritten": (
                "NB nhập viện vì đau ngực trái. Men tim Troponin I tăng. "
                "Kết luận NMCT cấp, điều trị aspirin 81 mg uống mỗi ngày."
            ),
            "entities_rewritten": [
                {"source_text": "đau ngực", "rewritten_text": "đau ngực trái", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": []},
                {"source_text": "Troponin I", "rewritten_text": "Troponin I", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": []},
                {"source_text": "tăng", "rewritten_text": "tăng", "type": "KẾT_QUẢ_XÉT_NGHIỆM", "assertions": [], "candidates": []},
                {"source_text": "nhồi máu cơ tim cấp", "rewritten_text": "NMCT cấp", "type": "CHẨN_ĐOÁN", "assertions": [], "candidates": ["I21.9"]},
                {"source_text": "aspirin 81 mg po daily", "rewritten_text": "aspirin 81 mg uống mỗi ngày", "type": "THUỐC", "assertions": [], "candidates": ["1191"]},
            ],
        },
        ensure_ascii=False,
    )
    mock = MockLLMClient(response)
    generator = ParaphraseGenerator(mock)

    result = generator.paraphrase_sample(
        _build_sample(),
        style_target="admission_note",
        paraphrase_mode="semantic_preserve",
    )

    assert result is None
    assert len(mock.prompts) == 1
    assert "ENTITY JSON GỐC" in mock.prompts[0]["prompt"]
    assert "admission_note" in mock.prompts[0]["prompt"]
    assert mock.prompts[0]["system_prompt"]
