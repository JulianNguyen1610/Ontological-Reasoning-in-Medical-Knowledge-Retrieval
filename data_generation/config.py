"""
Cấu hình hệ thống sinh dữ liệu nhân tạo định hướng tri thức
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Đường dẫn gốc dự án
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SEEDS_DIR = Path(__file__).parent / "knowledge_seeds"

# Chỉ các chẩn đoán này có ngữ cảnh tiền sử gia đình đủ tự nhiên trong seed hiện tại.
FAMILY_HISTORY_DIAGNOSIS_CODES = frozenset({
    "J45.9", "I10", "I21.9", "E11.9", "E10.9", "G40.9", "G43.9",
    "M06.9", "C50.9", "C34.9", "L40.0", "L30.9", "H40.9",
})

@dataclass
class GenerationConfig:
    """Cấu hình sinh dữ liệu"""
    
    # Số lượng bản ghi cần sinh
    num_samples: int = 10000
    
    # Tỷ lệ phân phối loại thực thể (đảm bảo độ phủ cân bằng)
    entity_distribution: Dict[str, float] = field(default_factory=lambda: {
        "TRIỆU_CHỨNG": 0.25,
        "TÊN_XÉT_NGHIỆM": 0.15,
        "KẾT_QUẢ_XÉT_NGHIỆM": 0.15,
        "CHẨN_ĐOÁN": 0.25,
        "THUỐC": 0.20,
    })
    
    # Tỷ lệ phân phối thuộc tính
    assertion_distribution: Dict[str, float] = field(default_factory=lambda: {
        "isNegated": 0.30,
        "isFamily": 0.25,
        "isHistorical": 0.45,
        "none": 0.20,  # Không có thuộc tính đặc biệt
    })
    
    # Tỷ lệ các kịch bản lâm sàng
    scenario_distribution: Dict[str, float] = field(default_factory=lambda: {
        "single_entity": 0.15,        # Chỉ 1 thực thể
        "few_entities": 0.35,          # 2-5 thực thể
        "many_entities": 0.30,         # 6-15 thực thể
        "complex_mixed": 0.20,         # >15 thực thể, đan xen phức tạp
    })
    
    # Ngưỡng验证
    min_similarity_threshold: float = 0.95
    max_retries: int = 3

    # Relative curriculum targets; ChallengePlanner converts these to batch quotas.
    challenge_profile_quotas: Dict[str, float] = field(default_factory=lambda: {
        "basic": 0.25, "negation_scope": 0.12, "historical_scope": 0.12,
        "family_scope": 0.08, "lab_name_result_pair": 0.15,
        "repeated_mention": 0.10, "abbreviation_or_typo": 0.10,
        "mixed_language": 0.08,
    })
    previous_evaluation_report: Optional[str] = None
    force_critic_all: bool = False
    checkpoint_interval: int = 25
    resume_from_checkpoint: Optional[str] = None
    max_total_attempts: Optional[int] = None
    
    # Phong cách văn bản
    style_variants: List[str] = field(default_factory=lambda: [
        "discharge_summary",      # Giấy xuất viện
        "clinical_note",          # Ghi chú lâm sàng
        "admission_note",         # Ghi chú nhập viện
        "progress_note",          # Ghi chú tiến triển
        "medication_list",        # Danh sách thuốc
        "lab_report",             # Báo cáo xét nghiệm
        "imaging_report",         # Báo cáo hình ảnh
    ])
    
    # Mức độ nhiễu (noise injection)
    noise_config: Dict[str, float] = field(default_factory=lambda: {
        "typos": 0.15,             # 15% bản ghi có lỗi chính tả
        "abbreviations": 0.40,     # 40% dùng từ viết tắt
        "missing_punctuation": 0.20, # 20% thiếu dấu câu
        "informal_language": 0.25,  # 25% dùng ngôn ngữ dân dã
    })

    # Text Generator config
    text_gen_api_url: str = os.getenv("TEXT_GEN_API_URL", "https://api.openai.com/v1/chat/completions")
    text_gen_api_key: str = os.getenv("TEXT_GEN_API_KEY", "")
    text_gen_model: str = os.getenv("TEXT_GEN_MODEL", "gpt-4")
    
    # Critic Agent config
    critic_api_url: str = os.getenv("CRITIC_API_URL", "https://api.openai.com/v1/chat/completions")
    critic_api_key: str = os.getenv("CRITIC_API_KEY", "")
    critic_model: str = os.getenv("CRITIC_MODEL", "gpt-4o")
    
    temperature: float = 0.7
    max_tokens: int = 2000
    
    # Cấu hình delay để tránh giới hạn RPM (40 RPM tương đương trung bình 1.5s/request)
    request_delay: float = 4.0
    api_max_retries: int = 5
    api_retry_base_delay: float = 5.0
    api_retry_max_delay: float = 60.0
    api_retry_jitter: float = 0.25
    api_rate_limit_cooldown: float = 15.0

# Các loại thực thể hợp lệ
VALID_ENTITY_TYPES = [
    "TRIỆU_CHỨNG",
    "TÊN_XÉT_NGHIỆM", 
    "KẾT_QUẢ_XÉT_NGHIỆM",
    "CHẨN_ĐOÁN",
    "THUỐC"
]

# Các loại thuộc tính hợp lệ
VALID_ASSERTIONS = [
    "isNegated",
    "isFamily", 
    "isHistorical"
]

# Template prompt cho từng giai đoạn
PROMPT_TEMPLATES = {
    "scenario_generation": """Bạn là một bác sĩ lâm sàng giàu kinh nghiệm. 
