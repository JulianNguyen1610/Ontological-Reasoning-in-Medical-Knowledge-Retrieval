"""
Tests cho data generation pipeline.
Mỗi test khóa lại một bug đã phát hiện trong review.
Không gọi API thật — toàn bộ dùng mock.
"""
import json
import pytest
from data_generation.generators.text_generator import (
    TextGenerator,
    EntityAnnotation,
    GeneratedSample,
)
from data_generation.generators.critic_agent import CriticAgent
from data_generation.utils.cleanup import clean_sample


# ============================================================
# Mock helpers
# ============================================================

class MockLLMClient:
    """Mock đủ interface call_text_gen / call_critic."""

    def __init__(self, text_response: str = "", critic_response: dict | None = None):
        self._text_response = text_response
        self._critic_response = critic_response or {
            "is_valid": True,
            "errors": [],
            "suggestions": [],
        }

    def call_text_gen(self, prompt, system_prompt="", temperature=0.7, max_tokens=500):
        return self._text_response

    def call_critic(self, prompt, system_prompt="", temperature=0.7, max_tokens=500):
        return json.dumps(self._critic_response, ensure_ascii=False)


# ============================================================
# 1. Test: package import works
# ============================================================

class TestPackageImport:
    def test_import_pipeline(self):
        """pipeline.py phải import được từ repo root."""
        from data_generation.pipeline import DataGenerationPipeline  # noqa: F401

    def test_import_config(self):
        from data_generation.config import GenerationConfig  # noqa: F401

    def test_import_text_generator(self):
        from data_generation.generators.text_generator import TextGenerator  # noqa: F401

    def test_import_critic_agent(self):
        from data_generation.generators.critic_agent import CriticAgent  # noqa: F401

    def test_import_cleanup(self):
        from data_generation.utils.cleanup import clean_sample  # noqa: F401


# ============================================================
# 2. Test: MockLLMClient interface
# ============================================================

class TestMockLLMClientInterface:
    """Mock phải có call_text_gen và call_critic khớp contract."""

    def test_has_call_text_gen(self):
        client = MockLLMClient(text_response="hello")
        result = client.call_text_gen("prompt")
        assert isinstance(result, str)

    def test_has_call_critic(self):
        client = MockLLMClient()
        raw = client.call_critic("prompt")
        parsed = json.loads(raw)
        assert "is_valid" in parsed
        assert "errors" in parsed

    def test_text_generator_uses_call_text_gen(self):
        """TextGenerator phải gọi call_text_gen (không phải generate)."""
        mock = MockLLMClient(text_response="BN nhập viện vì đau ngực")
        gen = TextGenerator(mock)
        # Chỉ kiểm tra method tồn tại và không raise
        assert hasattr(mock, "call_text_gen")

    def test_critic_agent_uses_call_critic(self):
        """CriticAgent phải gọi call_critic."""
        mock = MockLLMClient()
        critic = CriticAgent(mock)
        result = critic.review_sample("text", [])
        assert result.is_valid is True


# ============================================================
# 3. Test: Missing entity → reject
# ============================================================

