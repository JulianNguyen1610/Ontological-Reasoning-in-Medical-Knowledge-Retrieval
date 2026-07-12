---
name: experiment-manager
description: Manage and execute experiments for the legal QA and courtroom simulation framework. Configure ablation studies, run batch evaluations, and analyze results.
---

# Experiment Manager

Dùng skill này khi cần chạy, cấu hình, hoặc phân tích kết quả thí nghiệm cho Phase 1 (ViLQA) và Phase 3 (Courtroom LJP).

## Trạng Thái Thí Nghiệm Hiện Tại

| Run | Model | Split | EM | F1 | Ghi chú |
|-----|-------|-------|----|----|---------|
| direct | dolphin3:latest | validation 53 | 0.2642 | 0.6802 | Baseline tốt nhất với model nhỏ |
| debate rounds=1 | dolphin3:latest | validation 53 | 0.1698 | 0.5111 | Sau fix prompt/postprocess |
| **debate rounds=1** | **qwen3.5:9b** | **validation 53** | **0.4717** | **0.8106** | Debate thắng lớn |
| direct | qwen3.5:9b | validation 53 | 0.0189 | 0.4034 | Sụp do `max_output_tokens=128` (Linux cũ) |

**Còn lại**: Gemini validation, ablation matrix đầy đủ, batch courtroom runner.

## Cách Chạy Experiment

### Phase 1 — ViLQA QA Debate

```powershell
# Smoke test (không cần API)
python -m src.main --run-batch --llm mock --method both --limit 2 --rounds 1

# Validation với Gemini (default config)
python -m src.main --run-batch --llm gemini --method both --split validation --limit 0 --rounds 1

# Validation với Ollama — quan trọng: dùng ollama.yaml và đảm bảo num_ctx=8192
python -m src.main --config configs/ollama.yaml --run-batch --llm local --local-model qwen3.5:9b --method both --split validation --limit 0 --rounds 1

# Chỉ chạy direct để so sánh baseline
python -m src.main --run-batch --llm gemini --method direct --split validation --limit 0
```

### Phase 3 — Courtroom LJP

```powershell
# Smoke test
python -m src.main --run-courtroom --llm mock

# Pilot case VN với Gemini
python -m src.main --run-courtroom --courtroom-case data/processed/case_01_theft.json --llm gemini
```

## Tạo Ablation Matrix (Phase 1)

Các biến ablation được định nghĩa trong `configs/default.yaml` dưới `debate.ablations`, `retrieval.ablations`, và `memory.ablations`.

```powershell
# Chạy script tạo dry-run các câu lệnh
python scripts/run_ablation_matrix.py --dry-run

# Chạy thực tế và lưu tất cả kết quả
python scripts/run_ablation_matrix.py --execute
```

## Quy Tắc Lưu Trữ Artifacts

Mỗi lần chạy batch lưu vào thư mục timestamped dưới dạng:
`outputs/vilqa_multi_agent_baseline/<timestamp>_<split>_<method>/`

Các tệp được sinh ra tự động:
- `config.json`: Cấu hình dùng để chạy (đã lọc API keys)
- `metrics.json`: Chứa `metrics_by_method`, `models_by_method`, `fallbacks`
- `predictions.csv`: Kết quả chi tiết từng case

## Lưu Ý Cấu Hình Ollama (Local LLM)

1. Thiết lập `num_ctx=8192` cho Ollama server (xem hướng dẫn trong `Tech Context` hoặc chạy `scripts/setup_ollama_ctx8k.sh`).
2. Tắt model thinking để tránh lỗi rỗng `content`: `export LOCAL_LLM_REASONING_EFFORT=none`.
3. Kiểm tra token output: `max_output_tokens` cho direct/cot phải là **384** (tránh bị cắt JSON giữa chừng gây sụp đổ baseline).
