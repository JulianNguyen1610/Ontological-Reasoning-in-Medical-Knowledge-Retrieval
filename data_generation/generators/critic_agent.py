"""
Critic Agent: Tác nhân phản biện độc lập
Kiểm tra chéo xem chuỗi văn bản trong dữ liệu cấu trúc có khớp hoàn toàn với văn bản thô không
"""
import json
import re
from typing import Dict, List, Tuple
from dataclasses import dataclass

@dataclass
class CriticResult:
    """Kết quả kiểm duyệt"""
    is_valid: bool
    errors: List[str]
    suggestions: List[str]

class CriticAgent:
    def __init__(self, llm_client):
        self.llm = llm_client
    
    def _clean_json_response(self, response: str) -> str:
        """Trích xuất khối JSON từ response của LLM (nếu có markdown codeblock hoặc text thừa)"""
        response = response.strip()
        # Tìm ```json ... ``` hoặc ``` ... ```
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Nếu không tìm thấy markdown block, cố gắng tìm cặp ngoặc nhọn đầu tiên và cuối cùng
        start_idx = response.find("{")
        end_idx = response.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            return response[start_idx:end_idx+1].strip()
        return response

    def review_sample(self, text: str, entities: List[Dict]) -> CriticResult:
        prompt = self._build_review_prompt(text, entities)
        system_prompt = (
            "You are a critic agent for medical text validation. "
            "You must ALWAYS respond with a single valid JSON object. "
            "Do not include any chat prefix, suffix, or markdown formatting other than the JSON block. "
            "Expected JSON format:\n"
            "{\n"
            '  "is_valid": true|false,\n'
            '  "errors": ["error message 1", ...],\n'
            '  "suggestions": ["suggestion 1", ...]\n'
            "}"
        )
        
        try:
            response = self.llm.call_critic(prompt, system_prompt)
            cleaned_response = self._clean_json_response(response)
            return self._parse_review_response(cleaned_response)
        except Exception as e:
            print(f"Critic error: {e}")
            return CriticResult(is_valid=False, errors=[str(e)], suggestions=[])
    
    def auto_fix(self, text: str, entities: List[Dict], errors: List[str]):
        prompt = self._build_fix_prompt(text, entities, errors)
        system_prompt = (
            "You are a critic agent that fixes medical text annotations. "
            "You must ALWAYS respond with a single valid JSON object. "
            "Do not include any chat prefix, suffix, or markdown formatting other than the JSON block. "
            "Expected JSON format:\n"
            "{\n"
            '  "text": "the corrected text here",\n'
            '  "entities": [\n'
            "    {\n"
            '      "text": "entity text",\n'
            '      "type": "entity type",\n'
            '      "assertions": [...],\n'
            '      "candidates": [...],\n'
            '      "position": [start, end]\n'
            "    }, ...\n"
            '  ]\n'
            "}"
        )
        
        try:
            response = self.llm.call_critic(prompt, system_prompt)
            cleaned_response = self._clean_json_response(response)
            fixed_data = json.loads(cleaned_response)
            return fixed_data["text"], fixed_data["entities"]
        except Exception as e:
            print(f"Auto-fix error: {e}")
            return text, entities
    
    def _build_review_prompt(self, text: str, entities: List[Dict]) -> str:
        return (
            "Review this medical text and the list of annotated entities to verify if the annotations are correct.\n"
            f"Text: {text}\n"
            f"Entities: {json.dumps(entities, ensure_ascii=False)}\n\n"
            "Requirements:\n"
            "1. 'is_valid' must be true only if all entities are correctly annotated and their texts exist exactly in the text.\n"
            "2. If there are mismatches, list them in the 'errors' array and provide solutions in 'suggestions'.\n"
            "Respond ONLY with a valid JSON object matching the requested schema."
        )
    
    def _build_fix_prompt(self, text: str, entities: List[Dict], errors: List[str]) -> str:
        return (
            "Fix the annotations/text for the following medical sample based on the errors reported.\n"
            f"Original Text: {text}\n"
            f"Original Entities: {json.dumps(entities, ensure_ascii=False)}\n"
            f"Errors: {json.dumps(errors, ensure_ascii=False)}\n\n"
            "Requirements:\n"
            "1. Make minimum edits to align the entities with the text.\n"
            "2. Ensure positions [start, end] exactly match the character offsets in the returned 'text'.\n"
            "Respond ONLY with a valid JSON object matching the requested schema."
        )
    
    def _parse_review_response(self, response: str) -> CriticResult:
        data = json.loads(response)
        return CriticResult(
            is_valid=data["is_valid"],
            errors=data.get("errors", []),
            suggestions=data.get("suggestions", [])
        )