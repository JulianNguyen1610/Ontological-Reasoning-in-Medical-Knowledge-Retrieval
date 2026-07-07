"""
Sinh văn bản thô từ kịch bản lâm sàng sử dụng Tree of Thought
Đảm bảo chuỗi thực thể được giữ nguyên văn 100%
"""
import json
import random
from typing import Dict, List, Tuple, Optional  # <-- Thêm Optional
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
    
    def generate_sample(self, scenario, style_director) -> Optional[GeneratedSample]:
        """
        Sinh một mẫu dữ liệu hoàn chỉnh qua đường ống Tree of Thought
        """
        # Bước 1: Tạo danh sách thực thể từ kịch bản
        entities = self._create_entity_list(scenario)
        
        # Bước 2: Sinh văn bản thô
        raw_text = self._generate_raw_text(scenario, entities, style_director)
        
        if not raw_text:
            return None
        
        # Bước 3: Xác định vị trí thực thể trong văn bản
        positioned_entities = self._locate_entities(raw_text, entities)
        
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
                scenario.assertions, scenario.diagnosis["name_vi"]
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
                scenario.assertions, text
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
                scenario.assertions, text
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
                scenario.assertions, test_name
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
        
        if unit and value != "bình thường":
            return f"{value}"
        elif value == "bình thường":
            return f"{test['test_name']} bình thường"
        else:
            return f"{value} {unit}"
    
    def _assign_assertions_to_entity(
        self, scenario_assertions: List[str], entity_text: str
    ) -> List[str]:
        """Gán thuộc tính cho thực thể dựa trên kịch bản"""
        assigned = []
        
        for assertion in scenario_assertions:
            if random.random() < 0.4:  # 40% cơ hội mỗi thuộc tính được gán
                assigned.append(assertion)
        
        return assigned
    
    def _generate_raw_text(
        self, scenario, entities: List[EntityAnnotation], style_director
    ) -> Optional[str]:
        """Sinh văn bản thô từ kịch bản và danh sách thực thể"""
        
        # Tạo prompt
        entity_list = "\n".join([
            f"- '{e.text}' (loại: {e.type}, thuộc tính: {e.assertions})"
            for e in entities
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

YÊU CẦU NGHIÊM NGẶT:
1. PHẢI giữ NGUYÊN VĂN chuỗi text của mỗi thực thể - KHÔNG thêm, bớt, sửa bất kỳ ký tự nào
2. Văn bản phải tự nhiên, giống ghi chú bác sĩ thực tế
3. Có thể dùng từ viết tắt, ký hiệu chuyên ngành
4. Không cần cấu trúc ngữ pháp hoàn chỉnh
5. Các thực thể phải xuất hiện theo thứ tự logic trong văn bản
6. Nếu thực thể có thuộc tính isNegated: phải dùng ngữ cảnh phủ định (không, không có, phủ nhận)
7. Nếu thực thể có thuộc tính isFamily: phải nhắc đến người nhà/gia đình
8. Nếu thực thể có thuộc tính isHistorical: phải nhắc đến tiền sử/quá khứ

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
        
        return {"valid": len(errors) == 0, "errors": errors}
    
    def _fix_errors(
        self, text: str, entities: List[EntityAnnotation], errors: List[Dict],
        scenario, style_director
    ) -> Tuple[str, List[EntityAnnotation]]:
        """Sửa lỗi và regenerate"""
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