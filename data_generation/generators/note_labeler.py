import hashlib
import json
from copy import deepcopy
from typing import Dict, List, Optional

from data_generation.generators.critic_agent import CriticAgent
from data_generation.utils.cleanup import _filter_schema, _relocate


NOTE_LABELER_SYSTEM_PROMPT = "Bạn là chuyên gia gán nhãn thực thể y khoa tiếng Việt."
NOTE_LABELER_PROMPT_TEMPLATE = """Bạn là chuyên gia gán nhãn thực thể y khoa tiếng Việt.

Hãy đọc NOTE và trích xuất thực thể theo schema.

ENTITY TYPES hợp lệ:
- TRIỆU_CHỨNG
- TÊN_XÉT_NGHIỆM
- KẾT_QUẢ_XÉT_NGHIỆM
- CHẨN_ĐOÁN
- THUỐC

ASSERTIONS hợp lệ:
- isNegated
- isFamily
- isHistorical

Yêu cầu:
- Chỉ trích xuất thực thể xuất hiện trực tiếp trong NOTE
- text phải là chuỗi nguyên văn từ NOTE
- candidates chỉ điền nếu chắc chắn
- confidence là mức tin cậy của riêng entity đó từ 0 đến 1
- rationale_short rất ngắn, tối đa 12 từ
- không thêm giải thích ngoài JSON

NOTE:
{note}

Trả về JSON:
{{
  "entities": [
    {{
      "text": "...",
      "type": "...",
      "assertions": [],
      "candidates": [],
      "confidence": 0.0,
      "rationale_short": "..."
    }}
  ]
}}"""

DEFAULT_PROVENANCE = {
    "source_id": "",
    "source_type": "",
    "teacher_model": "",
    "prompt_version": "v1",
}


