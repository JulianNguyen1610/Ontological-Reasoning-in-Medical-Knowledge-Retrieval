"""
Script chạy sinh dữ liệu nhân tạo
"""
import sys
import os
from pathlib import Path

# Thêm project root vào path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_generation.config import GenerationConfig, SEEDS_DIR
from data_generation.pipeline import DataGenerationPipeline, validate_coverage

class MockLLMClient:
    """Mock LLM Client cho testing không cần GPU"""
    
    def generate(self, prompt: str, temperature: float = 0.7, max_tokens: int = 500) -> str:
        """
        Mock generate - thay thế bằng LLM thực tế khi deploy
        """
        # Đây là nơi bạn tích hợp LLM thực tế
        # Có thể dùng: vLLM, Ollama, transformers, v.v.
        
        # Ví dụ mock: sinh văn bản đơn giản
        import random
        
        # Phân tích prompt để sinh response phù hợp
        if "kịch bản" in prompt.lower() or "scenario" in prompt.lower():
            return self._mock_scenario_response(prompt)
        elif "văn bản thô" in prompt.lower() or "raw text" in prompt.lower():
            return self._mock_text_response(prompt)
        else:
            return self._mock_generic_response(prompt)
    
    def _mock_scenario_response(self, prompt: str) -> str:
        """Mock response cho sinh kịch bản"""
        import json
        import random
        
        scenarios = [
            {
                "scenario": "Bệnh nhân 65 tuổi, nam, nhập viện vì đau ngực",
                "entities": [
                    {
                        "text": "đau ngực",
                        "type": "TRIỆU_CHỨNG",
                        "assertions": [],
                        "candidates": [],
                        "context": "than phiền đau ngực"
                    },
                    {
                        "text": "nhồi máu cơ tim cấp",
                        "type": "CHẨN_ĐOÁN",
                        "assertions": [],
                        "candidates": ["I21.9"],
                        "context": "chẩn đoán nhồi máu cơ tim cấp"
                    },
                    {
                        "text": "aspirin 81 mg po daily",
                        "type": "THUỐC",
                        "assertions": ["isHistorical"],
                        "candidates": ["243670"],
                        "context": "điều trị aspirin"
                    }
                ]
            }
        ]
        
        return json.dumps(random.choice(scenarios), ensure_ascii=False)
    
    def _mock_text_response(self, prompt: str) -> str:
        """Mock response cho sinh văn bản"""
        import random
        
        texts = [
            "BN 65t nam, NV vì đau ngực dữ dội 2h trước. TS: THA 10 năm, ĐTĐ type 2 5 năm. "
            "Khám: đau ngực trái, vã mồ hôi, khó thở. HA 160/95, HR 110, SpO2 92%. "
            "ECG: ST chênh lên. Troponin 2.5 ng/mL. CD: nhồi máu cơ tim cấp. "
            "Điều trị: aspirin 81 mg po daily, clopidogrel 75 mg po daily, atorvastatin 40 mg po qhs. "
            "Dặn BN nghỉ ngơi, theo dõi monitor.",
            
            "BN 55t nữ, NV vì đau thượng vị, ợ hơi 1 tuần. "
            "TS: viêm loét dạ dày 3 năm trước. "
            "Khám: đau thượng vị, ợ chua. "
            "CD: trào ngược dạ dày thực quản. "
            "Điều trị: omeprazole 20 mg po daily, aluminum hydroxide 10 ml po prn. "
            "Nội soi dạ dày: viêm thực quản cấp độ B.",
            
            "BN 70t nam, NV vì khó thở, ho đờm xanh 3 ngày. "
            "TS: hen suyễn 20 năm, hút thuốc lá 40 năm. "
            "Khám: khó thở, khò khè, ho đờm xanh. SpO2 88%, RR 28. "
            "X-quang phổi: đậm độ tăng 2 đáy phổi. "
            "CBC: WBC 15.2 G/L. CRP 85 mg/L. "
            "CD: viêm phổi. "
            "Điều trị: amoxicillin 1g po bid, salbutamol 2.5 mg nebulizer q6h, "
            "budesonide 0.5 mg nebulizer bid. "
            "Dặn BN nghỉ ngơi, uống đủ nước."
        ]
        
        return random.choice(texts)
    
    def _mock_generic_response(self, prompt: str) -> str:
        """Mock response generic"""
        return "Bệnh nhân nhập viện vì đau ngực. Chẩn đoán nhồi máu cơ tim cấp. Điều trị aspirin 81 mg po daily."


def main():
    """Hàm main - chạy pipeline sinh dữ liệu"""
    
    # Cấu hình
    config = GenerationConfig(
        num_samples=100,  # Bắt đầu với 100 mẫu để test
        max_retries=3,
    )
    
    # Đường dẫn
    output_dir = project_root / "data" / "raw_generated"
    seeds_dir = project_root / "data_generation" / "knowledge_seeds"
    
    # Khởi tạo LLM client
    # Thay thế bằng LLM thực tế khi deploy
    llm_client = MockLLMClient()
    
    # Khởi tạo pipeline
    pipeline = DataGenerationPipeline(
        config=config,
        llm_client=llm_client,
        output_dir=output_dir,
        seeds_dir=seeds_dir
    )
    
    # Chạy pipeline
    samples = pipeline.run(num_samples=config.num_samples)
    
    # Kiểm tra độ phủ
    coverage = validate_coverage(samples)
    
    print("\n" + "="*60)
    print("KẾT QUẢ SINH DỮ LIỆU")
    print("="*60)
    print(f"Tổng số mẫu: {coverage['total_samples']}")
    print(f"Tổng số thực thể: {coverage['total_entities']}")
    print(f"Trung bình thực thể/mẫu: {coverage['avg_entities_per_sample']:.2f}")
    print("\nPhân phối loại thực thể:")
    for etype, count in coverage['entity_types'].items():
        print(f"  {etype}: {count}")
    print("\nPhân phối thuộc tính:")
    for assertion, count in coverage['assertions'].items():
        print(f"  {assertion}: {count}")
    
    if coverage['missing_entity_types']:
        print(f"\n⚠️  Thiếu loại thực thể: {coverage['missing_entity_types']}")
    if coverage['missing_assertions']:
        print(f"⚠️  Thiếu thuộc tính: {coverage['missing_assertions']}")
    
    print("\n" + "="*60)
    print(f"Dữ liệu đã lưu tại: {output_dir}")
    print("="*60)


if __name__ == "__main__":
    main()