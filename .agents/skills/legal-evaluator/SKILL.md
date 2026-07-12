---
name: legal-evaluator
description: Evaluate legal QA and courtroom simulation outputs. Implement metrics, rubrics, and quality assessment for legal reasoning and judgment prediction.
---

# Legal Evaluator

Dùng skill này khi cần tính toán, kiểm tra hoặc nâng cấp các metric đánh giá chất lượng pháp lý (LJP) và độ chính xác của câu trả lời QA.

## Hệ Thống Đánh Giá Hiện Tại

### 1. Phase 1 — ViLQA QA Evaluation (`src/evaluation/evaluator.py`)
- **Exact Match (EM)**: Trả về `1.0` nếu prediction (sau khi chuẩn hóa) trùng khớp hoàn toàn với gold answer, ngược lại `0.0`.
- **Token-level F1**: Đánh giá độ chồng chéo từ vựng (whitespace split) giữa prediction và gold answer.
- **LLM-as-Judge Rubric (`src/agents/evaluator_agent.py`)**: Đánh giá định tính (legal accuracy, argument quality, logical consistency) bằng thang điểm `1-5` thông qua một mô hình độc lập (được cấu hình qua `evaluator` role trong config).

### 2. Phase 3 — Courtroom LJP Evaluation (`src/evaluation/ljp_evaluator.py`)
Đánh giá chất lượng của dự đoán phán quyết pháp lý (`LegalJudgment`) so với nhãn vàng (`JudgmentGroundTruth`):
- **Charge Accuracy**: Độ chính xác của tội danh dự đoán (chuẩn hóa chuỗi và so khớp).
- **Article Accuracy**: Khớp tập hợp các điều luật trích dẫn (ví dụ: "Điều 104 Bộ luật Hình sự").
- **Sentence metrics**:
  - `sentence_mae_years`: Sai số tuyệt đối trung bình (MAE) tính bằng năm tù.
  - `sentence_rmse_years`: Sai số bình phương trung bình gốc (RMSE) tính bằng năm tù.
  - `sentence_bucket_accuracy`: Phân loại mức án vào các xô (0 năm/án treo, <3 năm, 3-7 năm, 7-15 năm, >15 năm) và đo độ chính xác.
- **Citation Validity / Hallucination hooks**: Đánh giá độ chuẩn xác của các `cited_evidence_ids`.

## Các Bài Test Đã Có (tests/)

Bạn có thể chạy các bài test này để kiểm tra xem thay đổi của mình có làm hỏng logic đánh giá hiện tại không:
- `python -m unittest tests/test_answer_postprocess.py`: Test chuẩn hóa span tiếng Việt.
- `python -m unittest tests/test_phase4_evaluation_runner.py`: Test ghi kết quả metric của Phase 1.
- `python -m unittest tests/test_phase5_courtroom.py`: Chứa các test kiểm thử toàn bộ dòng chảy LJP và tính điểm LJP sơ bộ.

## Quy Tắc Đánh Giá Nghiên Cứu

1. **Label Leakage Protection**: Đảm bảo gold answer/ground truth không bao giờ được chuyển vào prompt tranh biện hoặc prompt của Thẩm phán cập nhật niềm tin. Chỉ tệp Evaluator/LJPEvaluator mới được phép đọc nhãn vàng để so khớp.
2. **Post-processing đồng đều**: Bất kỳ bộ lọc/rút gọn chuỗi nào (như `shorten_legal_answer`) dùng để làm đẹp câu trả lời trước khi so EM/F1 **phải** được áp dụng công bằng cho tất cả baselines (`direct`, `cot`, v.v.), không chỉ áp dụng riêng cho `debate`.
3. **Thống kê fallback**: Fallback count (khi Judge trả về câu trả lời không đúng định dạng JSON và phải kích hoạt fallback) là một metric bắt buộc trong `metrics.json`. Fallback rate cao đồng nghĩa với việc kết luận về khả năng lập luận của hệ thống bị giảm giá trị.
