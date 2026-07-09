# Ontological Reasoning in Medical Knowledge Retrieval - Data Generation Framework

Tài liệu này hướng dẫn chi tiết cách thiết lập, cấu hình và vận hành hệ thống sinh dữ liệu y khoa nhân tạo (synthetic clinical data) phục vụ cho các bài toán Nhận dạng Thực thể Y tế (NER), Phân tích Thuộc tính Thực thể (Assertion Status) và Liên kết Thực thể Y khoa (Entity Linking / Medical Coding).

---

## 1. Tổng quan dự án

Hệ thống được thiết kế để sinh ra các đoạn văn bản lâm sàng tự do (free-form clinical text) bằng tiếng Việt mô phỏng hồ sơ bệnh án thực tế tại Việt Nam. Quá trình sinh dữ liệu được định hướng bởi các nguồn tri thức y khoa có sẵn (Knowledge Seeds) bao gồm ICD-10, RxNorm, danh mục triệu chứng và xét nghiệm lâm sàng.

Hệ thống tích hợp một đường ống sinh dữ liệu nâng cao gồm các giai đoạn chính (Multi-Agent Pipeline):
1. **Topic Extractor (Trích xuất chủ đề)**: Lựa chọn ngẫu nhiên các bộ thực thể lâm sàng có logic từ cơ sở tri thức (seeds) dựa trên độ phức tạp của kịch bản lâm sàng được chỉ định.
2. **Style Director (Định hướng phong cách)**: Quản lý phong cách ghi chú y khoa và tiêm các đặc trưng nhiễu thực tế (từ viết tắt chuyên ngành, lỗi chính tả nhẹ, ký hiệu y khoa, lược bỏ chủ ngữ, dấu câu).
3. **Text Generator (Sinh văn bản lâm sàng)**: Sử dụng mô hình ngôn ngữ lớn (LLM) để sinh ra văn bản lâm sàng tự do và tự động định vị (tính toán offset `[start, end]`) các thực thể trong văn bản.
4. **Critic Agent (Tác nhân phản biện)**: Kiểm tra chéo độc lập tính chính xác của các thực thể được sinh ra và vị trí của chúng. Nếu phát hiện lỗi (lệch vị trí, thiếu thực thể, sai ngữ cảnh thuộc tính), Critic Agent sẽ tự động đề xuất chỉnh sửa (Auto-Fix).
5. **Deduplication & Schema Alignment (Làm sạch dữ liệu)**: Chuẩn hóa Unicode tiếng Việt (NFC), tinh chỉnh lại vị trí offset bằng thuật toán tìm kiếm mờ (Fuzzy Search / Levenshtein Distance), lọc trùng lặp và loại bỏ các thực thể nằm ngoài schema quy định.

---

## 2. Cấu trúc thư mục

Dự án được phân chia thành các thư mục chức năng rõ ràng:

```text
.
├── data/                      # Thư mục chứa dữ liệu đầu ra đã được làm sạch
│   ├── training_data.json     # File dữ liệu huấn luyện dạng danh sách JSON
│   ├── training_data.jsonl    # Dữ liệu huấn luyện dạng JSON Lines (mỗi dòng 1 bản ghi)
│   └── generation_stats.json  # Thống kê về độ phủ thực thể và thuộc tính
├── data_generation/           # Mã nguồn pipeline sinh dữ liệu
│   ├── generators/            # Các tác nhân trong pipeline sinh dữ liệu
│   │   ├── topic_extractor.py # Trích xuất chủ đề y khoa từ seeds
│   │   ├── style_director.py  # Áp dụng viết tắt, lỗi chính tả, phong cách lâm sàng
│   │   ├── text_generator.py  # Sinh văn bản qua LLM và định vị thực thể
│   │   └── critic_agent.py    # Kiểm duyệt chéo và tự động sửa lỗi (Auto-Fix)
│   ├── knowledge_seeds/       # Tri thức y khoa nền tảng (Seeds)
│   │   ├── icd10_seeds.json   # Chẩn đoán ICD-10 và liên kết triệu chứng/thuốc/xét nghiệm
│   │   ├── rxnorm_seeds.json  # Danh mục thuốc, liều lượng, đường dùng, tần suất
│   │   ├── symptom_seeds.json # Danh mục triệu chứng lâm sàng và từ đồng nghĩa
│   │   └── test_lab_seeds.json# Danh mục xét nghiệm, đơn vị đo, chỉ số bất thường
│   ├── utils/                 # Các tiện ích xử lý văn bản và hậu xử lý
│   │   ├── cleanup.py         # Hậu xử lý, sửa offset, loại trùng lặp và căn chỉnh schema
│   │   └── text_utils.py      # Chuẩn hóa Unicode, tính khoảng cách Levenshtein
│   ├── config.py              # Cấu hình phân phối thực thể, tỷ lệ nhiễu, template prompt
│   ├── llm_client.py          # Client gọi API mô hình ngôn ngữ lớn (OpenAI compatible)
│   ├── run_pipeline.py        # Kịch bản chính chạy sinh dữ liệu bằng LLM thực tế
│   ├── requirements.txt       # Danh sách các thư viện cần thiết
│   └── .env                   # Cấu hình API key và đường dẫn mô hình (không đưa lên Git)
├── document/                  # Tài liệu tham khảo, bài báo khoa học và mô tả đề bài
├── input/                     # Dữ liệu bệnh án đầu vào mẫu
└── scripts/                   # Các kịch bản phụ trợ
    └── run_generation.py      # Kịch bản chạy sinh dữ liệu thử nghiệm bằng Mock LLM
```

