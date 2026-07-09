import json
from copy import deepcopy
from typing import Dict, List, Optional

from data_generation.generators.critic_agent import CriticAgent
from data_generation.utils.cleanup import _filter_schema, _relocate


STRICT_PARAPHRASE_SYSTEM_PROMPT = "Bạn là bác sĩ đang viết lại ghi chú lâm sàng tiếng Việt."
STRICT_PARAPHRASE_PROMPT_TEMPLATE = """Bạn là bác sĩ đang viết lại ghi chú lâm sàng tiếng Việt.

Nhiệm vụ:
Viết lại NOTE dưới đây theo phong cách {style_target}, tự nhiên hơn và khác cách diễn đạt ban đầu.

Chế độ hiện tại: strict_preserve
- Có thể đổi trật tự câu, rút gọn cú pháp, thay đổi nhịp ghi chú.
- Phải giữ nguyên literal entity text cho toàn bộ entity trong ENTITY JSON GỐC.

Không được phép:
- làm mất thực thể
- đổi loại thực thể
- đổi assertion
- đổi candidates/code mapping
- thêm thông tin lâm sàng mới không có trong note gốc

NOTE GỐC:
{note}

ENTITY JSON GỐC:
{entities_json}

Trả về CHỈ một JSON hợp lệ:
{{
  "note_rewritten": "...",
  "entities_rewritten": [
    {{
      "source_text": "...",
      "rewritten_text": "...",
      "type": "...",
      "assertions": [...],
      "candidates": [...]
    }}
  ]
}}"""

SEMANTIC_PARAPHRASE_SYSTEM_PROMPT = "Bạn là bác sĩ đang viết lại ghi chú lâm sàng tiếng Việt."
SEMANTIC_PARAPHRASE_PROMPT_TEMPLATE = """Bạn là bác sĩ đang viết lại ghi chú lâm sàng tiếng Việt.

Nhiệm vụ:
Viết lại NOTE dưới đây theo phong cách {style_target}, tự nhiên hơn và khác cách diễn đạt ban đầu.
Được phép:
- đổi trật tự câu
- dùng viết tắt y khoa
- rút gọn cú pháp
- đổi cách viết bề mặt của thực thể nếu vẫn giữ nguyên meaning lâm sàng và đúng loại nhãn

Không được phép:
- làm mất thực thể
- đổi loại thực thể
- đổi assertion
- đổi candidates/code mapping
- thêm thông tin lâm sàng mới không có trong note gốc

NOTE GỐC:
{note}

ENTITY JSON GỐC:
{entities_json}

Trả về CHỈ một JSON hợp lệ:
{{
  "note_rewritten": "...",
  "entities_rewritten": [
    {{
      "source_text": "...",
      "rewritten_text": "...",
      "type": "...",
      "assertions": [...],
      "candidates": [...]
    }}
  ]
}}"""

VALID_MODES = {"strict_preserve", "semantic_preserve"}