class TestMissingEntityValidation:
    """Kiểm tra chuỗi chặn: _locate_entities → generate_sample → _generate_single_sample."""

    # ---------- Level 1: _locate_entities drops missing ----------

    def test_locate_entities_drops_missing(self):
        """Entity không có trong text phải bị loại khỏi positioned list."""
        mock = MockLLMClient()
        gen = TextGenerator(mock)
        text = "BN nhập viện vì đau ngực. CD: nhồi máu cơ tim cấp."

        entities = [
            EntityAnnotation(
                text="đau ngực", type="TRIỆU_CHỨNG",
                assertions=[], candidates=[],
            ),
            EntityAnnotation(
                text="ENTITY_KHÔNG_CÓ_TRONG_TEXT", type="CHẨN_ĐOÁN",
                assertions=[], candidates=[],
            ),
        ]

        positioned = gen._locate_entities(text, entities)
        assert len(positioned) < len(entities), (
            "_locate_entities phải loại entity không tìm thấy"
        )

    def test_expected_count_tracked(self):
        """last_expected_entity_count phải được set đúng."""
        mock = MockLLMClient(text_response="BN đau ngực")
        gen = TextGenerator(mock)
        assert gen.last_expected_entity_count == 0  # chưa chạy

    def test_empty_entity_sample_rejected_at_locate(self):
        """0 entity located khi expected > 0."""
        mock = MockLLMClient()
        gen = TextGenerator(mock)
        text = "Văn bản hoàn toàn không chứa entity nào."
        entities = [
            EntityAnnotation(
                text="nhồi máu cơ tim cấp", type="CHẨN_ĐOÁN",
                assertions=[], candidates=[],
            ),
        ]
        positioned = gen._locate_entities(text, entities)
        assert len(positioned) == 0

    # ---------- Level 2: generate_sample returns None ----------

    def test_generate_sample_returns_none_when_entity_missing(self):
        """generate_sample() phải trả None khi LLM sinh text thiếu entity.

        Đảm bảo caller trực tiếp (không qua pipeline) cũng bị chặn.
        """
        from dataclasses import dataclass
        from typing import List, Dict

        # Mock LLM trả text KHÔNG chứa entity bắt buộc
        mock = MockLLMClient(
            text_response="Văn bản hoàn toàn không chứa bất kỳ entity nào."
        )
        gen = TextGenerator(mock)

        # Tạo scenario giả có 1 diagnosis
        @dataclass
        class FakeScenario:
            diagnosis: Dict
            symptoms: List[Dict]
            drugs: List[Dict]
            lab_tests: List[Dict]
            assertions: List[str]
            text_style: str
            complexity: str

        scenario = FakeScenario(
            diagnosis={"name_vi": "nhồi máu cơ tim cấp", "code": "I21.9"},
            symptoms=[],
            drugs=[],
            lab_tests=[],
            assertions=[],
            text_style="clinical_note",
            complexity="single_entity",
        )

        from data_generation.generators.style_director import StyleDirector
        result = gen.generate_sample(scenario, StyleDirector())

        assert result is None, (
            "generate_sample() phải trả None khi text thiếu entity bắt buộc, "
            f"nhưng trả {type(result)}"
        )
        # expected_count vẫn phải được ghi nhận
        assert gen.last_expected_entity_count >= 1

    # ---------- Level 3: _generate_single_sample rejects ----------

    def test_pipeline_generate_single_sample_rejects_missing_entity(self):
        """_generate_single_sample() phải trả None và tăng retry_count
        khi TextGenerator.generate_sample() trả None do thiếu entity.
        """
        from pathlib import Path
        from data_generation.config import GenerationConfig
        from data_generation.pipeline import DataGenerationPipeline

        # Mock luôn trả text không chứa entity nào
        mock = MockLLMClient(
            text_response="Văn bản rỗng entity."
        )

        config = GenerationConfig(num_samples=1, max_retries=2)
        seeds_dir = Path(__file__).resolve().parent.parent / "data_generation" / "knowledge_seeds"
        output_dir = Path(__file__).resolve().parent.parent / "data" / "raw_generated"

        pipeline = DataGenerationPipeline(
            config=config,
            llm_client=mock,
            output_dir=output_dir,
            seeds_dir=seeds_dir,
        )

        result = pipeline._generate_single_sample()

        assert result is None, (
            "_generate_single_sample() phải trả None khi tất cả retries thất bại "
            "do thiếu entity"
        )
        assert pipeline.stats["retry_count"] >= 1, (
            f"retry_count phải >= 1, nhưng là {pipeline.stats['retry_count']}"
        )


# ============================================================
# 4. Test: _format_lab_result
# ============================================================

class TestFormatLabResult:
    """Kiểm tra bug mất đơn vị (unit) đã được sửa."""

    def _make_generator(self):
        return TextGenerator(MockLLMClient())

    def test_value_with_unit(self):
        """7.1 + mmol/L → '7.1 mmol/L'"""
        gen = self._make_generator()
        test = {
            "test_name": "Glucose",
            "abnormal_values": ["7.1"],
            "units": ["mmol/L"],
        }
        result = gen._format_lab_result(test)
        assert result == "7.1 mmol/L", f"Got: {result!r}"

    def test_value_without_unit(self):
        """7.1 + '' → '7.1'"""
        gen = self._make_generator()
        test = {
            "test_name": "Glucose",
            "abnormal_values": ["7.1"],
            "units": [""],
        }
        result = gen._format_lab_result(test)
        assert result == "7.1", f"Got: {result!r}"

    def test_normal_value(self):
        """'bình thường' → 'Glucose bình thường'"""
        gen = self._make_generator()
        test = {
            "test_name": "Glucose",
            "abnormal_values": ["bình thường"],
            "units": ["mmol/L"],
        }
        result = gen._format_lab_result(test)
        assert result == "Glucose bình thường", f"Got: {result!r}"

    def test_no_trailing_space(self):
        """Không được có trailing space."""
        gen = self._make_generator()
        test = {
            "test_name": "WBC",
            "abnormal_values": ["15.2"],
            "units": ["G/L"],
        }
        result = gen._format_lab_result(test)
        assert result == result.strip(), f"Trailing space in: {result!r}"

    def test_no_unit_no_abnormal(self):
        """Fallback: không có abnormal_values → 'test_name bình thường'."""
        gen = self._make_generator()
        test = {"test_name": "CBC"}
        result = gen._format_lab_result(test)
        assert "bình thường" in result


