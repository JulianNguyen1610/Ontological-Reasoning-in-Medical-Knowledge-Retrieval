"""
Luồng 1: Trích xuất chủ đề lâm sàng từ knowledge seeds
Đảm bảo bao phủ tất cả trường hợp: kết hợp ICD-10, RxNorm, triệu chứng, xét nghiệm
"""
import json
import random
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
from data_generation.config import FAMILY_HISTORY_DIAGNOSIS_CODES
from data_generation.generation_planner import CHALLENGE_PROFILES

@dataclass
class ClinicalScenario:
    """Kịch bản lâm sàng được trích xuất từ knowledge seeds"""
    diagnosis: Dict  # Từ ICD-10 seeds
    drugs: List[Dict]  # Từ RxNorm seeds
    symptoms: List[Dict]  # Từ symptom seeds
    lab_tests: List[Dict]  # Từ test_lab seeds
    assertions: List[str]  # Thuộc tính cần xuất hiện
    text_style: str  # Phong cách văn bản
    complexity: str  # Mức độ phức tạp
    challenge_profile: str = "basic"

class TopicExtractor:
    def __init__(self, seeds_dir: Path):
        self.icd10_seeds = self._load_json(seeds_dir / "icd10_seeds.json")
        self.rxnorm_seeds = self._load_json(seeds_dir / "rxnorm_seeds.json")
        self.symptom_seeds = self._load_json(seeds_dir / "symptom_seeds.json")
        self.lab_seeds = self._load_json(seeds_dir / "test_lab_seeds.json")
        
    def _load_json(self, filepath: Path) -> List[Dict]:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def extract_topic(self, complexity: str = "few_entities", challenge_profile: str = "basic") -> ClinicalScenario:
        """
        Trích xuất một chủ đề lâm sàng dựa trên knowledge seeds
        Đảm bảo tính logic: chẩn đoán ↔ triệu chứng ↔ thuốc ↔ xét nghiệm
        """
        if challenge_profile not in CHALLENGE_PROFILES:
            raise ValueError(f"Unsupported challenge profile: {challenge_profile}")

        if challenge_profile in {"repeated_mention", "lab_name_result_pair", "mixed_language"} and complexity == "single_entity":
            complexity = "few_entities"

        # Family scope needs a diagnosis for which family history is clinically plausible.
        diagnosis_pool = self.icd10_seeds
        if challenge_profile == "family_scope":
            eligible = [seed for seed in self.icd10_seeds if seed.get("code") in FAMILY_HISTORY_DIAGNOSIS_CODES]
            diagnosis_pool = eligible or self.icd10_seeds
        diagnosis = random.choice(diagnosis_pool)
        
        # 2. Chọn triệu chứng liên quan đến chẩn đoán
        related_symptoms = self._get_related_symptoms(diagnosis)
        num_symptoms = self._get_num_entities(complexity, "symptom")
        selected_symptoms = self._select_symptoms(related_symptoms, num_symptoms)
        
        # 3. Chọn thuốc liên quan đến chẩn đoán
        related_drugs = self._get_related_drugs(diagnosis)
        num_drugs = self._get_num_entities(complexity, "drug")
        selected_drugs = self._select_drugs(related_drugs, num_drugs)
        
        # 4. Chọn xét nghiệm liên quan
        related_tests = self._get_related_tests(diagnosis)
        num_tests = self._get_num_entities(complexity, "test")
        selected_tests = self._select_tests(related_tests, num_tests)
        
        # 5. Xác định thuộc tính cần xuất hiện
        assertions = self._select_assertions(diagnosis, challenge_profile)
        
        # 6. Chọn phong cách văn bản
        text_style = random.choice([
            "discharge_summary", "clinical_note", "admission_note",
            "progress_note", "medication_list", "lab_report", "imaging_report"
        ])
        
        if challenge_profile == "lab_name_result_pair" and not selected_tests:
            selected_tests = self._select_tests(related_tests, 1)
        return ClinicalScenario(
            diagnosis=diagnosis,
            drugs=selected_drugs,
            symptoms=selected_symptoms,
            lab_tests=selected_tests,
            assertions=assertions,
            text_style=text_style,
            complexity=complexity,
            challenge_profile=challenge_profile,
        )
    
    def _get_related_symptoms(self, diagnosis: Dict) -> List[Dict]:
        """Lấy triệu chứng liên quan đến chẩn đoán"""
        related_names = diagnosis.get("related_symptoms", [])
        related = [s for s in self.symptom_seeds if s["text"] in related_names]
        
        # Nếu không đủ, bổ sung ngẫu nhiên
        if len(related) < 3:
            extra = random.sample(self.symptom_seeds, min(3, len(self.symptom_seeds)))
            related.extend(extra)
        
        return related
    
    def _get_related_drugs(self, diagnosis: Dict) -> List[Dict]:
        """Lấy thuốc liên quan đến chẩn đoán"""
        related_names = diagnosis.get("related_drugs", [])
        related = [d for d in self.rxnorm_seeds if any(
            name.lower() in d["name_vi"].lower() or 
            name.lower() in d["name_en"].lower() or
            name.lower() in [s.lower() for s in d.get("synonyms", [])]
            for name in related_names
        )]
        
        if len(related) < 2:
            extra = random.sample(self.rxnorm_seeds, min(2, len(self.rxnorm_seeds)))
            related.extend(extra)
        
        return related
    
    def _get_related_tests(self, diagnosis: Dict) -> List[Dict]:
        """Lấy xét nghiệm liên quan đến chẩn đoán"""
        related_names = diagnosis.get("related_tests", [])
        related = [t for t in self.lab_seeds if t["test_name"] in related_names]
        
        if len(related) < 1:
            related = [random.choice(self.lab_seeds)]
        
        return related
    
    def _get_num_entities(self, complexity: str, entity_type: str) -> int:
        """Xác định số lượng thực thể theo độ phức tạp"""
        ranges = {
            "single_entity": {"symptom": 1, "drug": 0, "test": 0},
            "few_entities": {"symptom": (1, 3), "drug": (1, 2), "test": (0, 1)},
            "many_entities": {"symptom": (2, 5), "drug": (2, 4), "test": (1, 2)},
            "complex_mixed": {"symptom": (3, 8), "drug": (3, 6), "test": (2, 4)},
        }
        
        val = ranges.get(complexity, ranges["few_entities"]).get(entity_type, 0)
        if isinstance(val, tuple):
            return random.randint(val[0], val[1])
        return val
    
    def _select_symptoms(self, symptoms: List[Dict], num: int) -> List[Dict]:
        """Chọn triệu chứng, đảm bảo đa dạng"""
        if num == 0:
            return []
        return random.sample(symptoms, min(num, len(symptoms)))
    
    def _select_drugs(self, drugs: List[Dict], num: int) -> List[Dict]:
        """Chọn thuốc, đảm bảo đa dạng"""
        if num == 0:
            return []
        return random.sample(drugs, min(num, len(drugs)))
    
    def _select_tests(self, tests: List[Dict], num: int) -> List[Dict]:
        """Chọn xét nghiệm"""
        if num == 0:
            return []
        return random.sample(tests, min(num, len(tests)))
    
    def _select_assertions(self, diagnosis: Dict, challenge_profile: str = "basic") -> List[str]:
        """Chọn assertion với tỷ lệ đủ cao để tạo dữ liệu huấn luyện cân bằng."""
        profile_assertion = {
            "negation_scope": "isNegated",
            "historical_scope": "isHistorical",
            "family_scope": "isFamily",
        }.get(challenge_profile)
        if profile_assertion:
            if profile_assertion == "isFamily" and diagnosis.get("code") not in FAMILY_HISTORY_DIAGNOSIS_CODES:
                return []
            return [profile_assertion]

        if random.random() < 0.20:
            return []

        if diagnosis.get("code") in FAMILY_HISTORY_DIAGNOSIS_CODES:
            all_assertions = ["isNegated", "isFamily", "isHistorical"]
            weights = [0.30, 0.25, 0.45]
        else:
            all_assertions = ["isNegated", "isHistorical"]
            weights = [0.40, 0.60]
        return [random.choices(all_assertions, weights=weights, k=1)[0]]
    def generate_diverse_scenarios(self, num_samples: int = 10000) -> List[ClinicalScenario]:
        """Sinh tập hợp đa dạng các kịch bản lâm sàng"""
        scenarios = []
        complexities = ["single_entity", "few_entities", "many_entities", "complex_mixed"]
        weights = [0.15, 0.35, 0.30, 0.20]
        
        for _ in range(num_samples):
            complexity = random.choices(complexities, weights=weights, k=1)[0]
            scenario = self.extract_topic(complexity)
            scenarios.append(scenario)
        
        return scenarios
