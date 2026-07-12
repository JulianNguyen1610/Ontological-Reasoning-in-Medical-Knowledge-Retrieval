---
name: courtroom-sim-architect
description: Help design and architect the multi-agent courtroom simulation framework. Focus on legal role design, protocol structure, and courtroom workflow optimization.
---

# Courtroom Simulation Architect

Dùng skill này khi cần thiết kế, mở rộng, hoặc debug kiến trúc **Phase 3 Courtroom LJP** của dự án.

## Kiến Trúc Hiện Tại

```
CourtroomSession.run(CourtCase)
  └─ CourtroomProtocol
       ├─ opening():       judge.open_session → prosecutor.present_indictment
       │                   → defendant.testify → defense.opening_statement
       ├─ debate_round():  prosecutor.generate_argument → defense.generate_argument
       │                   → judge.update_courtroom_belief [× max_debate_rounds]
       ├─ closing():       prosecutor.closing_statement → defense.closing_statement
       └─ judgment:        judge.deliberate → judge.render_ljp_verdict → judge.render_verdict
```

**Config**: `configs/courtroom.yaml` — bật/tắt từng phase, `max_debate_rounds`, `early_stop_confidence`, token limits.

## File Cốt Lõi Cần Biết

| File | Vai trò |
|------|---------|
| `src/courtroom/protocol.py` | `CourtroomProtocol` + `ProtocolConfig` — định nghĩa turn order |
| `src/courtroom/session.py` | `CourtroomSession` — lifecycle đầy đủ; `from_config()` đọc `courtroom.yaml` |
| `src/agents/base_legal_agent.py` | Base class cho tất cả legal agents |
| `src/agents/prosecutor.py` | `ProsecutorAgent`: `present_indictment`, `generate_argument`, `closing_statement` |
| `src/agents/defense.py` | `DefenseAgent`: `opening_statement`, `generate_argument`, `closing_statement` |
| `src/agents/defendant.py` | `DefendantAgent`: `testify` |
| `src/agents/judge_agent.py` | `JudgeAgent`: dual-mode (Phase 1 + Phase 3 courtroom) |
| `src/agents/compat.py` | Alias backward-compat Phase 1 |
| `src/models.py` | `CourtCase`, `LegalJudgment`, `CourtroomResult`, `ProtocolConfig` |
| `configs/prompts/courtroom/` | 13 prompt templates cho tất cả roles và phases |

## Prompt Templates Phase 3

```
configs/prompts/courtroom/
├── judge_opening.txt
├── judge_belief.txt          (tái dùng từ Phase 1, render qua _render_courtroom_prompt)
├── judge_question.txt
├── judge_deliberation.txt
├── judge_ljp_verdict.txt     (output: JSON {charge, articles, sentence, reasoning, confidence})
├── prosecutor_indictment.txt
├── prosecutor_strategy.txt
├── prosecutor_argument.txt
├── prosecutor_closing.txt
├── defense_strategy.txt
├── defense_opening.txt
├── defense_argument.txt
├── defense_closing.txt
└── defendant_testimony.txt
```

## Khi Thêm Role Mới (ví dụ: Witness)

1. Tạo class kế thừa `BaseLegalAgent` trong `src/agents/<role>.py`
2. Implement các method: `testify(court_case, legal_evidence, past_memory, transcript) -> AgentOutput`
3. Thêm `AgentRole` literal mới vào `src/models.py`
4. Tạo prompt templates trong `configs/prompts/courtroom/<role>_*.txt`
5. Cập nhật `CourtroomProtocol` để thêm turn mới trong phase phù hợp
6. Cập nhật `CourtroomSession.__init__` và `run()` để nhận agent mới
7. Viết test trong `tests/test_phase5_courtroom.py`

## Khi Sửa Protocol Phase

- `ProtocolConfig` là `dataclass(frozen=True)` — thêm field mới với default value
- `CourtroomProtocol.opening/debate_round/closing` nhận switch `if not self.config.enable_*: return [], []`
- Mỗi phase trả `(list[AgentOutput], list[str])` — turns và phase labels cho `phases_completed`
- Early stopping check trong `CourtroomSession.run()` sau mỗi `debate_round`

## JudgeAgent Dual-Mode

- Phase 1: dùng `update_belief`, `render_verdict`, `ask_follow_up` — template trong `configs/prompts/`
- Phase 3: dùng `update_courtroom_belief`, `deliberate`, `render_ljp_verdict` — template trong `configs/prompts/courtroom/`
- Kích hoạt courtroom mode bằng `judge.enable_courtroom_mode()` (được gọi tự động bởi `CourtroomSession.run()`)
- `render_ljp_verdict` output JSON: `{charge, articles, sentence, reasoning, confidence, cited_evidence_ids}`
- `render_verdict` gọi sau `render_ljp_verdict` để giữ backward-compat với `DebateResult`

## Lưu Ý Quan Trọng

- `CourtroomResult.to_debate_result()` cho phép Phase 1 artifact writer xử lý Phase 3 output
- `CourtCase.to_case_profile()` adapter dùng cho retrieval/memory (Phase 1 interface)
- Không đưa `ground_truth` (charge/articles/sentence) vào `agent_view()` — tránh label leakage
- Smoke test: `python -m src.main --run-courtroom --llm mock`