Hãy tạo ra một kịch bản bệnh lý có cấu trúc rõ ràng dựa trên các chủ đề y khoa sau:

Chủ đề: {topic}
Loại văn bản: {text_style}
Số thực thể mong muốn: {num_entities}
Phân phối thực thể: {entity_distribution}

Yêu cầu:
1. Kịch bản phải có tính logic lâm sàng cao
2. Các thực thể phải tự nhiên, không gượng ép
3. Bao phủ đầy đủ các loại: triệu chứng, xét nghiệm, chẩn đoán, thuốc
4. Có ít nhất 1 thực thể có thuộc tính (phủ định/tiền sử/gia đình)

Trả về định dạng JSON:
{{
  "scenario": "mô tả kịch bản",
  "entities": [
    {{
      "text": "chuỗi văn bản chính xác",
      "type": "LOẠI_THỰC_THỂ",
      "assertions": ["thuộc_tính"],
      "candidates": ["mã_chuẩn"],
      "context": "ngữ cảnh xuất hiện"
    }}
  ]
}}""",

    "text_generation": """Bạn là một bác sĩ đang ghi chú bệnh án. 
Hãy chuyển kịch bản sau thành văn bản y khoa tự do (free-form text) theo phong cách {style}.

Kịch bản: {scenario}
Danh sách thực thể cần xuất hiện: {entities}

YÊU CẦU NGHIÊM NGẶT:
1. PHẢI giữ NGUYÊN VĂN chuỗi text của mỗi thực thể - không thêm, bớt, sửa ký tự
2. Văn bản phải tự nhiên, giống ghi chú bác sĩ thực tế
3. Có thể dùng từ viết tắt, ký hiệu chuyên ngành
4. Không cần cấu trúc ngữ pháp hoàn chỉnh
5. Các thực thể phải xuất hiện theo thứ tự logic trong văn bản

{noise_instructions}

Trả về CHỈ văn bản thô, không kèm giải thích.""",

    "critic_check": """Bạn là một chuyên gia kiểm duyệt hồ sơ bệnh án.
Hãy kiểm tra xem danh sách thực thể có khớp hoàn toàn với văn bản không.

Văn bản: {text}
Danh sách thực thể: {entities}

Kiểm tra từng thực thể:
1. Chuỗi "text" có xuất hiện CHÍNH XÁC (kể cả khoảng trắng) trong văn bản không?
2. Vị trí (start, end) có đúng không?
3. Loại thực thể có phù hợp ngữ cảnh không?
4. Thuộc tính có đúng ngữ cảnh không?

Trả về JSON:
{{
  "valid": true/false,
  "errors": [
    {{
      "entity_index": 0,
      "error_type": "text_mismatch|position_error|type_error|assertion_error",
      "detail": "mô tả lỗi",
      "suggestion": "gợi ý sửa"
    }}
  ]
}}"""
}