class NoteLabeler:
    """Teacher-LLM based note-to-label distillation with provenance."""

    def __init__(self, llm_client, temperature: float = 0.0, max_tokens: int = 1200):
        self.llm = llm_client
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._json_cleaner = CriticAgent(llm_client)

    def label_note(
        self,
        note: str,
        metadata: Optional[Dict] = None,
        min_confidence: Optional[float] = None,
    ) -> Dict:
        note = (note or "").strip()
        metadata = self._normalize_metadata(metadata)
        min_confidence = self._normalize_min_confidence(min_confidence)

        if not note:
            return self._build_output(
                note,
                [],
                metadata,
                dropped_low_confidence_entities=0,
                labeling_status="empty_note",
                teacher_parse_success=False,
                teacher_returned_entities=0,
                validated_entities=0,
            )

        teacher_payload, parse_success = self._extract_teacher_payload(note)
        teacher_entities = teacher_payload.get("entities", []) if isinstance(teacher_payload, dict) else []
        normalized_entities = self._normalize_entities(teacher_entities)
        filtered_entities = _filter_schema(normalized_entities)
        filtered_entities = self._merge_filtered_schema_fields(normalized_entities, filtered_entities)
        relocated_entities = self._relocate_supported_entities(note, filtered_entities)
        relocated_entities, dropped_count = self._apply_confidence_filter(relocated_entities, min_confidence)

        labeling_status = self._determine_labeling_status(
            parse_success=parse_success,
            teacher_entity_count=len(teacher_entities),
            validated_entity_count=len(relocated_entities),
        )

        return self._build_output(
            note,
            relocated_entities,
            metadata,
            dropped_low_confidence_entities=dropped_count,
            labeling_status=labeling_status,
            teacher_parse_success=parse_success,
            teacher_returned_entities=len(teacher_entities),
            validated_entities=len(relocated_entities),
        )

    def _extract_teacher_payload(self, note: str) -> tuple[Dict, bool]:
        prompt = NOTE_LABELER_PROMPT_TEMPLATE.format(note=note)
        response = self.llm.call_text_gen(
            prompt,
            system_prompt=NOTE_LABELER_SYSTEM_PROMPT,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        cleaned = self._json_cleaner._clean_json_response(response or "")
        if not cleaned:
            return {"entities": []}, False
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return {"entities": []}, False
        if not isinstance(data, dict):
            return {"entities": []}, False
        return data, True

    def _normalize_entities(self, entities: List[Dict]) -> List[Dict]:
        normalized = []
        if not isinstance(entities, list):
            return normalized
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            text = entity.get("text")
            entity_type = entity.get("type")
            if not isinstance(text, str) or not isinstance(entity_type, str):
                continue
            normalized.append(
                {
                    "text": text,
                    "type": entity_type,
                    "assertions": self._normalize_string_list(entity.get("assertions", [])),
                    "candidates": self._normalize_string_list(entity.get("candidates", [])),
                    "teacher_confidence": self._normalize_confidence(entity.get("confidence")),
                    "teacher_rationale_short": self._normalize_rationale(entity.get("rationale_short")),
                }
            )
        return normalized

    def _merge_filtered_schema_fields(
        self,
        original_entities: List[Dict],
        filtered_entities: List[Dict],
    ) -> List[Dict]:
        merged = []
        remaining = deepcopy(original_entities)
        for entity in filtered_entities:
            match_index = self._find_matching_entity_index(entity, remaining)
            if match_index is None:
                continue
            original = remaining.pop(match_index)
            merged_entity = dict(entity)
            merged_entity["teacher_confidence"] = original.get("teacher_confidence")
            merged_entity["teacher_rationale_short"] = original.get("teacher_rationale_short")
            merged.append(merged_entity)
        return merged

    def _relocate_supported_entities(self, note: str, entities: List[Dict]) -> List[Dict]:
        exact_match_entities = []
        for entity in deepcopy(entities):
            if entity["text"] in note:
                exact_match_entities.append(entity)
        relocated = _relocate(exact_match_entities, note)
        for entity in relocated:
            if isinstance(entity.get("position"), tuple):
                entity["position"] = list(entity["position"])
        return [entity for entity in relocated if self._is_valid_position(note, entity)]

    def _apply_confidence_filter(
        self,
        entities: List[Dict],
        min_confidence: Optional[float],
    ) -> tuple[List[Dict], int]:
        if min_confidence is None:
            return entities, 0
        kept = []
        dropped = 0
        for entity in entities:
            confidence = entity.get("teacher_confidence")
            if confidence is not None and confidence < min_confidence:
                dropped += 1
                continue
            kept.append(entity)
        return kept, dropped

    @staticmethod
    def _find_matching_entity_index(entity: Dict, pool: List[Dict]) -> Optional[int]:
        for index, candidate in enumerate(pool):
            if (
                candidate.get("text") == entity.get("text")
                and candidate.get("type") == entity.get("type")
                and candidate.get("candidates", []) == entity.get("candidates", [])
            ):
                return index
        return None

    @staticmethod
    def _normalize_string_list(values) -> List[str]:
        if not isinstance(values, list):
            return []
        return [value for value in values if isinstance(value, str)]

    @staticmethod
    def _normalize_rationale(value) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _normalize_confidence(value) -> Optional[float]:
        if value is None:
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        if confidence < 0:
            return 0.0
        if confidence > 1:
            return 1.0
        return confidence

    @staticmethod
    def _normalize_metadata(metadata: Optional[Dict]) -> Dict:
        merged = dict(DEFAULT_PROVENANCE)
        if isinstance(metadata, dict):
            for key in DEFAULT_PROVENANCE:
                value = metadata.get(key)
                if isinstance(value, str):
                    merged[key] = value
        return merged

    @staticmethod
    def _normalize_min_confidence(min_confidence: Optional[float]) -> Optional[float]:
        if min_confidence is None:
            return None
        try:
            value = float(min_confidence)
        except (TypeError, ValueError):
            return None
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value

    @staticmethod
    def _is_valid_position(note: str, entity: Dict) -> bool:
        position = entity.get("position", [])
        if len(position) != 2:
            return False
        start, end = position
        return 0 <= start < end <= len(note) and note[start:end] == entity["text"]

    @staticmethod
    def _scenario_id_for(note: str, metadata: Dict) -> str:
        seed = f"{metadata.get('source_id', '')}::{note}"
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
        return f"note_label_{digest}"

    def _build_output(
        self,
        note: str,
        entities: List[Dict],
        metadata: Dict,
        dropped_low_confidence_entities: int,
        labeling_status: str,
        teacher_parse_success: bool,
        teacher_returned_entities: int,
        validated_entities: int,
    ) -> Dict:
        return {
            "text": note,
            "entities": entities,
            "scenario_id": self._scenario_id_for(note, metadata),
            "generation_mode": "note_to_label",
            "label_provenance": {
                "source_id": metadata["source_id"],
                "source_type": metadata["source_type"],
                "teacher_model": metadata["teacher_model"],
                "prompt_version": metadata["prompt_version"],
                "label_style": "weak_supervision",
                "labeling_status": labeling_status,
                "teacher_parse_success": teacher_parse_success,
                "teacher_returned_entities": teacher_returned_entities,
                "validated_entities": validated_entities,
                "dropped_low_confidence_entities": dropped_low_confidence_entities,
            },
        }

    @staticmethod
    def _determine_labeling_status(
        parse_success: bool,
        teacher_entity_count: int,
        validated_entity_count: int,
    ) -> str:
        if not parse_success:
            return "teacher_parse_failed"
        if teacher_entity_count == 0:
            return "teacher_returned_no_entities"
        if validated_entity_count == 0:
            return "no_valid_entities_after_validation"
        return "success"
