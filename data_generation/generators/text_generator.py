"""
Sinh văn bản thô từ kịch bản lâm sàng sử dụng Tree of Thought
Đảm bảo chuỗi thực thể được giữ nguyên văn 100%
"""
import json
import random
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class EntityAnnotation:
    """Chú thích thực thể"""
    text: str
    type: str
    assertions: List[str]
    candidates: List[str]
    position: Tuple[int, int] = (0, 0)


@dataclass
class GeneratedSample:
    """Mẫu dữ liệu sinh ra"""
    text: str
    entities: List[EntityAnnotation]
    scenario_id: str


class TextGenerator:
    def __init__(self, llm_client):
        """
        Args:
            llm_client: Client LLM (có thể là OpenAI-compatible local hoặc API)
        """
        self.llm = llm_client
        self.max_retries = 3
        self.last_expected_entity_count = 0
        self.assertion_cues = {
            "isNegated": [
                "không",
                "không có",
                "phủ nhận",
                "chưa ghi nhận",
                "âm tính",
            ],
            "isFamily": [
                "gia đình",
                "người nhà",
                "mẹ",
                "bố",
                "anh chị em",
                "họ hàng",
            ],
            "isHistorical": [
                "tiền sử",
                "trước đây",
                "trong quá khứ",
                "đã từng",
                "ghi nhận trước đó",
            ],
        }
    
    def generate_sample(self, scenario, style_director) -> Optional[GeneratedSample]:
        """
        Sinh một mẫu dữ liệu hoàn chỉnh qua đường ống Tree of Thought.

        Trả None nếu:
        - LLM không sinh được văn bản
        - Văn bản thiếu entity bắt buộc (located < expected)
        - Validation thất bại sau max_retries
        """
        # Bước 1: Tạo danh sách thực thể từ kịch bản
        entities = self._create_entity_list(scenario)
        
        # Bước 2: Sinh văn bản thô
        raw_text = self._generate_raw_text(scenario, entities, style_director)
        
        if not raw_text:
            return None
        
        # Bước 3: Xác định vị trí thực thể trong văn bản
        self.last_expected_entity_count = len(entities)
        positioned_entities = self._locate_entities(raw_text, entities)
        
        # Bước 3.5: Reject nếu thiếu entity bắt buộc
        # Đảm bảo caller trực tiếp cũng bị chặn, không chỉ pipeline.
        if len(positioned_entities) < len(entities):
            return None
        
        # Bước 4: Kiểm tra và sửa lỗi
        for attempt in range(self.max_retries):
            validation = self._validate_sample(raw_text, positioned_entities)
            
            if validation["valid"]:
                return GeneratedSample(
                    text=raw_text,
                    entities=positioned_entities,
                    scenario_id=f"sample_{random.randint(0, 999999)}"
                )
            
            # Sửa lỗi và thử lại
            raw_text, positioned_entities = self._fix_errors(
                raw_text, positioned_entities, validation["errors"], scenario, style_director
            )
        
        return None
    
    def _create_entity_list(self, scenario) -> List[EntityAnnotation]:
        """Tạo danh sách thực thể từ kịch bản lâm sàng"""
        entities = []
        
        # Thêm chẩn đoán
        if scenario.diagnosis:
            assertions = self._assign_assertions_to_entity(
                scenario.assertions,
                scenario.diagnosis["name_vi"],
                "CHẨN_ĐOÁN",
            )
            entities.append(EntityAnnotation(
                text=scenario.diagnosis["name_vi"],
                type="CHẨN_ĐOÁN",
                assertions=assertions,
                candidates=[scenario.diagnosis["code"]],
            ))
        
        # Thêm triệu chứng
        for symptom in scenario.symptoms:
            # Chọn synonym ngẫu nhiên
            text = random.choice([symptom["text"]] + symptom.get("synonyms", []))
            assertions = self._assign_assertions_to_entity(
                scenario.assertions,
                text,
                "TRIỆU_CHỨNG",
            )
            entities.append(EntityAnnotation(
                text=text,
                type="TRIỆU_CHỨNG",
                assertions=assertions,
                candidates=[],  # Triệu chứng không có candidates
            ))
        
        # Thêm thuốc
        for drug in scenario.drugs:
            text = self._format_drug_text(drug)
            assertions = self._assign_assertions_to_entity(
                scenario.assertions,
                text,
                "THUỐC",
            )
            entities.append(EntityAnnotation(
                text=text,
                type="THUỐC",
                assertions=assertions,
                candidates=[drug["rxcui"]],
            ))
        
        # Thêm xét nghiệm
        for test in scenario.lab_tests:
            # Tên xét nghiệm
            test_name = random.choice([test["test_name"]] + test.get("synonyms", []))
            assertions = self._assign_assertions_to_entity(
                scenario.assertions,
                test_name,
                "TÊN_XÉT_NGHIỆM",
            )
            entities.append(EntityAnnotation(
                text=test_name,
                type="TÊN_XÉT_NGHIỆM",
                assertions=assertions,
                candidates=[],
            ))
            
            # Kết quả xét nghiệm
            if random.random() < 0.7:
                result_text = self._format_lab_result(test)
                entities.append(EntityAnnotation(
                    text=result_text,
                    type="KẾT_QUẢ_XÉT_NGHIỆM",
                    assertions=assertions,
                    candidates=[],
                ))
        
        self._ensure_assertion_coverage(entities, scenario.assertions)
        return entities
    
    def _format_drug_text(self, drug: Dict) -> str:
        """Định dạng chuỗi thuốc: tên + liều + đường dùng + tần suất"""
        parts = [drug["name_vi"]]
        
        # Liều
        dose = random.choice(drug.get("common_doses") or [""])
        if dose:
            parts.append(dose)
        
        # Đường dùng
        route = random.choice(drug.get("routes") or ["po"])
        parts.append(route)
        
        # Tần suất
        freq = random.choice(drug.get("frequencies") or ["daily"])
        parts.append(freq)
        
        return " ".join(parts)
    
    def _format_lab_result(self, test: Dict) -> str:
        """Định dạng kết quả xét nghiệm"""
        abn = test.get("abnormal_values") or ["bình thường"]
        value = random.choice(abn)
        units = test.get("units") or [""]
        unit = random.choice(units)
        
        if value == "bình thường":
            return f"{test['test_name']} bình thường"
        elif unit:
            return f"{value} {unit}".strip()
        else:
            return value.strip()
    
    def _assign_assertions_to_entity(
        self,
        scenario_assertions: List[str],
        entity_text: str,
        entity_type: str,
    ) -> List[str]:
        """Gán thuộc tính cho thực thể dựa trên kịch bản"""
        del entity_text

        eligible_by_type = {
            "CHẨN_ĐOÁN": {"isHistorical", "isFamily"},
            "TRIỆU_CHỨNG": {"isNegated", "isHistorical", "isFamily"},
            "THUỐC": {"isHistorical"},
            "TÊN_XÉT_NGHIỆM": {"isNegated", "isHistorical"},
            "KẾT_QUẢ_XÉT_NGHIỆM": {"isHistorical"},
        }
        eligible_assertions = [
            assertion
            for assertion in scenario_assertions
            if assertion in eligible_by_type.get(entity_type, set())
        ]

        if not eligible_assertions or random.random() >= 0.75:
            return []

        return [random.choice(eligible_assertions)]

    def _ensure_assertion_coverage(
        self,
        entities: List[EntityAnnotation],
        scenario_assertions: List[str],
    ) -> None:
        if not entities or any(entity.assertions for entity in entities):
            return

        for preferred_assertion in ["isNegated", "isHistorical", "isFamily"]:
            if preferred_assertion not in scenario_assertions:
                continue
            candidate = self._find_best_assertion_candidate(
                entities,
                preferred_assertion,
            )
            if candidate:
                candidate.assertions = [preferred_assertion]
                return

    def _find_best_assertion_candidate(
        self,
        entities: List[EntityAnnotation],
        assertion: str,
    ) -> Optional[EntityAnnotation]:
        priority_by_assertion = {
            "isNegated": ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM"],
            "isHistorical": ["CHẨN_ĐOÁN", "TRIỆU_CHỨNG", "THUỐC"],
            "isFamily": ["CHẨN_ĐOÁN", "TRIỆU_CHỨNG"],
        }
        for entity_type in priority_by_assertion.get(assertion, []):
            for entity in entities:
                if entity.type == entity_type:
                    return entity
        return None
    
    def _generate_raw_text(
        self, scenario, entities: List[EntityAnnotation], style_director
    ) -> Optional[str]:
        """Sinh văn bản thô từ kịch bản và danh sách thực thể"""
        
        # Tạo prompt
        placement_plan = self._build_entity_placement_plan(entities)
        entity_list = "\n".join([
            (
                f"- '{e.text}' (loại: {e.type}, thuộc tính: {e.assertions}, "
                f"hướng dẫn: {self._build_assertion_instruction(e)})"
            )
            for e in entities
        ])
        placement_list = "\n".join([
            (
                f"- '{plan['text']}' -> phần: {plan['section']}; "
                f"kiểu câu: {plan['sentence_style']}; "
                f"cue bắt buộc: {plan['required_cue']}; "
                f"câu mẫu: {plan['example_sentence']}"
            )
            for plan in placement_plan
        ])
        
        noise_instructions = style_director.generate_noise_instructions(0.3)
        
        prompt = f"""Bạn là một bác sĩ đang ghi chú bệnh án. 
Hãy chuyển kịch bản sau thành văn bản y khoa có cấu trúc theo 3 phần chính (sử dụng định dạng danh sách và gạch đầu dòng cho các mục con như mẫu bệnh án thực tế), theo phong cách {scenario.text_style}.

Kịch bản bệnh lý: Bệnh nhân mắc {scenario.diagnosis['name_vi']}, có các triệu chứng và được điều trị.

YÊU CẦU ĐỊNH DẠNG CẤU TRÚC (BẮT BUỘC):
Văn bản của bạn PHẢI chứa đầy đủ 3 phần sau với các tiêu đề chính xác:

1. Tiền sử bệnh
   (Mô tả tiền sử bệnh lý, các thuốc đã sử dụng trước khi nhập viện, hoặc các yếu tố nguy cơ)

2. Tiền sử bệnh hiện tại
   (Mô tả lý do nhập viện, diễn biến các triệu chứng, và các sự kiện xảy ra trước khi nhập viện)

3. Đánh giá tại bệnh viện
   (Mô tả kết quả khám lâm sàng, kết quả cận lâm sàng như xét nghiệm hay chẩn đoán hình ảnh, và các thủ thuật y tế đã thực hiện tại bệnh viện)

Danh sách thực thể BẮT BUỘC phải xuất hiện trong văn bản (giữ NGUYÊN VĂN chuỗi text và đặt vào các phần phù hợp):
{entity_list}

Kế hoạch đặt thực thể theo section và ngữ cảnh (PHẢI tuân thủ):
{placement_list}

YÊU CẦU NGHIÊM NGẶT:
1. PHẢI giữ NGUYÊN VĂN chuỗi text của mỗi thực thể - KHÔNG thêm, bớt, sửa bất kỳ ký tự nào
2. Văn bản phải tự nhiên, giống ghi chú bác sĩ thực tế
3. Có thể dùng từ viết tắt, ký hiệu chuyên ngành
4. Không cần cấu trúc ngữ pháp hoàn chỉnh
5. Các thực thể phải xuất hiện theo thứ tự logic trong văn bản
6. Nếu thực thể có thuộc tính isNegated: phải dùng từ/cụm phủ định ở ngay gần thực thể (không, không có, phủ nhận, chưa ghi nhận)
7. Nếu thực thể có thuộc tính isFamily: phải nhắc đến người nhà/gia đình ở ngay gần thực thể
8. Nếu thực thể có thuộc tính isHistorical: phải nhắc đến tiền sử/quá khứ ở ngay gần thực thể
9. Không được gán ngữ cảnh phủ định cho thuốc đang dùng hiện tại
10. Không được gộp nhiều thực thể có thuộc tính khác nhau vào cùng một câu mơ hồ
11. Với mỗi dòng trong kế hoạch đặt thực thể, hãy viết ít nhất một câu hoặc bullet riêng đủ để thể hiện đúng cue bắt buộc
12. Ưu tiên viết các thực thể có assertion trước, sau đó mới nối các thực thể không assertion

{noise_instructions}

Trả về CHỈ văn bản thô theo đúng cấu trúc 3 phần trên, không kèm giải thích hay markdown."""
        
        # Gọi LLM
        response = self.llm.call_text_gen(
            prompt,
            system_prompt="Bạn là bác sĩ viết báo cáo y khoa...",
            temperature=0.7,
            max_tokens=800
        )
        
        if response:
            # Làm sạch response
            text = response.strip()
            text = text.replace("```", "").strip()
            return text
        
        return None

    def _build_assertion_instruction(self, entity: EntityAnnotation) -> str:
        if "isNegated" in entity.assertions:
            return "đặt trong câu phủ định rõ ràng ngay gần thực thể"
        if "isFamily" in entity.assertions:
            return "đặt trong ngữ cảnh gia đình/người nhà ngay gần thực thể"
        if "isHistorical" in entity.assertions:
            return "đặt trong ngữ cảnh tiền sử/quá khứ ngay gần thực thể"
        return "không cần ngữ cảnh đặc biệt"

    def _build_entity_placement_plan(
        self, entities: List[EntityAnnotation]
    ) -> List[Dict[str, str]]:
        plan = []
        for entity in entities:
            plan.append({
                "text": entity.text,
                "section": self._select_section_for_entity(entity),
                "sentence_style": self._select_sentence_style(entity),
                "required_cue": self._select_required_cue(entity),
                "example_sentence": self._build_example_sentence(entity),
            })
        return plan

    def _select_section_for_entity(self, entity: EntityAnnotation) -> str:
        if "isFamily" in entity.assertions or "isHistorical" in entity.assertions:
            return "1. Tiền sử bệnh"
        if "isNegated" in entity.assertions:
            return "2. Tiền sử bệnh hiện tại"
        if entity.type in {"THUỐC", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"}:
            return "3. Đánh giá tại bệnh viện"
        if entity.type == "CHẨN_ĐOÁN":
            return "3. Đánh giá tại bệnh viện"
        return "2. Tiền sử bệnh hiện tại"

    def _select_sentence_style(self, entity: EntityAnnotation) -> str:
        if "isNegated" in entity.assertions:
            return "bullet hoặc câu ngắn phủ nhận riêng"
        if "isFamily" in entity.assertions:
            return "bullet mô tả tiền sử gia đình riêng"
        if "isHistorical" in entity.assertions:
            return "bullet mô tả tiền sử/quá khứ riêng"
        if entity.type == "THUỐC":
            return "bullet điều trị hoặc thuốc"
        if entity.type in {"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"}:
            return "bullet cận lâm sàng"
        return "bullet triệu chứng/chẩn đoán"

    def _select_required_cue(self, entity: EntityAnnotation) -> str:
        if "isNegated" in entity.assertions:
            return "một trong các cụm: không, không có, phủ nhận, chưa ghi nhận"
        if "isFamily" in entity.assertions:
            return "một trong các cụm: gia đình, người nhà, mẹ, bố, anh chị em"
        if "isHistorical" in entity.assertions:
            return "một trong các cụm: tiền sử, trước đây, trong quá khứ, đã từng"
        if entity.type == "THUỐC":
            return "nêu rõ là thuốc đang dùng hoặc được chỉ định"
        if entity.type in {"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"}:
            return "đặt trong ngữ cảnh xét nghiệm/cận lâm sàng"
        return "không bắt buộc cue đặc biệt"

    def _build_example_sentence(self, entity: EntityAnnotation) -> str:
        if "isNegated" in entity.assertions:
            return f"BN phủ nhận {entity.text}."
        if "isFamily" in entity.assertions:
            return f"Gia đình ghi nhận mẹ bệnh nhân có tiền sử {entity.text}."
        if "isHistorical" in entity.assertions:
            if entity.type == "THUỐC":
                return f"Tiền sử trước đây đã dùng {entity.text}."
            return f"Tiền sử ghi nhận {entity.text}."
        if entity.type == "THUỐC":
            return f"Chỉ định {entity.text}."
        if entity.type in {"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"}:
            return f"Cận lâm sàng ghi nhận {entity.text}."
        return f"Ghi nhận {entity.text}."
    
    def _locate_entities(
        self, text: str, entities: List[EntityAnnotation]
    ) -> List[EntityAnnotation]:
        positioned: List[EntityAnnotation] = []
        used: List[tuple] = []

        def _overlap(a, b):
            return not (a[1] <= b[0] or a[0] >= b[1])

        for entity in entities:
            target = entity.text
            span = None
            start = 0
            while True:
                pos = text.find(target, start)
                if pos < 0:
                    break
                end = pos + len(target)
                if not any(_overlap((pos, end), u) for u in used):
                    span = (pos, end)
                    used.append(span)
                    break
                start = pos + 1
            if span is None:
                fuzzy = self._fuzzy_find(text, target)
                if fuzzy and not any(_overlap(fuzzy, u) for u in used):
                    span = fuzzy
                    used.append(span)
            if span:
                positioned.append(EntityAnnotation(
                    text=target,
                    type=entity.type,
                    assertions=entity.assertions,
                    candidates=entity.candidates,
                    position=span,
                ))

        return positioned

    def _fuzzy_find(self, text: str, query: str) -> Optional[Tuple[int, int]]:
        """Tìm mờ vị trí thực thể trong văn bản"""
        # Sử dụng difflib để tìm tương đồng
        import difflib
        
        query_len = len(query)
        best_ratio = 0
        best_pos = None
        
        # Trượt cửa sổ trên văn bản
        for i in range(len(text) - query_len + 1):
            window = text[i:i + query_len]
            ratio = difflib.SequenceMatcher(None, query, window).ratio()
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_pos = (i, i + query_len)
        
        if best_ratio > 0.85 and best_pos:
            return best_pos
        
        return None
    
    def _validate_sample(
        self, text: str, entities: List[EntityAnnotation]
    ) -> Dict:
        """Kiểm tra tính hợp lệ của mẫu"""
        errors = []
        
        for i, entity in enumerate(entities):
            # Kiểm tra text có khớp với position
            start, end = entity.position
            actual_text = text[start:end]
            
            if actual_text != entity.text:
                errors.append({
                    "entity_index": i,
                    "error_type": "text_mismatch",
                    "detail": f"Expected '{entity.text}' but found '{actual_text}' at position [{start}, {end}]",
                    "suggestion": f"Update text to '{actual_text}' or fix position"
                })
            
            # Kiểm tra type hợp lệ
            if entity.type not in ["TRIỆU_CHỨNG", "TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM", "CHẨN_ĐOÁN", "THUỐC"]:
                errors.append({
                    "entity_index": i,
                    "error_type": "type_error",
                    "detail": f"Invalid type: {entity.type}",
                    "suggestion": "Use one of: TRIỆU_CHỨNG, TÊN_XÉT_NGHIỆM, KẾT_QUẢ_XÉT_NGHIỆM, CHẨN_ĐOÁN, THUỐC"
                })
            
            # Kiểm tra assertions hợp lệ
            for assertion in entity.assertions:
                if assertion not in ["isNegated", "isFamily", "isHistorical"]:
                    errors.append({
                        "entity_index": i,
                        "error_type": "assertion_error",
                        "detail": f"Invalid assertion: {assertion}",
                        "suggestion": "Use one of: isNegated, isFamily, isHistorical"
                    })
                elif not self._assertion_context_is_valid(text, entity):
                    errors.append({
                        "entity_index": i,
                        "error_type": "assertion_context_error",
                        "detail": (
                            f"Assertion context mismatch for '{entity.text}' "
                            f"with assertions {entity.assertions}"
                        ),
                        "suggestion": (
                            "Regenerate the local sentence so the assertion is "
                            "stated explicitly near the entity"
                        ),
                    })
        
        return {"valid": len(errors) == 0, "errors": errors}

    def _assertion_context_is_valid(
        self, text: str, entity: EntityAnnotation
    ) -> bool:
        if not entity.assertions:
            return True

        start, end = entity.position
        context = text[max(0, start - 80):min(len(text), end + 80)].lower()

        for assertion in entity.assertions:
            cues = self.assertion_cues.get(assertion, [])
            if not any(cue in context for cue in cues):
                return False

        return True
    
    def _fix_errors(
        self, text: str, entities: List[EntityAnnotation], errors: List[Dict],
        scenario, style_director
    ) -> Tuple[str, List[EntityAnnotation]]:
        """Sửa lỗi và regenerate"""
        if any(error["error_type"] != "text_mismatch" for error in errors):
            regenerated_text = self._generate_raw_text(scenario, entities, style_director)
            if not regenerated_text:
                return text, entities
            return regenerated_text, self._locate_entities(regenerated_text, entities)

        # Cố gắng sửa vị trí
        for error in errors:
            if error["error_type"] == "text_mismatch":
                idx = error["entity_index"]
                start, end = entities[idx].position
                actual_text = text[start:end]
                # Cập nhật text thực thể thành text thực tế trong văn bản
                entities[idx] = EntityAnnotation(
                    text=actual_text,
                    type=entities[idx].type,
                    assertions=entities[idx].assertions,
                    candidates=entities[idx].candidates,
                    position=entities[idx].position
                )
        
        return text, entities
