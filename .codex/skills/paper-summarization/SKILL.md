---
name: paper-summarization
description: Tóm tắt ngắn gọn một bài báo khoa học về AI/ML/NLP bằng tiếng Việt. Sử dụng khi người dùng yêu cầu tóm tắt, summary, đọc nhanh, hoặc review ngắn một paper, bài báo, hoặc nghiên cứu.
disable-model-invocation: true
---

# Tóm Tắt Bài Báo Khoa Học AI/ML

Skill này tạo bản tóm tắt ngắn gọn (~300-500 từ) cho một bài báo khoa học, bằng tiếng Việt, phục vụ nghiên cứu AI/ML/NLP.

**Khác biệt với các skill hiện có:**
- `paper-review-and-implementation`: phân tích chi tiết 10 mục + kế hoạch triển khai code
- `literature-review-matrix`: so sánh nhiều bài báo cùng lúc
- **Skill này**: tóm tắt nhanh 1 bài, đủ để nắm ý chính và đánh giá mức liên quan

## Quy trình

### Bước 1: Xác định nguồn

- Người dùng cung cấp file PDF, link arXiv, DOI, hoặc dán nội dung.
- Nếu thiếu nguồn, yêu cầu cung cấp trước khi tiếp tục.

### Bước 2: Trích xuất metadata

Ghi nhận: Tiêu đề, Tác giả, Năm, Venue, Link/DOI, Code repository (nếu có).

### Bước 3: Tóm tắt theo template

Viết tóm tắt theo template bên dưới, đảm bảo:

- **Ngôn ngữ**: Tiếng Việt. Giữ nguyên thuật ngữ kỹ thuật tiếng Anh khi cần (ví dụ: attention, transformer, loss function).
- **Độ dài**: 300-500 từ cho phần nội dung chính.
- **Trọng tâm cân bằng**: Vấn đề → Phương pháp → Kết quả → Đóng góp.
- **Trung thực**: Không suy diễn ngoài nội dung bài báo. Đánh dấu rõ nếu thông tin bị thiếu.

### Bước 4: Đánh giá bổ sung

Sau phần tóm tắt, bổ sung:

1. **Điểm mạnh / Điểm yếu**: 2-3 điểm mỗi loại, ngắn gọn.
2. **Công thức quan trọng**: Trích tối đa 2-3 công thức cốt lõi, giải thích từng biến bằng tiếng Việt.
3. **Hình/Bảng quan trọng**: Mô tả ngắn 1-2 hình hoặc bảng then chốt.
4. **Mức liên quan**: Đánh giá mức liên quan đến nghiên cứu hiện tại (Cao / Trung bình / Thấp) kèm lý do 1-2 câu.

## Template Đầu Ra

```markdown
# Tóm Tắt: <Tiêu đề bài báo>

## Metadata
- **Tác giả**: ...
- **Năm**: ... | **Venue**: ...
- **Link**: ...
- **Code**: ... (nếu có)

## Vấn Đề Nghiên Cứu
<Bài báo giải quyết vấn đề gì? Tại sao quan trọng? 2-3 câu.>

## Phương Pháp
<Ý tưởng chính và kiến trúc/kỹ thuật đề xuất. 3-5 câu.>

## Kết Quả Chính
<Tóm tắt kết quả thực nghiệm: dataset, metric, so sánh với baseline. 2-4 câu.>

## Đóng Góp
<Liệt kê 2-3 đóng góp chính của bài báo.>

---

## Điểm Mạnh
- ...
- ...

## Điểm Yếu
- ...
- ...

## Công Thức Quan Trọng
<Trích công thức cốt lõi, giải thích biến.>

## Hình/Bảng Quan Trọng
<Mô tả ngắn hình hoặc bảng then chốt.>

## Mức Liên Quan Đến Nghiên Cứu Hiện Tại
**Mức độ**: Cao / Trung bình / Thấp
**Lý do**: <1-2 câu giải thích.>
```

## Lưu Ý

- Không copy nguyên văn từ bài báo; diễn đạt lại bằng lời.
- Nếu bài báo có nhiều thí nghiệm, chỉ tóm tắt kết quả chính (main result), không liệt kê toàn bộ.
- Nếu bài báo thiếu thông tin quan trọng (ví dụ: không công bố code, không có ablation), ghi rõ trong phần Điểm Yếu.
- Khi đánh giá mức liên quan, tham khảo context dự án tại `.cursor/rules/01-project-context-always.mdc`.