class ParaphraseGenerator:
    """Sinh biến thể note nhưng giữ nguyên label semantics."""

    def __init__(self, llm_client, temperature: float = 0.7, max_tokens: int = 1200):
        self.llm = llm_client
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._json_cleaner = CriticAgent(llm_client)

    def paraphrase_sample(
        self,
        sample: Dict,
        style_target: str,
        paraphrase_mode: str = "strict_preserve",
    ) -> Optional[Dict]:
        if paraphrase_mode not in VALID_MODES:
            raise ValueError(f"Unsupported paraphrase_mode: {paraphrase_mode}")

        original_text = sample.get("text", "")
        scenario_id = sample.get("scenario_id", "")
        source_entities = _filter_schema(deepcopy(sample.get("entities", [])))
        if not original_text or not source_entities:
            return None

        payload = self._rewrite_note(
            original_text,
            source_entities,
            style_target=style_target,
            paraphrase_mode=paraphrase_mode,
        )
        if not payload:
            return None

        rewritten_text = (payload.get("note_rewritten") or "").strip()
        rewritten_mappings = payload.get("entities_rewritten")
        if not rewritten_text or not isinstance(rewritten_mappings, list):
            return None

        validated_entities = self._validate_and_build_entities(
            source_entities,
            rewritten_mappings,
            paraphrase_mode=paraphrase_mode,
        )
        if validated_entities is None:
            return None

        relocated_entities = self._relocate_entities(rewritten_text, validated_entities)
        if len(relocated_entities) != len(source_entities):
            return None
        if not self._validate_positions(rewritten_text, relocated_entities):
            return None

        return {
            "text": rewritten_text,
            "entities": relocated_entities,
            "paraphrase_mode": paraphrase_mode,
            "source_scenario_id": scenario_id,
            "generation_mode": "paraphrase_preserving_labels",
        }

    def _rewrite_note(
        self,
        note: str,
        entities: List[Dict],
        style_target: str,
        paraphrase_mode: str,
    ) -> Optional[Dict]:
        prompt = self._build_prompt(
            note=note,
            entities=entities,
            style_target=style_target,
            paraphrase_mode=paraphrase_mode,
        )
        response = self.llm.call_text_gen(
            prompt,
            system_prompt=self._system_prompt_for(paraphrase_mode),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        cleaned = self._json_cleaner._clean_json_response(response or "")
        if not cleaned:
            return None
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _build_prompt(
        self,
        note: str,
        entities: List[Dict],
        style_target: str,
        paraphrase_mode: str,
    ) -> str:
        prompt_entities = [
            {
                "text": entity["text"],
                "type": entity["type"],
                "assertions": entity.get("assertions", []),
                "candidates": entity.get("candidates", []),
            }
            for entity in entities
        ]
        entities_json = json.dumps(prompt_entities, ensure_ascii=False, indent=2)
        template = (
            STRICT_PARAPHRASE_PROMPT_TEMPLATE
            if paraphrase_mode == "strict_preserve"
            else SEMANTIC_PARAPHRASE_PROMPT_TEMPLATE
        )
        return template.format(
            style_target=style_target,
            note=note,
            entities_json=entities_json,
        )

    @staticmethod
    def _system_prompt_for(paraphrase_mode: str) -> str:
        if paraphrase_mode == "strict_preserve":
            return STRICT_PARAPHRASE_SYSTEM_PROMPT
        return SEMANTIC_PARAPHRASE_SYSTEM_PROMPT

    def _validate_and_build_entities(
        self,
        source_entities: List[Dict],
        rewritten_mappings: List[Dict],
        paraphrase_mode: str,
    ) -> Optional[List[Dict]]:
        if len(rewritten_mappings) != len(source_entities):
            return None

        remaining_mappings = list(rewritten_mappings)
        validated_entities = []

        for source_entity in source_entities:
            mapping_index = self._find_mapping_index(source_entity, remaining_mappings)
            if mapping_index is None:
                return None

            mapping = remaining_mappings.pop(mapping_index)
            normalized_mapping = self._normalize_mapping(mapping)
            if normalized_mapping is None:
                return None

            if normalized_mapping["source_text"] != source_entity["text"]:
                return None
            if normalized_mapping["type"] != source_entity["type"]:
                return None
            if normalized_mapping["assertions"] != source_entity.get("assertions", []):
                return None
            if normalized_mapping["candidates"] != source_entity.get("candidates", []):
                return None
            if paraphrase_mode == "strict_preserve" and normalized_mapping["rewritten_text"] != source_entity["text"]:
                return None

            validated_entities.append(
                {
                    "text": normalized_mapping["rewritten_text"],
                    "type": source_entity["type"],
                    "assertions": source_entity.get("assertions", []),
                    "candidates": source_entity.get("candidates", []),
                }
            )

        return validated_entities if not remaining_mappings else None

    @staticmethod
    def _find_mapping_index(source_entity: Dict, rewritten_mappings: List[Dict]) -> Optional[int]:
        for index, mapping in enumerate(rewritten_mappings):
            if mapping.get("source_text") == source_entity["text"]:
                return index
        return None

    @staticmethod
    def _normalize_mapping(mapping: Dict) -> Optional[Dict]:
        source_text = mapping.get("source_text")
        rewritten_text = mapping.get("rewritten_text")
        entity_type = mapping.get("type")
        if not all(isinstance(value, str) and value for value in [source_text, rewritten_text, entity_type]):
            return None
        assertions = mapping.get("assertions", [])
        candidates = mapping.get("candidates", [])
        if not isinstance(assertions, list) or not all(isinstance(item, str) for item in assertions):
            return None
        if not isinstance(candidates, list) or not all(isinstance(item, str) for item in candidates):
            return None
        return {
            "source_text": source_text,
            "rewritten_text": rewritten_text,
            "type": entity_type,
            "assertions": assertions,
            "candidates": candidates,
        }

    def _relocate_entities(self, text: str, entities: List[Dict]) -> List[Dict]:
        relocated = _relocate(deepcopy(entities), text)
        for entity in relocated:
            if isinstance(entity.get("position"), tuple):
                entity["position"] = list(entity["position"])
        return relocated

    @staticmethod
    def _validate_positions(text: str, entities: List[Dict]) -> bool:
        for entity in entities:
            position = entity.get("position", [])
            if len(position) != 2:
                return False
            start, end = position
            if start < 0 or end <= start or end > len(text):
                return False
            if text[start:end] != entity["text"]:
                return False
        return True
