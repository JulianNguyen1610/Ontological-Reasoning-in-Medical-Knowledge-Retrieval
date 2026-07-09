"""
Pipeline sinh dữ liệu nhân tạo định hướng tri thức hoàn chỉnh
Kết hợp: Topic Extractor + Style Director + Text Generator + Critic Agent
"""
import logging
import json
import random
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional
from tqdm import tqdm

from data_generation.config import GenerationConfig, VALID_ENTITY_TYPES, VALID_ASSERTIONS
from data_generation.generators.topic_extractor import TopicExtractor
from data_generation.generators.style_director import StyleDirector
from data_generation.generators.text_generator import TextGenerator, GeneratedSample
from data_generation.generators.critic_agent import CriticAgent

# Cấu hình logging với UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except AttributeError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_generation.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)  # Dùng sys.stdout thay vì stderr
    ]
)
logger = logging.getLogger(__name__)

class DataGenerationPipeline:
    """Pipeline sinh dữ liệu nhân tạo hoàn chỉnh"""
    
    def __init__(
        self,
        config: GenerationConfig,
        llm_client,
        output_dir: Path,
        seeds_dir: Path
    ):
        self.config = config
        self.llm = llm_client
        self.output_dir = output_dir
        self.seeds_dir = seeds_dir
        
        # Thêm timestamp cho mỗi lượt chạy
        import datetime
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Khởi tạo các thành phần
        self.topic_extractor = TopicExtractor(seeds_dir)
        self.style_director = StyleDirector()
        self.text_generator = TextGenerator(llm_client)
        self.critic = CriticAgent(llm_client)
        
        # Thống kê
        self.stats = {
            "total_generated": 0,
            "valid_samples": 0,
            "invalid_samples": 0,
            "retry_count": 0,
            "entity_type_distribution": {t: 0 for t in VALID_ENTITY_TYPES},
            "assertion_distribution": {a: 0 for a in VALID_ASSERTIONS},
        }
    
    def run(self, num_samples: int = None) -> List[Dict]:
        """Chạy pipeline sinh dữ liệu"""
        num_samples = num_samples or self.config.num_samples
        logger.info(f"Bắt đầu sinh {num_samples} mẫu dữ liệu...")
        
        all_samples = []
        
        for i in tqdm(range(num_samples), desc="Sinh dữ liệu"):
            sample = self._generate_single_sample()
            
            if sample:
                all_samples.append(sample)
                self.stats["valid_samples"] += 1
            else:
                self.stats["invalid_samples"] += 1
            
            self.stats["total_generated"] += 1
            
            # Lưu checkpoint mỗi 1000 mẫu
            if (i + 1) % 1000 == 0:
                self._save_checkpoint(all_samples, i + 1)
                logger.info(f"Đã sinh {i + 1}/{num_samples}. Hợp lệ: {self.stats['valid_samples']}")
        
        # Lưu kết quả cuối cùng
        self._save_final_output(all_samples)
        self._save_stats()
        
        logger.info(f"Hoàn thành! Sinh {len(all_samples)} mẫu hợp lệ.")
        return all_samples
    
    def _generate_single_sample(self) -> Optional[Dict]:
        """Sinh một mẫu dữ liệu đơn lẻ"""
        max_retries = self.config.max_retries
        
        for attempt in range(max_retries):
            try:
                # Bước 1: Trích xuất chủ đề
                complexity = self._select_complexity()
                scenario = self.topic_extractor.extract_topic(complexity)
                
                # Bước 2: Sinh văn bản
                sample = self.text_generator.generate_sample(scenario, self.style_director)
                
                if not sample:
                    self.stats["retry_count"] += 1
                    continue
                
                # Bước 2.5: Kiểm tra entity bắt buộc
                expected_count = self.text_generator.last_expected_entity_count
                located_count = len(sample.entities)
                if located_count < expected_count:
                    logger.warning(
                        f"Missing entities: located {located_count}/{expected_count}. "
                        f"Rejecting sample (attempt {attempt})."
                    )
                    self.stats["retry_count"] += 1
                    continue
                
                # Bước 3: Critic Agent kiểm duyệt
                entities_dict = [self._entity_to_dict(e) for e in sample.entities]
                critic_result = self.critic.review_sample(sample.text, entities_dict)
                
                if critic_result.is_valid:
                    # whitelist filter schema
                    from data_generation.utils.cleanup import clean_sample
                    cleaned = clean_sample(self._sample_to_dict(sample))
                    if not cleaned['entities']:
                        self.stats['retry_count'] += 1
                        continue
                    sample.entities = [self._dict_to_entity(e) for e in cleaned['entities']]
                    self._update_stats(sample)
                    return self._sample_to_dict(sample)
                else:
                    # Thử auto-fix
                    text, fixed_entities = self.critic.auto_fix(
                        sample.text, entities_dict, critic_result.errors
                    )
                    
                    # Kiểm tra lại
                    re_check = self.critic.review_sample(text, fixed_entities)
                    if re_check.is_valid:
                        sample.text = text
                        sample.entities = [self._dict_to_entity(e) for e in fixed_entities]
                        # whitelist filter schema
                        from data_generation.utils.cleanup import clean_sample
                        cleaned = clean_sample(self._sample_to_dict(sample))
                        if not cleaned['entities']:
                            self.stats['retry_count'] += 1
                            continue
                        sample.entities = [self._dict_to_entity(e) for e in cleaned['entities']]
                        self._update_stats(sample)
                        return self._sample_to_dict(sample)
                    
                    self.stats["retry_count"] += 1
                    
            except Exception as e:
                logger.warning(f"Lỗi khi sinh mẫu (attempt {attempt}): {e}")
                continue
        
        return None
    
    def _select_complexity(self) -> str:
        """Chọn độ phức tạp theo phân phối"""
        complexities = list(self.config.scenario_distribution.keys())
        weights = list(self.config.scenario_distribution.values())
        return random.choices(complexities, weights=weights, k=1)[0]
    
    def _entity_to_dict(self, entity) -> Dict:
        """Chuyển EntityAnnotation thành dict"""
        return {
            "text": entity.text,
            "type": entity.type,
            "assertions": entity.assertions,
            "candidates": entity.candidates,
            "position": list(entity.position)
        }
    
    def _dict_to_entity(self, d: Dict):
        """Chuyển dict thành EntityAnnotation"""
        from data_generation.generators.text_generator import EntityAnnotation
        return EntityAnnotation(
            text=d["text"],
            type=d["type"],
            assertions=d["assertions"],
            candidates=d["candidates"],
            position=tuple(d["position"])
        )
    
    def _sample_to_dict(self, sample: GeneratedSample) -> Dict:
        """Chuyển GeneratedSample thành dict"""
        return {
            "text": sample.text,
            "entities": [self._entity_to_dict(e) for e in sample.entities],
            "scenario_id": sample.scenario_id
        }
    
    def _update_stats(self, sample: GeneratedSample):
        """Cập nhật thống kê"""
        for entity in sample.entities:
            if entity.type in self.stats["entity_type_distribution"]:
                self.stats["entity_type_distribution"][entity.type] += 1
            
            for assertion in entity.assertions:
                if assertion in self.stats["assertion_distribution"]:
                    self.stats["assertion_distribution"][assertion] += 1
    
    def _save_checkpoint(self, samples: List[Dict], count: int):
        """Lưu checkpoint"""
        checkpoint_dir = self.output_dir / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = checkpoint_dir / f"checkpoint_{self.timestamp}_{count}.json"
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(samples, f, ensure_ascii=False, indent=2)
    
    def _save_final_output(self, samples: List[Dict]):
        """Lưu kết quả cuối cùng"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Lưu tất cả dưới dạng JSONL (mỗi dòng 1 sample)
        jsonl_path = self.output_dir / f"training_data_{self.timestamp}.jsonl"
        with open(jsonl_path, 'w', encoding='utf-8') as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')
        
        # Lưu dưới dạng JSON (list)
        json_path = self.output_dir / f"training_data_{self.timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(samples, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Đã lưu {len(samples)} mẫu vào {json_path}")
    
    def _save_stats(self):
        """Lưu thống kê"""
        stats_path = self.output_dir / f"generation_stats_{self.timestamp}.json"
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Thống kê: {json.dumps(self.stats, ensure_ascii=False, indent=2)}")


def validate_coverage(samples: List[Dict]) -> Dict:
    """Kiểm tra độ phủ của tập dữ liệu sinh ra"""
    coverage = {
        "entity_types": {t: 0 for t in VALID_ENTITY_TYPES},
        "assertions": {a: 0 for a in VALID_ASSERTIONS},
        "text_styles": {},
        "complexities": {},
        "total_entities": 0,
        "total_samples": len(samples),
        "avg_entities_per_sample": 0,
    }
    
    for sample in samples:
        entities = sample.get("entities", [])
        coverage["total_entities"] += len(entities)
        
        for entity in entities:
            # Đếm loại thực thể
            if entity["type"] in coverage["entity_types"]:
                coverage["entity_types"][entity["type"]] += 1
            
            # Đếm thuộc tính
            for assertion in entity.get("assertions", []):
                if assertion in coverage["assertions"]:
                    coverage["assertions"][assertion] += 1
    
    if coverage["total_samples"] > 0:
        coverage["avg_entities_per_sample"] = coverage["total_entities"] / coverage["total_samples"]
    
    # Kiểm tra missing types
    coverage["missing_entity_types"] = [
        t for t, count in coverage["entity_types"].items() if count == 0
    ]
    coverage["missing_assertions"] = [
        a for a, count in coverage["assertions"].items() if count == 0
    ]
    
    return coverage