---

## 3. Định dạng dữ liệu đầu ra

Tập dữ liệu huấn luyện được lưu dưới dạng danh sách JSON hoặc JSONL, mỗi mẫu dữ liệu có cấu trúc như sau:

```json
{
  "text": "BN được chẩn đoán Tăng huyết áp. Triệu chứng bao gồm fatigue và nhức đầu. Điều trị hiện tại: metoprolol succinate xl 100 mg đường uống hàng ngày và amlodipine 5mg po hàng ngày.",
  "entities": [
    {
      "text": "Tăng huyết áp",
      "type": "CHẨN_ĐOÁN",
      "assertions": [],
      "candidates": ["I10"],
      "position": [18, 31]
    },
    {
      "text": "fatigue",
      "type": "TRIỆU_CHỨNG",
      "assertions": [],
      "candidates": [],
      "position": [53, 60]
    },
    {
      "text": "nhức đầu",
      "type": "TRIỆU_CHỨNG",
      "assertions": [],
      "candidates": [],
      "position": [64, 72]
    },
    {
      "text": "metoprolol succinate xl 100 mg đường uống hàng ngày",
      "type": "THUỐC",
      "assertions": [],
      "candidates": ["866436"],
      "position": [88, 129]
    }
  ],
  "scenario_id": "sample_123456"
}
```

### Các thông số chi tiết trong thực thể:
- `text`: Chuỗi ký tự của thực thể được trích xuất (phải khớp chính xác 100% với ký tự trong văn bản gốc tại vị trí offset).
- `type`: Phải thuộc một trong các loại thực thể trong Schema y khoa hợp lệ:
  - `TRIỆU_CHỨNG`: Các dấu hiệu, triệu chứng lâm sàng.
  - `TÊN_XÉT_NGHIỆM`: Tên các chỉ định xét nghiệm/cận lâm sàng.
  - `KẾT_QUẢ_XÉT_NGHIỆM`: Chỉ số kết quả xét nghiệm y tế.
  - `CHẨN_ĐOÁN`: Các bệnh lý hoặc chẩn đoán lâm sàng của bác sĩ.
  - `THUỐC`: Tên biệt dược/hoạt chất kèm liều lượng, tần suất và đường dùng.
- `assertions`: Các thuộc tính ngữ cảnh của thực thể (Assertion Status):
  - `isNegated`: Thực thể được nhắc đến ở dạng phủ định (ví dụ: *"không đau ngực"*).
  - `isFamily`: Bệnh lý/triệu chứng của người nhà chứ không phải của bệnh nhân (ví dụ: *"bố bị tiểu đường"*).
  - `isHistorical`: Tiền sử bệnh lý hoặc thuốc đã ngưng sử dụng trong quá khứ.
- `candidates`: Danh sách mã chuẩn hóa thực thể sang cơ sở tri thức (Ontology Linking):
  - Đối với `CHẨN_ĐOÁN`: mã ICD-10 (ví dụ: `["I10"]`).
  - Đối với `THUỐC`: mã RxCUI từ RxNorm (ví dụ: `["866436"]`).
- `position`: Cặp chỉ số `[start, end]` (0-indexed) chỉ vị trí bắt đầu và kết thúc của thực thể trong trường `text` (không bao gồm ký tự tại chỉ số `end`).

---

## 4. Hướng dẫn thiết lập môi trường

### Bước 1: Yêu cầu hệ thống
- Python 3.10 trở lên.
- Có kết nối Internet để gọi LLM API (hoặc chạy local LLM thông qua Ollama/vLLM).

### Bước 2: Cài đặt thư viện dependencies
Chạy lệnh sau tại thư mục gốc của dự án để cài đặt các thư viện phụ thuộc:
```bash
pip install -r data_generation/requirements.txt
```

### Bước 3: Cấu hình biến môi trường
Tạo file `.env` nằm trong thư mục `data_generation/` với nội dung cấu hình API của bạn:
```ini
# API cấu hình cho mô hình sinh văn bản (Text Generator)
TEXT_GEN_API_URL=https://api.openai.com/v1/chat/completions # Hoặc link vLLM/Ollama
TEXT_GEN_API_KEY=your-api-key-here
TEXT_GEN_MODEL=gpt-4 # Hoặc model mong muốn khác

# API cấu hình cho mô hình phản biện (Critic Agent)
CRITIC_API_URL=https://api.openai.com/v1/chat/completions
CRITIC_API_KEY=your-api-key-here
CRITIC_MODEL=gpt-4o
```

---

## 5. Hướng dẫn chạy chương trình

