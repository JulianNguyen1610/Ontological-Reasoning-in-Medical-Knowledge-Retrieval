# MedLink-IE Coding Instructions

## Source of truth

Thứ tự ưu tiên:

1. `specs/TASK_CONTRACT.md`
2. `specs/ANNOTATION_GUIDE.md`
3. `specs/terminology_manifest.yaml`
4. `docs/MedLink-IE_v2_Framework.md`
5. `tests`
6. source code hiện tại

Khi tài liệu mâu thuẫn, không tự chọn. Hãy dừng lại và ghi rõ mâu thuẫn.

## Architectural invariants

- Không để LLM sinh position.
- Mọi position phải được tính từ raw source text.
- Mọi output entity phải thỏa: `entity.text == raw_text[entity.start:entity.end]`.
- Không để LLM đoán ICD hoặc RxNorm từ parametric memory.
- Candidate chỉ được lấy từ terminology snapshot.
- Grounding diễn ra trước type classification và assertion classification.
- Không thay đổi raw text bằng strip, trim hoặc normalize in-place.
- Không gọi Internet hoặc commercial API trong inference.
- LLM inference phải self-host và <= 9B.
- Pipeline phải deterministic khi dùng cùng config, seed, weights và data.
- Một sample lỗi không được làm dừng toàn batch.

## Development rules

- Mỗi task chỉ thay đổi một module hoặc một concern rõ ràng.
- Viết hoặc cập nhật test trước khi sửa implementation.
- Không tạo abstraction chưa được dùng.
- Không thêm dependency nếu Python standard library hoặc dependency hiện có đủ dùng.
- Không sửa public interface ngoài phạm vi task.
- Không bỏ qua lỗi bằng broad exception như `except Exception: pass`.
- Không dùng placeholder, mock logic hoặc TODO trong production path.
- Mỗi function public phải có type hints.
- Mỗi quyết định giữ hoặc bỏ entity phải có decision trace.

## Completion requirements

Trước khi báo hoàn thành:

1. Chạy formatter.
2. Chạy type checker.
3. Chạy unit tests liên quan.
4. Chạy toàn bộ test suite nếu không quá tốn thời gian.
5. Ghi rõ file đã đổi.
6. Ghi rõ test đã chạy.
7. Ghi rõ assumption còn tồn tại.
