---
name: agent-crafter
description: Create and customize legal agents for the courtroom simulation framework. Implement role-specific prompts, behaviors, and interaction patterns.
---

# Agent Crafter

Dùng skill này khi cần viết code, tùy chỉnh, chỉnh sửa prompt hoặc tối ưu hóa hoạt động của một Agent pháp lý cụ thể.

## Tổng Quan Class Agents Hiện Tại

Tất cả các agents kế thừa từ `BaseLegalAgent` (cho Phase 3) hoặc độc lập (Phase 1):

| Class | Thừa kế | File | Nhiệm vụ chính |
|-------|---------|------|----------------|
| `BaseLegalAgent` | — | `src/agents/base_legal_agent.py` | Quản lý chung prompt rendering, LLM client và compact context |
| `DebateAgent` | — | `src/agents/debate_agent.py` | Phase 1 Proponent/Opponent: `generate_argument`, `generate_closing_statement` |
| `JudgeAgent` | — | `src/agents/judge_agent.py` | Trọng tài/Thẩm phán: parse JSON, track belief, render verdict/LJP judgment |
| `ProsecutorAgent` | `BaseLegalAgent` | `src/agents/prosecutor.py` | Kiểm sát viên: `present_indictment`, `generate_argument`, `closing_statement` |
| `DefenseAgent` | `BaseLegalAgent` | `src/agents/defense.py` | Luật sư bào chữa: `opening_statement`, `generate_argument`, `closing_statement` |
| `DefendantAgent` | `BaseLegalAgent` | `src/agents/defendant.py` | Bị cáo: `testify` (lời khai cá nhân) |
| `EvaluatorAgent` | — | `src/agents/evaluator_agent.py` | LLM-as-judge chấm điểm rubric |

## Hướng Dẫn Kỹ Thuật

### 1. Robust JSON Parsing (JudgeAgent)
- Thẩm phán phải parse được JSON từ LLM output. Luôn có phương thức parse an toàn:
  - `_loads_json_or_empty(raw_output)`: tìm markdown fence ` ```json ... ``` ` hoặc `{ ... }` dẹp.
  - `_recover_json_field(raw_output)`: khôi phục `answer` hoặc `prediction` bằng Regex nếu JSON bị cắt giữa chừng (do token limit).
  - Tránh crash: Luôn bọc trong `try-except` và tạo `Verdict` hoặc `LegalJudgment` fallback với thông tin lấy từ context/previous belief.

### 2. Thiết Kế Prompt Template (`configs/prompts/`)
- Prompt dùng cú pháp `{variable}` để `str.format()` trong python. Do đó:
  - **Không** sử dụng dấu ngoặc nhọn kép `{}` trong prompt nếu không cần thay thế biến. Nếu là JSON mẫu hoặc pattern cố định, hãy dùng file txt thông thường và hướng dẫn rõ ràng.
  - Các biến truyền vào prompt phổ biến: `case_profile`, `legal_evidence`, `past_memory`, `debate_history` / `transcript`.

### 3. Answer Post-processing (`src/utils/answer_postprocess.py`)
- Phase 1 ViLQA yêu cầu câu trả lời là một **span ngắn nguyên văn** trong context.
- Để cải thiện Exact Match cho Debate, postprocessor lọc bớt các phần giải thích thừa của agent và rút gọn span:
  - `shorten_legal_answer(text)`: Rút gọn văn bản, loại bỏ các cụm "đồng trở lên", "Điều...", v.v.
  - Áp dụng đồng đều cho cả `direct`, `cot`, `vanilla`, `debate` thông qua helper để tránh thiên vị.

## Quy Trình Tùy Chỉnh Agent

1. Xác định agent và tệp prompt tương ứng cần sửa (ví dụ: `configs/prompts/courtroom/prosecutor_argument.txt`).
2. Sửa prompt txt, đảm bảo giữ nguyên hoặc thêm các biến format đúng chuẩn.
3. Nếu cần đổi logic code xử lý (ví dụ: tăng tham số temperature cho Prosecutor để tranh luận sắc sảo hơn), chỉnh sửa hàm khởi tạo agent hoặc file config `configs/default.yaml` hay `configs/courtroom.yaml`.
4. Viết test case hoặc chạy lại test: `python -m unittest tests/test_judge_agent.py` hoặc `tests/test_phase5_courtroom.py`.
