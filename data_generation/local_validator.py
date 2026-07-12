"""Deterministic validation before an expensive LLM critic call."""
from __future__ import annotations

import re
from typing import Dict, List

from data_generation.config import FAMILY_HISTORY_DIAGNOSIS_CODES, VALID_ASSERTIONS, VALID_ENTITY_TYPES


class LocalSampleValidator:
    def __init__(self, assertion_cues: Dict[str, List[str]]):
        self.assertion_cues = assertion_cues

    def validate(
        self, text: str, entities: List[Dict], challenge_profile: str = "basic"
    ) -> Dict[str, List[str] | bool]:
        errors, warnings = [], []
        for entity in entities:
            entity_type = entity.get("type")
            assertions = entity.get("assertions", [])
            position = entity.get("position", [])
            if entity_type not in VALID_ENTITY_TYPES:
                errors.append("invalid_entity_type")
            if not isinstance(assertions, list) or any(value not in VALID_ASSERTIONS for value in assertions):
                errors.append("invalid_assertion")
            if not self._exact_span(text, entity.get("text", ""), position):
                errors.append("bad_exact_span")
                continue
            for assertion in assertions:
                if not self._has_nearby_cue(text, position, assertion):
                    warnings.append(f"missing_{assertion}_cue")
            if "isFamily" in assertions and not self._family_entity_is_allowed(entity):
                errors.append("invalid_family_semantics")
        errors.extend(self._profile_errors(text, entities, challenge_profile))
        return {"valid": not errors, "errors": errors, "warnings": warnings}

    @staticmethod
    def _profile_errors(text: str, entities: List[Dict], profile: str) -> List[str]:
        if profile == "repeated_mention":
            if not any(entity.get("text") and text.count(entity["text"]) >= 2 for entity in entities):
                return ["missing_repeated_mention"]
        elif profile == "abbreviation_or_typo":
            masked = LocalSampleValidator._mask_entity_spans(text, entities)
            if not re.search(r"\b(?:BN|HA|THA|CRP|WBC|ECG|EEG|MRI|CT|SpO2|PO|IV)\b", masked, re.IGNORECASE):
                return ["missing_medical_abbreviation"]
        elif profile == "mixed_language":
            masked = LocalSampleValidator._mask_entity_spans(text, entities)
            if not re.search(r"\bfollow-up\b", masked, re.IGNORECASE):
                return ["missing_mixed_language_term"]
        return []

    @staticmethod
    def _mask_entity_spans(text: str, entities: List[Dict]) -> str:
        """Ignore mandatory entity strings when validating free-form profile signals."""
        characters = list(text)
        for entity in entities:
            position = entity.get("position", [])
            if isinstance(position, (list, tuple)) and len(position) == 2:
                start, end = position
                if isinstance(start, int) and isinstance(end, int):
                    for index in range(max(0, start), min(len(characters), end)):
                        characters[index] = " "
        return "".join(characters)

    @staticmethod
    def _exact_span(text: str, entity_text: str, position) -> bool:
        return (
            isinstance(position, (list, tuple)) and len(position) == 2
            and isinstance(position[0], int) and isinstance(position[1], int)
            and 0 <= position[0] < position[1] <= len(text)
            and text[position[0]:position[1]] == entity_text
        )

    def _has_nearby_cue(self, text: str, position, assertion: str) -> bool:
        start, end = position
        context = text[max(0, start - 80):min(len(text), end + 80)].lower()
        return any(cue.lower() in context for cue in self.assertion_cues.get(assertion, []))

    @staticmethod
    def _family_entity_is_allowed(entity: Dict) -> bool:
        if entity.get("type") != "CHẨN_ĐOÁN":
            return False
        return any(
            code == allowed or code.split(".")[0] == allowed.split(".")[0]
            for code in entity.get("candidates", [])
            for allowed in FAMILY_HISTORY_DIAGNOSIS_CODES
        )