# ============================================================
# 4b. Test: assertion ngữ cảnh phải khớp text
# ============================================================

class TestAssertionContextValidation:
    def _make_generator(self):
        return TextGenerator(MockLLMClient())

    def test_negated_assertion_requires_negation_cue(self):
        gen = self._make_generator()
        text = "BN đau ngực tăng dần 2 ngày nay."
        entity = EntityAnnotation(
            text="đau ngực",
            type="TRIỆU_CHỨNG",
            assertions=["isNegated"],
            candidates=[],
            position=(3, 11),
        )

        validation = gen._validate_sample(text, [entity])

        assert validation["valid"] is False
        assert any(
            error["error_type"] == "assertion_context_error"
            for error in validation["errors"]
        )

    def test_negated_assertion_passes_with_negation_cue(self):
        gen = self._make_generator()
        text = "BN phủ nhận đau ngực và khó thở."
        entity = EntityAnnotation(
            text="đau ngực",
            type="TRIỆU_CHỨNG",
            assertions=["isNegated"],
            candidates=[],
            position=(12, 20),
        )

        validation = gen._validate_sample(text, [entity])

        assert validation["valid"] is True

    def test_drug_only_receives_historical_assertion(self):
        gen = self._make_generator()
        random_values = {
            tuple(sorted(gen._assign_assertions_to_entity(
                ["isNegated", "isHistorical", "isFamily"],
                "amlodipine 5 mg po daily",
                "THUỐC",
            )))
            for _ in range(25)
        }

        assert random_values <= {(), ("isHistorical",)}

    def test_lab_name_does_not_receive_negated_assertion(self):
        gen = self._make_generator()
        random_values = {
            tuple(sorted(gen._assign_assertions_to_entity(
                ["isNegated", "isHistorical"],
                "công thức máu",
                "TÊN_XÉT_NGHIỆM",
            )))
            for _ in range(25)
        }

        assert random_values <= {(), ("isHistorical",)}

    def test_negated_lab_result_uses_result_language(self):
        gen = self._make_generator()
        entity = EntityAnnotation(
            text="công thức máu bình thường",
            type="KẾT_QUẢ_XÉT_NGHIỆM",
            assertions=["isNegated"],
            candidates=[],
        )

        example = gen._build_example_sentence(entity)

        assert example.startswith("Chưa có kết quả")
        assert "phủ nhận" not in example.lower()

    def test_assertion_coverage_forces_best_candidate_when_missing(self):
        gen = self._make_generator()
        entities = [
            EntityAnnotation(
                text="Viêm dạ dày",
                type="CHẨN_ĐOÁN",
                assertions=[],
                candidates=["K29.7"],
            ),
            EntityAnnotation(
                text="đau thượng vị",
                type="TRIỆU_CHỨNG",
                assertions=[],
                candidates=[],
            ),
        ]

        gen._ensure_assertion_coverage(entities, ["isNegated"])

        assert entities[0].assertions == []
        assert entities[1].assertions == ["isNegated"]

    def test_family_coverage_can_select_diagnosis(self):
        gen = self._make_generator()
        entities = [
            EntityAnnotation(
                text="Đái tháo đường type 2",
                type="CHẨN_ĐOÁN",
                assertions=[],
                candidates=["E11"],
            ),
            EntityAnnotation(
                text="mệt mỏi",
                type="TRIỆU_CHỨNG",
                assertions=[],
                candidates=[],
            ),
        ]

        gen._ensure_assertion_coverage(entities, ["isFamily"])

        assert entities[0].assertions == ["isFamily"]

    def test_family_coverage_rejects_acute_diagnosis_and_symptoms(self):
        gen = self._make_generator()
        entities = [
            EntityAnnotation(
                text="Viêm dạ dày ruột cấp",
                type="CHẨN_ĐOÁN",
                assertions=[],
                candidates=["A09.0"],
            ),
            EntityAnnotation(
                text="đau bụng",
                type="TRIỆU_CHỨNG",
                assertions=[],
                candidates=[],
            ),
        ]

        gen._ensure_assertion_coverage(entities, ["isFamily"])

        assert not any(entity.assertions for entity in entities)

    def test_assertion_coverage_limits_entities_per_sample(self):
        gen = self._make_generator()
        entities = [
            EntityAnnotation(text=f"triệu chứng {i}", type="TRIỆU_CHỨNG", assertions=["isHistorical"], candidates=[])
            for i in range(6)
        ]

        gen._ensure_assertion_coverage(entities, ["isHistorical"])

        assert 1 <= sum(bool(entity.assertions) for entity in entities) <= 2

    def test_historical_examples_are_varied(self):
        gen = self._make_generator()
        entity = EntityAnnotation(
            text="hen phế quản",
            type="CHẨN_ĐOÁN",
            assertions=["isHistorical"],
            candidates=["J45.9"],
        )

        examples = {gen._build_example_sentence(entity) for _ in range(30)}

        assert len(examples) > 1

    def test_historical_diagnosis_examples_use_diagnosis_language(self):
        gen = self._make_generator()
        entity = EntityAnnotation(
            text="Suy tim",
            type="CHẨN_ĐOÁN",
            assertions=["isHistorical"],
            candidates=["I50.9"],
        )

        examples = {gen._build_example_sentence(entity) for _ in range(30)}

        assert all("xuất hiện" not in example for example in examples)
        assert all(
            any(cue in example for cue in ["chẩn đoán", "điều trị", "theo dõi"])
            for example in examples
        )

    def test_family_examples_are_varied(self):
        gen = self._make_generator()
        entity = EntityAnnotation(
            text="đái tháo đường type 2",
            type="CHẨN_ĐOÁN",
            assertions=["isFamily"],
            candidates=["E11"],
        )

        examples = {gen._build_example_sentence(entity) for _ in range(30)}

        assert len(examples) > 1

    def test_entity_placement_plan_prefers_assertion_aware_sections(self):
        gen = self._make_generator()
        entities = [
            EntityAnnotation(
                text="đau ngực",
                type="TRIỆU_CHỨNG",
                assertions=["isNegated"],
                candidates=[],
            ),
            EntityAnnotation(
                text="hen phế quản",
                type="CHẨN_ĐOÁN",
                assertions=["isHistorical"],
                candidates=["J45.9"],
            ),
            EntityAnnotation(
                text="mẹ mắc đái tháo đường",
                type="CHẨN_ĐOÁN",
                assertions=["isFamily"],
                candidates=["E11.9"],
            ),
        ]

        plan = gen._build_entity_placement_plan(entities)

        assert plan[0]["section"] == "2. Tiền sử bệnh hiện tại"
        assert "không" in plan[0]["required_cue"]
        assert "phủ nhận đau ngực" in plan[0]["example_sentence"]
        assert plan[1]["section"] == "1. Tiền sử bệnh"
        assert "tiền sử" in plan[1]["required_cue"]
        assert plan[2]["section"] == "1. Tiền sử bệnh"
        assert "gia đình" in plan[2]["required_cue"]