Dự án cung cấp hai chế độ chạy sinh dữ liệu: chạy thử nghiệm ngoại tuyến (Mock LLM) và chạy thật với LLM API.

### Chế độ 1: Chạy thử nghiệm với Mock LLM (Không cần GPU / API Key)
Để kiểm tra nhanh tính toàn vẹn của logic pipeline, thuật toán định dạng và cách trích xuất chủ đề y khoa mà không tốn chi phí gọi API hoặc cần GPU, chạy lệnh sau từ thư mục gốc của dự án:
```bash
python scripts/run_generation.py
```
**Đặc điểm:**
- Sử dụng `MockLLMClient` tự động giả lập kết quả sinh ra văn bản y khoa tiếng Việt.
- Chạy nhanh, kiểm tra trực quan cấu trúc pipeline.
- Tự động in bảng thống kê độ phủ các loại thực thể, thuộc tính ngữ cảnh trực tiếp lên màn hình console sau khi hoàn thành.
- Kết quả được lưu vào thư mục `data/raw_generated/`.

### Chế độ 2: Chạy sinh dữ liệu thực tế bằng LLM API
Sau khi đã thiết lập chính xác các thông tin trong file `data_generation/.env`, chạy lệnh sau từ thư mục gốc của dự án:
```bash
python data_generation/run_pipeline.py
```
**Luồng xử lý:**
1. Pipeline khởi tạo cấu hình từ `GenerationConfig` trong `config.py` (mặc định sinh 100 mẫu, có thể cấu hình lại tham số `num_samples` lên tới 10,000 mẫu).
2. Trích xuất ngẫu nhiên các thực thể kết hợp từ ICD-10, RxNorm, symptoms, lab_tests.
3. Gửi prompt đến Text Generator để viết thành đoạn văn tự do tiếng Việt theo các định hướng phong cách lâm sàng ngẫu nhiên.
4. Gửi kết quả sang Critic Agent để kiểm duyệt chéo, tự động sửa (Auto-Fix) nếu vị trí offset bị lệch do LLM sinh ra.
5. Tiến hành giải pháp chuẩn hóa và làm sạch Unicode bằng module `cleanup.py`.
6. Lưu định kỳ các tệp tin checkpoint dạng JSON tại `output/checkpoints/` mỗi khi hoàn thành 1000 mẫu để đề phòng sự cố gián đoạn.
7. Khi kết thúc, ghi dữ liệu hoàn chỉnh dạng JSON và JSONL vào thư mục đầu ra.

---

## 6. Các thông số cấu hình nâng cao (`config.py`)

Bạn có thể thay đổi các tham số trong class `GenerationConfig` tại file [config.py](file:///d:/MedicalRetrieval/data_generation/config.py) để tinh chỉnh dữ liệu sinh ra:

- `num_samples`: Tổng số mẫu dữ liệu cần sinh.
- `entity_distribution`: Tỷ lệ phân phối các loại thực thể y khoa mong muốn nhằm tránh tình trạng mất cân bằng dữ liệu (Imbalanced Data).
- `assertion_distribution`: Tỷ lệ xuất hiện của các thuộc tính ngữ cảnh `isNegated`, `isFamily`, `isHistorical`.
- `scenario_distribution`: Phân phối độ dài và tính phức tạp của kịch bản lâm sàng (`single_entity`, `few_entities`, `many_entities`, `complex_mixed`).
- `noise_config`: Tỷ lệ xuất hiện các loại nhiễu trong văn bản (ví dụ: `typos`: 15% lỗi chính tả, `abbreviations`: 40% viết tắt, `missing_punctuation`: 20% thiếu dấu câu, `informal_language`: 25% dùng từ dân dã).
- `request_delay`: Khoảng thời gian nghỉ giữa các yêu cầu (mặc định `1.5` giây) để tránh vượt quá giới hạn tần suất gọi API của nhà cung cấp (Rate Limit / RPM).

---

## 7. Quy trình Hậu Xử Lý & Làm Sạch (`cleanup.py`)

Vì LLM sinh văn bản đôi khi có thể tự ý thay đổi ký tự hoặc vị trí offset bị sai lệch nhỏ so với văn bản gốc, tệp [cleanup.py](file:///d:/MedicalRetrieval/data_generation/utils/cleanup.py) cung cấp quy trình làm sạch nghiêm ngặt:
- **Lọc Schema**: Chỉ giữ lại các thực thể và thuộc tính thuộc schema cho phép.
- **Tính toán lại Vị trí (Relocate)**: Tìm kiếm chính xác và tìm kiếm mờ (Fuzzy Matching) để định vị lại chỉ số `[start, end]` của chuỗi thực thể trong văn bản.
- **Loại bỏ trùng lặp**: Loại bỏ các thực thể có cùng vị trí bắt đầu, kết thúc hoặc cùng nhãn loại.

Bạn có thể chạy độc lập file cleanup để gộp và làm sạch nhiều file dữ liệu thô:
```bash
python data_generation/utils/cleanup.py
```
Dữ liệu đầu ra sạch hoàn chỉnh sẽ được lưu tại thư mục `data/` ở thư mục gốc của dự án.
