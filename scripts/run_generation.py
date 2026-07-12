"""
Script chạy sinh dữ liệu nhân tạo
"""
import sys
import os
import json
import random
from pathlib import Path

# Thêm project root vào path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_generation.config import GenerationConfig, SEEDS_DIR
from data_generation.pipeline import DataGenerationPipeline, validate_coverage


class MockLLMClient:
    """Mock LLM Client cho testing không cần GPU/API key.

    Cung cấp đúng interface mà pipeline yêu cầu:
    - call_text_gen(prompt, system_prompt, temperature, max_tokens)
    - call_critic(prompt, system_prompt, ...)
    """

    # ------------------------------------------------------------------ #
    # Interface chính — khớp với LLMClient thật
    # ------------------------------------------------------------------ #

    def call_text_gen(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> str:
        """Mock cho TextGenerator.  Trả văn bản chứa entity từ prompt."""
        return self._mock_text_response(prompt)

    def call_critic(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> str:
        """Mock cho CriticAgent.  Luôn trả JSON hợp lệ (valid)."""
        return json.dumps(
            {"is_valid": True, "errors": [], "suggestions": []},
            ensure_ascii=False,
        )

    # ------------------------------------------------------------------ #
    # Giữ lại generate() cũ cho tương thích ngược (nếu ai đó gọi trực tiếp)
    # ------------------------------------------------------------------ #

    def generate(
        self, prompt: str, temperature: float = 0.7, max_tokens: int = 500
    ) -> str:
        return self._mock_text_response(prompt)

    # ------------------------------------------------------------------ #
    # Helpers nội bộ
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_entity_texts(prompt: str) -> list[str]:
        """Trích xuất danh sách entity text từ prompt của TextGenerator.

        Prompt chứa các dòng dạng:  - 'entity text here' (loại: ...)
        """
        import re
        return re.findall(r"- '([^']+)'\s*\(loại:", prompt)

    def _mock_text_response(self, prompt: str) -> str:
        """Sinh văn bản mock chứa tất cả entity được yêu cầu trong prompt."""

        entity_texts = self._extract_entity_texts(prompt)

        if not entity_texts:
            # Fallback nếu không parse được (ví dụ prompt lạ)
            return (
                "1. Tiền sử bệnh\n"
                "BN 65t nam, TS: tăng huyết áp 10 năm.\n\n"
                "2. Tiền sử bệnh hiện tại\n"
                "NV vì đau ngực dữ dội.\n\n"
                "3. Đánh giá tại bệnh viện\n"
                "CD: nhồi máu cơ tim cấp. Điều trị: aspirin 81 mg po daily."
            )

        # Chia entity vào 3 phần cho tự nhiên
        n = len(entity_texts)
        part1 = entity_texts[: max(1, n // 3)]
        part2 = entity_texts[max(1, n // 3): max(2, 2 * n // 3)]
        part3 = entity_texts[max(2, 2 * n // 3):]

        lines = ["1. Tiền sử bệnh"]
        lines.append("BN 65t nam, TS bệnh lý.")
        for e in part1:
            lines.append(f"- {e}")

        lines.append("\n2. Tiền sử bệnh hiện tại")
        lines.append("NV vì các triệu chứng sau:")
        for e in part2:
            lines.append(f"- {e}")

        lines.append("\n3. Đánh giá tại bệnh viện")
        lines.append("Khám và điều trị:")
        for e in part3:
            lines.append(f"- {e}")

        return "\n".join(lines)


def main():
    """Hàm main - chạy pipeline sinh dữ liệu"""

    # Cấu hình
    config = GenerationConfig(
        num_samples=100,  # Bắt đầu với 20 mẫu để test
        max_retries=3,
    )

    # Đường dẫn
    output_dir = project_root / "data" / "raw_generated"
    seeds_dir = project_root / "data_generation" / "knowledge_seeds"

    # Khởi tạo LLM client (mock — thay bằng LLM thật khi deploy)
    llm_client = MockLLMClient()

    # Khởi tạo pipeline
    pipeline = DataGenerationPipeline(
        config=config,
        llm_client=llm_client,
        output_dir=output_dir,
        seeds_dir=seeds_dir,
    )

    # Chạy pipeline
    samples = pipeline.run(num_samples=config.num_samples)

    # Kiểm tra độ phủ
    coverage = validate_coverage(samples)

    print("\n" + "=" * 60)
    print("KẾT QUẢ SINH DỮ LIỆU")
    print("=" * 60)
    print(f"Tổng số mẫu: {coverage['total_samples']}")
    print(f"Tổng số thực thể: {coverage['total_entities']}")
    print(f"Trung bình thực thể/mẫu: {coverage['avg_entities_per_sample']:.2f}")
    print("\nPhân phối loại thực thể:")
    for etype, count in coverage["entity_types"].items():
        print(f"  {etype}: {count}")
    print("\nPhân phối thuộc tính:")
    for assertion, count in coverage["assertions"].items():
        print(f"  {assertion}: {count}")

    if coverage["missing_entity_types"]:
        print(f"\n⚠️  Thiếu loại thực thể: {coverage['missing_entity_types']}")
    if coverage["missing_assertions"]:
        print(f"⚠️  Thiếu thuộc tính: {coverage['missing_assertions']}")

    print("\n" + "=" * 60)
    print(f"Dữ liệu đã lưu tại: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()