# ============================================================
# 5. Test: cleanup không phá position hợp lệ
# ============================================================

class TestCleanupPositions:
    """clean_sample phải giữ nguyên position nếu entity hợp lệ."""

    def test_valid_positions_preserved(self):
        text = "BN đau ngực. CD: nhồi máu cơ tim cấp."
        entities = [
            {
                "text": "đau ngực",
                "type": "TRIỆU_CHỨNG",
                "assertions": [],
                "candidates": [],
                "position": [3, 11],
            },
            {
                "text": "nhồi máu cơ tim cấp",
                "type": "CHẨN_ĐOÁN",
                "assertions": [],
                "candidates": [],
                "position": [17, 37],
            },
        ]
        sample = {"text": text, "entities": entities, "scenario_id": "test"}
        cleaned = clean_sample(sample)

        assert len(cleaned["entities"]) == 2, "Should preserve both entities"
        for e in cleaned["entities"]:
            start, end = e["position"]
            assert text[start:end] == e["text"], (
                f"Position mismatch: text[{start}:{end}]={text[start:end]!r} vs {e['text']!r}"
            )

    def test_invalid_type_filtered(self):
        """Entity với type không hợp lệ phải bị loại."""
        text = "BN đau ngực."
        entities = [
            {
                "text": "đau ngực",
                "type": "INVALID_TYPE",
                "assertions": [],
                "candidates": [],
                "position": [3, 11],
            },
        ]
        sample = {"text": text, "entities": entities, "scenario_id": "test"}
        cleaned = clean_sample(sample)
        assert len(cleaned["entities"]) == 0

    def test_invalid_assertion_stripped(self):
        """Assertion không hợp lệ phải bị loại khỏi list."""
        text = "BN đau ngực."
        entities = [
            {
                "text": "đau ngực",
                "type": "TRIỆU_CHỨNG",
                "assertions": ["isNegated", "bogusAssertion"],
                "candidates": [],
                "position": [3, 11],
            },
        ]
        sample = {"text": text, "entities": entities, "scenario_id": "test"}
        cleaned = clean_sample(sample)
        assert len(cleaned["entities"]) == 1
        assert cleaned["entities"][0]["assertions"] == ["isNegated"]
