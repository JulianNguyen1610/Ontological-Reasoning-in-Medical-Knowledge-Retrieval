# MedLink-IE v2.0 — Pipeline Framework Sẵn sàng Triển khai
## Viettel AI Race: Trích xuất, Chuẩn hóa và Liên kết Thực thể Y khoa

**Trạng thái:** Implementation-ready specification  
**Định hướng:** precision-first, hybrid, modular, self-host, score-aware, reproducible  
**Ràng buộc:** mọi LLM/Agent dùng khi inference phải self-host và không vượt quá 9B tham số  
**Mục tiêu vận hành:** một lệnh inference tạo đúng `output.zip`, có log, manifest và khả năng dựng lại kết quả

---

# 0. Quyết định kiến trúc

Giải pháp chính thức là một **pipeline lai có kiểm soát**, không phải LLM-only và không phải GraphRAG thuần túy.

```text
Raw input bytes
    → immutable source document
    → multi-view normalization with boundary maps
    → section/list/sentence analysis
    → multi-source span proposals
    → exact source grounding
    → span clustering and fusion
    → calibrated type classification
    → section-aware multi-label assertions
    → structured medication/lab parsing
    → type-specific candidate retrieval
    → cross-encoder reranking
    → gated ontology constraints
    → score-aware joint decoding
    → global consistency and schema validation
    → deterministic JSON files and output.zip
```

Bốn nguyên tắc không được phá vỡ:

1. `position` luôn được suy ra bằng code từ chuỗi gốc, không do LLM sinh.
2. ICD/RxNorm luôn được truy xuất từ terminology snapshot, không do LLM đoán từ trí nhớ.
3. Mỗi thực thể phải có bằng chứng nguồn, confidence đã hiệu chỉnh và lý do được giữ/bỏ.
4. Chỉ thêm module khi ablation chứng minh cải thiện `official_final_score`, không chỉ cải thiện F1 cục bộ.

---

# 1. Mục tiêu và phạm vi

## 1.1 Input

Một đoạn văn bản y khoa tự do có thể chứa:

- ghi chú khám bệnh;
- tiền sử bệnh và thuốc;
- danh sách thuốc;
- báo cáo xét nghiệm;
- kết luận chẩn đoán hình ảnh;
- câu phủ định, tiền sử gia đình;
- viết tắt, lỗi chính tả, từ Việt–Anh trộn;
- nhiều thực thể lặp lại hoặc nằm trong danh sách.

## 1.2 Output

```json
[
  {
    "text": "amlodipine 10 mg po daily",
    "type": "THUỐC",
    "candidates": ["308135"],
    "assertions": ["isHistorical"],
    "position": [58, 83]
  }
]
```

## 1.3 Entity types

```text
TRIỆU_CHỨNG
TÊN_XÉT_NGHIỆM
KẾT_QUẢ_XÉT_NGHIỆM
CHẨN_ĐOÁN
THUỐC
```

## 1.4 Assertions

```text
isNegated
isHistorical
isFamily
```

Assertions là **multi-label**. Một thực thể có thể đồng thời mang nhiều assertion nếu annotation contract cho phép, ví dụ bệnh trong tiền sử gia đình và bị phủ định.

## 1.5 Trường được chấm

```text
text_score       30%
assertions_score 30%
candidates_score 40%
```

Do sai type có thể gây double penalty, mục tiêu tối ưu là:

> Tối đa hóa expected official score dưới ràng buộc precision cao, thay vì tối đa hóa recall đơn thuần.

---

# 2. Definition of Done

Framework được coi là sẵn sàng chạy private test khi tất cả điều kiện sau đều đạt:

- local scorer đã được đối chiếu bằng golden cases;
- loader bảo toàn byte, BOM, newline và khoảng trắng;
- `text == raw_text[start:end]` đúng 100% trên output;
- annotation guideline đã đóng băng phiên bản;
- terminology snapshot có version, checksum và license/provenance;
- mỗi module có unit test và metric riêng;
- inference không phụ thuộc Internet/API thương mại;
- chạy lại cùng input, weights, index và seed cho output giống hệt;
- lỗi một sample không làm dừng toàn bộ batch;
- một lệnh tạo được đúng cấu trúc `output/1.json ... output/100.json` và `output.zip`;
- package có README, environment lock, model/index manifest và smoke test.

---

# 3. Phase 0 — Đặc tả bắt buộc trước khi huấn luyện

Đây là cổng bắt buộc. Không bắt đầu fine-tune nếu bốn contract dưới đây chưa hoàn thành.

## 3.1 Task contract

Tạo `specs/TASK_CONTRACT.md` và khóa các quyết định:

- `position` dùng `[start, end)` hay `[start, end]`;
- index tính trên Python Unicode code point, byte hay chuẩn khác;
- có giữ BOM/newline cuối file hay không;
- thứ tự object có ảnh hưởng scorer không;
- cách scorer ghép prediction với ground truth;
- cách xử lý entity trùng, nested và overlap;
- field nào bắt buộc hoặc optional theo từng type;
- empty list khác field bị thiếu như thế nào;
- candidate có thể chứa nhiều code trong trường hợp nào;
- assertion áp dụng cho type nào;
- ICD là biến thể nào và RxNorm snapshot nào;
- treatment của wrong-type prediction trong scorer.

Nếu BTC chưa làm rõ, triển khai hai chế độ scorer và chọn chế độ khớp toàn bộ ví dụ/golden cases.

## 3.2 Official scorer clone

`src/evaluate/official_scorer.py` là artifact ưu tiên số một.

Phải có test cho:

```text
perfect prediction
empty prediction
extra entity
missing entity
right span + wrong type
right type + shifted boundary
missing candidates field
empty candidates list
extra candidate
missing assertion
extra assertion
repeated mention
same text at different positions
zero-entity sample
```

Không dùng threshold tuning trước khi scorer local ổn định.

## 3.3 Annotation contract

Tạo `specs/ANNOTATION_GUIDE.md`, kèm ít nhất 50 ví dụ đã adjudicate. Tài liệu phải trả lời:

### Span boundary

- thuốc có bao gồm strength, dose form, route, frequency, PRN không;
- có lấy dấu câu cuối span không;
- kết quả xét nghiệm có gồm unit, range và flag H/L không;
- qualitative result được cắt thế nào;
- cụm phối hợp bệnh/triệu chứng được tách hay gộp;
- viết tắt và phần giải thích trong ngoặc được xử lý thế nào;
- nested entity có được phép không.

### Type policy

- triệu chứng so với chẩn đoán dựa trên trigger và section nào;
- bệnh trong differential diagnosis được gán type/assertion ra sao;
- tên bệnh trong chỉ định xét nghiệm có được trích xuất không;
- kết luận imaging thuộc `CHẨN_ĐOÁN` hay `KẾT_QUẢ_XÉT_NGHIỆM`;
- hoạt chất đơn lẻ và full medication mention đều là `THUỐC` hay chỉ một dạng.

### Assertion policy

- phạm vi cue theo câu, clause, bullet và section;
- cue “tiền sử” có áp dụng cho toàn danh sách thuốc không;
- `isFamily` có lan qua nhiều entity trong cùng câu không;
- nhiều assertions có được đồng thời tồn tại không;
- phần kế hoạch “loại trừ”, “theo dõi” có phải phủ định không.

## 3.4 Terminology contract

Tạo `specs/terminology_manifest.yaml`:

```yaml
icd:
  source: organizer_provided
  variant: TBD
  version: TBD
  release_date: TBD
  checksum_sha256: TBD
  allowed_code_levels: TBD
  include_inactive: false

rxnorm:
  source: organizer_provided
  release: TBD
  checksum_sha256: TBD
  allowed_ttys: TBD
  include_obsolete: false

normalization:
  preserve_punctuation: true
  accentless_alias: true
  lowercase_alias: true
```

Bộ dữ liệu do BTC cung cấp là source of truth. Không trộn code từ snapshot khác.

## 3.5 Data and model provenance

Mọi data/model/index phải có manifest:

```yaml
artifact_id: medlink-icd-index-v1
created_at: 2026-xx-xx
source_files:
  - path: data/terminology/icd.csv
    sha256: "..."
code_commit: "..."
config: configs/linking.yaml
seed: 42
license_or_usage_basis: "..."
```

Synthetic data cần lưu:

- generator/model version;
- prompt version;
- seed;
- source concepts;
- critic result;
- repair history;
- trạng thái human review;
- split group ID.

---

# 4. Kiến trúc end-to-end chính thức

```text
[0] Task Contract + Scorer + Terminology Snapshot
                    │
                    ▼
[1] Raw-byte Loader / Immutable SourceDocument
                    │
                    ▼
[2] Multi-view Lossless Normalization + Boundary Maps
                    │
                    ▼
[3] Section, List, Sentence and Clause Analysis
                    │
                    ▼
[4] Candidate Proposal Generation
      ├── deterministic medication/lab engine
      ├── encoder/span model
      └── optional <=9B LLM proposer
                    │
                    ▼
[5] Exact Source Grounding for every proposal
                    │
                    ▼
[6] Span Clustering, Boundary Resolution and Evidence Fusion
                    │
                    ▼
[7] Type Classification + Calibrated Abstention
                    │
                    ▼
[8] Section-aware Assertion Scope Detection
                    │
                    ▼
[9] Structured Clinical Parsing
      ├── medication slots
      └── lab test-result relations
                    │
                    ▼
[10] Type-specific Candidate Retrieval
      ├── exact/unique alias
      ├── BM25
      ├── character n-gram
      ├── dense retrieval
      └── abbreviation/accentless channels
                    │
                    ▼
[11] Cross-encoder Reranking
                    │
                    ▼
[12] Gated Ontology/Hierarchy Constraints
                    │
                    ▼
[13] Score-aware Joint Decoder
                    │
                    ▼
[14] Global Consistency Resolver
                    │
                    ▼
[15] JSON Schema + Semantic Validation
                    │
                    ▼
[16] Deterministic Packaging + Run Manifest
```

**Thay đổi quan trọng so với bản cũ:** exact grounding được thực hiện trước type và assertion để repeated mention luôn dùng đúng local context.

---

# 5. Core data contracts

## 5.1 Source document

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    raw_bytes: bytes
    raw_text: str
    encoding: str
    had_bom: bool
    newline_style: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

`raw_text` là bất biến trong toàn pipeline.

## 5.2 Text view and boundary map

```python
@dataclass(frozen=True)
class TextView:
    name: str
    text: str
    # len(boundary_to_raw) == len(text) + 1
    boundary_to_raw: list[int]
```

Dùng boundary map thay vì map từng ký tự để ánh xạ an toàn cả `start` và `end` khi normalization co/giãn chuỗi.

Invariant:

```python
0 <= boundary_to_raw[i] <= len(raw_text)
boundary_to_raw[i] <= boundary_to_raw[i + 1]
```

## 5.3 Span proposal

```python
@dataclass
class SpanProposal:
    proposal_id: str
    source: str
    view_name: str
    proposed_text: str
    proposed_type: str | None
    view_start: int | None
    view_end: int | None
    raw_start: int | None
    raw_end: int | None
    raw_text: str | None
    source_score: float
    metadata: dict
```

## 5.4 Fused entity hypothesis

```python
@dataclass
class EntityHypothesis:
    raw_start: int
    raw_end: int
    text: str
    evidence_sources: list[str]
    source_scores: dict[str, float]
    type_probabilities: dict[str, float]
    assertion_probabilities: dict[str, float]
    structured_slots: dict
    candidate_scores: list[dict]
    decision_trace: list[str]
```

## 5.5 Final entity

```python
@dataclass(frozen=True)
class FinalEntity:
    text: str
    type: str
    position: tuple[int, int]
    assertions: tuple[str, ...]
    candidates: tuple[str, ...] | None
```

---

# 6. Raw-byte loading và lossless normalization

## 6.1 Loader

Không dùng `.strip()`, không tự đổi newline và không tự bỏ BOM trước khi xác minh task contract.

```python
def load_source(path: str) -> SourceDocument:
    raw = Path(path).read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig" if had_bom else "utf-8")
    newline_style = detect_newline_style(text)
    return SourceDocument(
        document_id=Path(path).stem,
        raw_bytes=raw,
        raw_text=text,
        encoding="utf-8",
        had_bom=had_bom,
        newline_style=newline_style,
    )
```

Việc dùng `utf-8-sig` phải tuân theo cách BTC tính offset. Nếu BOM được tính là ký tự, loader phải giữ nó trong `raw_text`.

## 6.2 Text views

Tạo nhiều view, không sửa chuỗi gốc:

```text
raw                   exact output and offsets
nfc                    model input where safe
lower                  lexical retrieval
accentless             alias retrieval
space_canonical        rules only
abbreviation_expanded  feature view, never output
```

## 6.3 Phép chuẩn hóa

Mỗi phép biến đổi phải trả về:

```text
new_text
new_boundary_to_old_boundary
```

Sau đó compose map về raw boundary. Không cho phép normalization “không truy vết”.

## 6.4 Offset tests bắt buộc

- NFC/NFD tiếng Việt;
- ký tự ghép dấu;
- emoji hoặc ký tự ngoài BMP nếu có;
- CRLF và LF;
- tab và nhiều khoảng trắng;
- dấu gạch nối Unicode;
- dấu nháy cong;
- BOM;
- repeated substring;
- text ở đầu/cuối document;
- trailing newline.

---

# 7. Structural analysis: section, list, sentence, clause

Mục tiêu là tạo context đúng cho type và assertion.

## 7.1 Section detector

Nhận diện heading và phạm vi như:

```text
Tiền sử bệnh
Tiền sử gia đình
Thuốc trước nhập viện
Khám hiện tại
Cận lâm sàng
Chẩn đoán
Kết luận
Kế hoạch
```

Section detector dùng rule trước, classifier sau. Output:

```python
@dataclass
class Section:
    label: str
    start: int
    end: int
    confidence: float
```

## 7.2 List detector

Danh sách đánh số/bullet phải được giữ thành cấu trúc vì một cue ở đầu danh sách có thể áp dụng cho mọi item.

## 7.3 Sentence and clause segmentation

Không chỉ tách bằng dấu chấm. Cần xử lý:

- `;`, `:`, newline, bullet;
- từ nối đảo scope: `nhưng`, `tuy nhiên`, `còn`;
- chuỗi thuốc chứa `q6h:prn` không được tách nhầm;
- số thập phân không được xem là dấu hết câu.

---

# 8. Candidate proposal generation

Proposal stage ưu tiên recall nhưng mỗi nguồn có confidence và trust tier riêng.

## 8.1 Deterministic clinical engine

Đây là nguồn precision cao cho thuốc và xét nghiệm.

### Medication patterns

Nhận diện:

```text
ingredient/brand
strength and unit
dose form
route
frequency
duration
PRN
release modifier
combination separator
```

Pattern phải hỗ trợ các dạng:

```text
10 mg
0.5mg
325-650 mg
5 mg/5 mL
1 viên x 2 lần/ngày
po, iv, im, sc
qd, bid, tid, qhs, qam, q6h
prn
XR, XL, SR, CR, ER
```

### Lab patterns

Nhận diện:

```text
numeric result
range
less/greater-than
unit
qualitative result
H/L flag
reference range
```

Ví dụ:

```text
Glucose 7.2 mmol/L
HbA1c: 8,1%
CRP < 5 mg/L
HBsAg âm tính
WBC 12.3 (H)
```

## 8.2 Encoder/span model

Benchmark ít nhất:

- token classifier trên multilingual/Vietnamese encoder;
- span classifier;
- GLiNER-style model nếu phù hợp.

Output luôn gồm raw/view offsets khi model hỗ trợ token alignment.

## 8.3 LLM proposer <=9B

LLM chỉ sinh exact-copy text và type proposal. Không sinh position, candidate cuối hoặc confidence cuối.

Prompt bắt buộc:

- chỉ copy nguyên văn từ input;
- chỉ dùng 5 type hợp lệ;
- có quyền trả `[]`;
- không sửa chính tả;
- không mở rộng viết tắt;
- không gộp hai mention không liền kề.

Dùng constrained JSON decoding khi runtime hỗ trợ.

## 8.4 Source trust tiers

Ví dụ khởi tạo:

```yaml
source_trust:
  exact_unique_drug_alias: 1.00
  high_precision_medication_rule: 0.98
  lab_result_rule: 0.97
  supervised_span_model: 0.90
  llm_proposer: 0.75
  fuzzy_dictionary: 0.60
```

Giá trị thực phải được fit/calibrate trên validation.

---

# 9. Exact source grounding

Mọi proposal phải được gắn vào một raw interval trước các bước hiểu ngữ cảnh.

## 9.1 Matching cascade

```text
1. direct raw interval supplied by aligned model
2. exact raw character match
3. exact match through reversible normalized view
4. case-insensitive constrained match
5. token-boundary constrained match
6. high-threshold character fuzzy match
7. unresolved → reject proposal
```

## 9.2 Repeated mentions

Không dùng `raw_text.find(text)` một lần duy nhất. Lấy toàn bộ occurrence:

```python
def all_occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    ...
```

Chọn occurrence bằng:

- vị trí gợi ý từ source model;
- thứ tự proposal;
- section/clause context;
- không xung đột span đã ground;
- similarity của local context;
- structured relation, ví dụ test-result cùng dòng.

Nếu vẫn mơ hồ, giữ nhiều grounded hypotheses cho fusion thay vì chọn ngẫu nhiên.

## 9.3 Fuzzy grounding policy

Fuzzy chỉ được dùng khi:

- không có exact candidate;
- similarity vượt threshold riêng theo length;
- token boundary hợp lệ;
- không sửa tên concept thành concept khác;
- decision trace ghi rõ edit operations;
- output `text` luôn là substring nguyên văn của raw input, không phải text do model sinh.

---

# 10. Span clustering, fusion và resolution

## 10.1 Clustering

Group proposals khi:

- exact raw interval giống nhau;
- hoặc IoU/span overlap cao và normalized text tương thích;
- hoặc cùng structured medication anchor.

Không group chỉ vì surface text giống nhau nếu positions khác nhau.

## 10.2 Feature set cho fusion

```text
source IDs and trust
number of independent sources
exact dictionary evidence
rule specificity
model score
boundary agreement
section label
span length
character class pattern
neighboring trigger words
overlap with other proposals
structured medication/lab completeness
```

## 10.3 Fusion strategy

MVP dùng deterministic weighted rules. Phiên bản cạnh tranh có thể dùng logistic regression/GBDT meta-classifier đã calibrate.

Không đặt `min_support: 1` chung cho mọi nguồn. Một source được phép tự quyết chỉ khi thuộc precision tier cao và vượt source-specific threshold.

## 10.4 Boundary resolution

Ưu tiên theo thứ tự:

1. boundary được gold guideline hỗ trợ;
2. exact agreement của nhiều source độc lập;
3. deterministic parser có cấu trúc đầy đủ;
4. calibrated fusion score;
5. span dài/nhỏ theo policy riêng của type, không theo rule chung.

## 10.5 Overlap policy

Dùng ma trận policy:

```yaml
overlap:
  THUỐC__THUỐC: disallow_unless_distinct_positions
  TÊN_XÉT_NGHIỆM__KẾT_QUẢ_XÉT_NGHIỆM: allow_adjacent_not_nested
  TRIỆU_CHỨNG__CHẨN_ĐOÁN: disallow_same_interval
  default: challenge_or_reject_lower_score
```

---

# 11. Type classification

## 11.1 Input

```text
section label
left context
[MENTION]
right context
source features
structured slots
```

## 11.2 Model hierarchy

```text
high-precision deterministic type rule
    ↓ if unresolved
small encoder/cross-encoder classifier
    ↓ if ambiguous top-2 margin low
optional <=9B LLM fallback
```

LLM fallback không được ghi đè một rule precision cao nếu không có explicit conflict rule.

## 11.3 Hard negatives

- symptom vs diagnosis;
- diagnosis vs lab/imaging conclusion;
- lab name vs lab result;
- medication vs dosage-only fragment;
- disease in family history;
- disease in negated differential;
- procedure/test name vs result phrase;
- brand vs unrelated common word;
- abbreviation with multiple medical senses.

## 11.4 Calibration

Fit probability bằng out-of-fold predictions:

- temperature scaling cho neural classifier;
- Platt scaling hoặc isotonic nếu đủ dữ liệu;
- reliability diagram và expected calibration error;
- threshold riêng cho từng type.

## 11.5 Abstention

Giữ entity khi:

```text
fused_span_probability >= span_threshold[source/type]
and type_probability >= type_threshold[type]
and top1 - top2 >= min_type_margin[type]
```

Exception chỉ dành cho exact unique terminology/rule match đã được audit.

---

# 12. Assertion scope detection

Assertion được dự đoán sau khi mention đã có raw interval.

## 12.1 Pipeline

```text
section prior
→ trigger detection
→ clause/list/section scope boundary
→ trigger-entity association
→ multi-label classifier
→ per-label calibration
→ conflict resolution
```

## 12.2 `isNegated`

Cue gồm nhưng không giới hạn:

```text
không, chưa, phủ nhận, không ghi nhận, âm tính với,
denies, negative for, no evidence of, rule out
```

Phải phân biệt:

```text
Không sốt nhưng ho nhiều
```

`sốt` bị phủ định, `ho` không bị phủ định.

`rule out`, `theo dõi`, `nghi` không tự động đồng nghĩa `isNegated`; quyết định theo annotation contract.

## 12.3 `isHistorical`

Nguồn scope:

- cue cục bộ: `đã từng`, `trước đây`, `history of`;
- section: `Tiền sử bệnh`, `Thuốc trước nhập viện`;
- list header: cue ở đầu danh sách lan tới từng item;
- temporal expression: `năm 2020`, `3 tháng trước` nếu guideline xem là historical.

## 12.4 `isFamily`

Nguồn scope:

- section `Tiền sử gia đình`;
- kinship terms: bố, mẹ, anh, chị, em, con, ông, bà;
- English cues: family history, mother/father/sibling.

Ngưỡng `isFamily` nên cao vì false positive gây Jaccard về 0 khi GT rỗng.

## 12.5 Multi-label behavior

Ví dụ logic có thể cho phép:

```text
“Mẹ bệnh nhân không mắc đái tháo đường”
→ isFamily + isNegated
```

Chỉ áp dụng nếu annotation contract xác nhận.

## 12.6 Assertion hard masks

Nếu đề quy định assertions chỉ có ý nghĩa cho một số type, validator phải xóa assertion ở type không hợp lệ.

---

# 13. Structured clinical parsing

## 13.1 Medication parser

```python
@dataclass
class MedicationSlots:
    ingredient: list[str]
    brand: str | None
    strength_value: list[float]
    strength_unit: str | None
    numerator_value: float | None
    numerator_unit: str | None
    denominator_value: float | None
    denominator_unit: str | None
    dose_form: str | None
    route: str | None
    frequency: str | None
    release: str | None
    prn: bool | None
    combination: bool
```

Slots dùng để retrieval/reranking, không tự ý thay đổi output span.

## 13.2 Lab parser

```python
@dataclass
class LabResultSlots:
    value_text: str
    numeric_values: list[float]
    comparator: str | None
    unit: str | None
    qualitative: str | None
    flag: str | None
    reference_range: tuple[float, float] | None
```

## 13.3 Internal relations

Giữ quan hệ nội bộ không xuất ra JSON:

```text
TEST_NAME ──has_result──> TEST_RESULT
MEDICATION ──has_strength──> strength
MEDICATION ──has_route──> route
```

Relations giúp resolver xử lý adjacency và tránh gán nhầm result cho test khác.

---

# 14. Candidate linking ICD/RxNorm

Chỉ `CHẨN_ĐOÁN` và `THUỐC` đi qua linker nếu task contract quy định như vậy.

## 14.1 Candidate record

```python
@dataclass(frozen=True)
class ConceptRecord:
    code: str
    preferred_term: str
    aliases: tuple[str, ...]
    language: str | None
    active: bool
    parent_codes: tuple[str, ...]
    child_codes: tuple[str, ...]
    metadata: dict
```

RxNorm metadata nên chứa term type/granularity, ingredient, strength và dose form khi có.

## 14.2 Offline terminology preparation

- parse official files;
- remove/quarantine inactive concepts theo contract;
- normalize aliases bằng nhiều view;
- deduplicate nhưng giữ provenance;
- build reverse alias index;
- build hierarchy adjacency;
- build lexical, char-ngram và dense indexes;
- serialize manifest/checksum.

## 14.3 Dictionary-first

Direct mapping chỉ khi:

- alias match exact sau normalization được phép;
- alias ánh xạ duy nhất hoặc có deterministic disambiguation;
- concept active;
- type tương thích;
- với thuốc, structured slots không mâu thuẫn candidate.

**Không dùng negation/historical/family để chặn linking.** Assertion mô tả trạng thái mention; candidate mô tả identity của concept.

## 14.4 High-recall retrieval channels

```text
exact alias
prefix/token alias
BM25
character n-gram 3–5
accentless alias
abbreviation alias
dense bi-encoder
structured medication lookup
```

Mỗi channel trả score đã normalize và retrieval rank.

## 14.5 Query construction

### Diagnosis

```text
mention + local clause + section + nearby modifiers
```

### Medication

```text
ingredient + strength + form + release + route + full mention
```

Không đưa toàn document vào dense query nếu gây nhiễu.

## 14.6 Candidate pool

- retrieval pool: thường 20–50;
- rerank pool: 10–20;
- ontology/LLM fallback pool: 3–5;
- final candidate set: tối ưu theo expected Jaccard, thường rất nhỏ.

## 14.7 Candidate set selection

Không mặc định luôn trả top-1 hoặc top-k cố định.

Tính expected utility cho các tập:

```text
{}
{c1}
{c1, c2}
...
```

Chọn tập tối đa hóa expected candidate score sau penalty cho extra candidates.

---

# 15. Cross-encoder reranking và ontology gating

## 15.1 Reranker input

```text
[MENTION]
[LOCAL CONTEXT]
[SECTION]
[STRUCTURED SLOTS]
[CANDIDATE TERM]
[CANDIDATE ALIASES]
[CANDIDATE HIERARCHY/METADATA]
```

## 15.2 Score fusion

```text
base_score =
  α * exact_alias
+ β * bm25
+ γ * char_ngram
+ δ * dense
+ ε * structured_match
+ ζ * cross_encoder
```

Không hard-code weights cuối cùng; tune trên validation với scorer chính thức.

## 15.3 Hard negatives

### ICD

- sibling;
- parent/child;
- symptom code gần diagnosis;
- unspecified vs specific;
- cùng từ khóa nhưng khác organ/system;
- code lịch sử/không active nếu snapshot chứa.

### RxNorm

- cùng ingredient khác strength;
- cùng ingredient khác dose form;
- ingredient vs clinical drug;
- generic vs brand;
- immediate vs extended release;
- single vs combination drug.

## 15.4 Ontology gate

Ontology chỉ chạy khi một trong các điều kiện đúng:

```text
top1-top2 margin thấp
candidate cùng hierarchy branch
RxNorm slots xung đột
diagnosis granularity không rõ
cross-encoder và lexical retrieval bất đồng
```

Không chạy graph traversal cho exact unique alias.

## 15.5 Ontology rules

- type-candidate compatibility;
- active status;
- parent-child specificity;
- structured medication compatibility;
- sibling discrimination;
- duplicate/equivalent concept collapse;
- optional disease-symptom/drug-disease consistency chỉ như weak feature.

Ontology không được tự sinh code không nằm trong retrieved pool trừ khi rule được audit và scorer chứng minh lợi ích.

---

# 16. Score-aware joint decoding

Mục tiêu không phải chọn từng module độc lập mà chọn tập entity cuối có utility cao nhất.

## 16.1 Entity utility

Ví dụ khung:

```text
U(entity) =
  w_span * calibrated_span_prob
+ w_type * calibrated_type_prob
+ w_assert * expected_assertion_score
+ w_link * expected_candidate_score
- overlap_penalty
- ambiguity_penalty
- unsupported_source_penalty
```

Weights và threshold được tối ưu trực tiếp trên `official_final_score`.

## 16.2 Joint decisions

Decoder quyết định:

- giữ/bỏ entity;
- type cuối;
- assertion subset;
- candidate subset;
- chọn một trong các boundary hypotheses;
- giải quyết overlap.

## 16.3 Optimization strategy

MVP: greedy theo utility + deterministic constraints.  
Advanced: weighted interval scheduling/ILP cho overlap và candidate choices nếu latency cho phép.

---

# 17. Global consistency resolver

## 17.1 Invariants

- mỗi final entity có raw interval hợp lệ;
- `text` khớp exact substring;
- không duplicate cùng `(start,end,type)`;
- repeated mentions giữ positions riêng;
- candidate chỉ có ở type hợp lệ;
- assertions chỉ có ở type hợp lệ;
- candidate code tồn tại trong snapshot;
- output sorted deterministic.

## 17.2 Không đồng nhất entity chỉ theo text

Hai thuốc cùng ingredient nhưng khác strength có thể ánh xạ code khác. Entity identity phải dựa trên:

```text
position + local context + structured slots
```

## 17.3 Lab consistency

- test name và result không được gộp nếu schema yêu cầu tách;
- result gần nhất không phải lúc nào cũng thuộc test gần nhất: dùng line/table relation;
- không giữ result không có test nếu annotation guideline cấm;
- không ép tách nếu gold guideline coi toàn phrase là result.

## 17.4 Conflict handling

Mọi conflict phải có action xác định:

```yaml
conflict_policy:
  same_interval_different_type: keep_highest_calibrated_utility
  exact_duplicate: merge_evidence
  partial_overlap: apply_type_pair_policy
  invalid_candidate: remove_candidate_not_entity
  low_assertion_confidence: omit_assertion
  unresolved_grounding: drop_entity
```

---

# 18. JSON schema, semantic validation và packaging

## 18.1 Schema validation

Kiểm tra:

- output là JSON array;
- key hợp lệ;
- type/assertion enum;
- position đúng hai integer;
- bounds hợp lệ;
- exact substring invariant;
- candidates là list string khi field tồn tại;
- không NaN/Infinity;
- không object duplicate;
- field optional/bắt buộc đúng task contract.

## 18.2 Semantic validation

```python
assert entity["text"] == raw_text[start:end]
assert all(code in terminology for code in candidates)
```

Kiểm tra position convention bằng golden test trước khi chạy batch.

## 18.3 Deterministic ordering

Sort theo:

```text
start asc, end asc, type rank, text
```

Chỉ dùng nếu task contract xác nhận ordering không có semantics khác.

## 18.4 Packaging

```text
output/
├── 1.json
├── 2.json
...
└── 100.json
```

Zip phải chứa trực tiếp thư mục `output/`, không thêm parent folder ngoài ý muốn.

## 18.5 Pre-submit validator

Một lệnh:

```bash
python -m medlink.cli validate-submission \
  --inputs data/test \
  --zip outputs/output.zip
```

Validator kiểm tra file count, filename, JSON, offsets, code snapshot và checksum zip.

---

# 19. Data strategy

## 19.1 Dataset layers

```text
L0 official examples
L1 rule-generated unit cases
L2 synthetic clinical notes
L3 human-reviewed gold dev
L4 adversarial challenge set
L5 pseudo-labeled real-domain text if legally allowed
```

## 19.2 Gold dev set

Mục tiêu 200–500 notes, ưu tiên chất lượng hơn số lượng.

Quy trình:

```text
annotator A
annotator B
adjudication
span offset validator
terminology validator
versioned release
```

Theo dõi inter-annotator agreement riêng cho span, type và assertions.

## 19.3 Grouped splits

Không random split theo record. Group theo:

- scenario seed;
- concept seed;
- template family;
- generator prompt/version;
- paraphrase parent;
- specialty;
- note style.

Mục tiêu ngăn template leakage và alias leakage.

## 19.4 Challenge set

Bao phủ bắt buộc:

- repeated mention;
- same text, different type by context;
- nested/overlap;
- list-level historical scope;
- negation with conjunction;
- family + negation;
- abbreviations;
- misspellings;
- accentless Vietnamese;
- mixed Vietnamese-English;
- drug strength/form/release ambiguity;
- combination drugs;
- lab numeric/qualitative/range;
- ICD parent-child/sibling;
- empty-entity note;
- very long note;
- Unicode/newline edge cases.

---

# 20. Synthetic data engine

## 20.1 Generation pipeline

```text
terminology seed
→ clinical scenario planner
→ structured fact plan
→ note-style renderer
→ deterministic entity insertion
→ annotation generation
→ critic validation
→ exact span repair
→ terminology validation
→ deduplication
→ quality scoring
→ split assignment
```

Ưu tiên **annotation-first rendering**: tạo plan và surface forms trước, chèn nguyên văn vào note, sau đó offsets được code tính. Không yêu cầu LLM đếm ký tự.

## 20.2 Curriculum

### Easy

- một entity/câu;
- exact terminology;
- không assertion;
- không viết tắt.

### Medium

- nhiều entity;
- historical/negation;
- list;
- medication slots;
- lab name-result pairs.

### Hard

- type confusion;
- repeated mention;
- section-level scope;
- family + negation;
- typo/accentless/mixed language;
- ICD/RxNorm hard negatives;
- nested and boundary traps.

## 20.3 Quality gates

Reject sample nếu:

- annotation text không phải exact substring;
- offsets overlap trái guideline;
- candidate code không tồn tại;
- structured facts mâu thuẫn note;
- critic confidence thấp;
- duplicate gần với sample khác;
- template leakage sang dev/test group.

## 20.4 Error-driven synthesis

Sau mỗi experiment:

```text
collect errors
→ assign taxonomy
→ choose top error buckets by score loss
→ generate targeted cases
→ human spot-check
→ retrain/retune
```

Không sinh thêm dữ liệu đại trà nếu chưa biết bucket lỗi cần sửa.

---

# 21. Training strategy

## 21.1 Baseline first

Trước fine-tune phải có baseline:

```text
rules + exact grounding + simple type rules
+ assertion rules + BM25/alias linker
```

Baseline cung cấp error taxonomy và lower bound.

## 21.2 Span/type model

- train grouped split;
- class-weight/focal loss chỉ khi ablation chứng minh;
- early stop theo score-aware dev metric;
- lưu out-of-fold logits để calibration;
- hard-negative sampling theo confusion matrix.

## 21.3 LLM QLoRA

Chỉ fine-tune nếu LLM proposer giúp scorer sau fusion.

Yêu cầu:

- model <=9B;
- 4-bit QLoRA nếu cần;
- exact-copy objective;
- constrained output;
- mixed easy/hard curriculum;
- checkpoint selection theo downstream score, không theo train loss.

## 21.4 Bi-encoder

Positive: mention-context ↔ canonical concept.  
Negatives: in-batch + mined sibling/strength/form hard negatives.

Benchmark loss:

- InfoNCE;
- multiple-negatives ranking;
- margin ranking.

## 21.5 Cross-encoder

Train trên top retrieval mistakes. Sampling phải mô phỏng candidate pool thật, không chỉ random negatives.

## 21.6 Self-training

Pseudo-label chỉ giữ khi:

- ít nhất hai nguồn độc lập đồng thuận;
- exact grounded interval;
- same type;
- high calibrated confidence;
- không schema/terminology conflict.

Pseudo-label không được dùng để calibrate final probabilities.

---

# 22. Evaluation và calibration

## 22.1 Primary metrics

- official `text_score`;
- official `assertions_score`;
- official `candidates_score`;
- official `final_score`.

## 22.2 Diagnostic metrics

### Extraction

```text
exact-span precision/recall/F1
boundary-only error rate
type confusion matrix
per-section performance
grounding failure rate
source contribution
```

### Assertions

```text
per-label precision/recall/F1
scope accuracy
multi-label subset accuracy
false positive when GT empty
section propagation errors
```

### Linking

```text
Recall@1/@5/@10
MRR
top-1 accuracy
candidate-set Jaccard
retrieval oracle score
reranker delta
error by hierarchy/TTY/strength/form
```

### System

```text
latency p50/p95
peak VRAM/RAM
JSON validity
crash rate
abstention coverage
reproducibility hash match
```

## 22.3 Calibration protocol

- dùng out-of-fold logits;
- fit calibrator trên calibration split;
- tune thresholds trên dev khác calibration split hoặc nested CV;
- báo reliability curve;
- không tune trên test-synthetic được dùng báo cáo cuối.

## 22.4 Score-aware threshold tuning

Tune đồng thời:

```text
span acceptance by source/type
type threshold and margin
assertion threshold by label
link threshold by type
candidate set size policy
fuzzy grounding threshold
ontology gate margin
overlap penalties
```

Objective là local official scorer. Optuna chỉ là công cụ tìm kiếm; phải kiểm tra stability qua seeds/folds.

---

# 23. Ablation plan

| Ablation | Câu hỏi |
|---|---|
| rules only | lower bound |
| encoder only | neural extraction value |
| LLM proposer on/off | LLM có tăng final score không |
| exact grounding vs fuzzy fallback | fuzzy có đáng rủi ro không |
| source fusion on/off | ensemble contribution |
| type classifier on/off | giảm double penalty bao nhiêu |
| section detector on/off | assertion list/section scope |
| assertion rules vs classifier | hybrid value |
| BM25 vs char-ngram vs dense | retrieval channel value |
| structured medication parsing on/off | RxNorm precision |
| cross-encoder on/off | reranking delta |
| hard-negative training on/off | sibling/strength errors |
| ontology gate on/off | graph constraint value |
| joint decoder vs independent thresholds | score-aware decoding value |
| global resolver on/off | invalid/conflict reduction |
| grouped vs random split | leakage impact |

Ablation report luôn gồm score delta, latency delta và error bucket delta.

---

# 24. Observability và experiment tracking

## 24.1 Per-entity decision trace

Lưu JSONL nội bộ:

```json
{
  "document_id": "1",
  "span": [58, 83],
  "text": "amlodipine 10 mg po daily",
  "sources": ["med_rule", "span_model"],
  "type_probs": {"THUỐC": 0.99},
  "assertion_probs": {"isHistorical": 0.96},
  "retrieved_codes": ["308135", "..."],
  "final_codes": ["308135"],
  "decisions": ["exact_grounded", "section_history", "rx_slots_match"]
}
```

Không đưa trace vào submission.

## 24.2 Run manifest

```json
{
  "run_id": "...",
  "git_commit": "...",
  "config_hash": "...",
  "model_hashes": {},
  "index_hashes": {},
  "input_hash": "...",
  "seed": 42,
  "environment": {},
  "started_at": "...",
  "ended_at": "..."
}
```

## 24.3 Error taxonomy

Mỗi false positive/negative được gắn một bucket duy nhất và optional secondary buckets:

```text
BOUNDARY
TYPE_CONFUSION
NEGATION_SCOPE
HISTORICAL_SCOPE
FAMILY_SCOPE
DRUG_PARSE
LAB_PAIRING
ICD_HIERARCHY
RX_STRENGTH_FORM
ABBREVIATION
GROUNDING
CALIBRATION
SCHEMA
```

---

# 25. Reproducibility, security và failure handling

## 25.1 Reproducibility

- lock Python/CUDA/package versions;
- fixed seeds;
- deterministic inference where supported;
- no live downloads during scoring;
- local artifact registry;
- checksums for weights/indexes/data;
- config-driven paths;
- one-command smoke test.

## 25.2 Offline mode

CI phải có test chạy với network disabled. Mọi model/tokenizer/index phải tồn tại local.

## 25.3 Failure handling

- lỗi một extractor → tiếp tục bằng các nguồn còn lại;
- LLM invalid JSON → retry tối đa cấu hình, sau đó abstain;
- out-of-memory → fallback profile hoặc smaller batch;
- terminology index missing → fail fast trước batch;
- sample exception → ghi error, tạo output an toàn theo policy, tiếp tục batch;
- invalid final entity → drop entity, không sửa offset đoán mò.

## 25.4 Medical safety

Đây là hệ thống thi trích xuất dữ liệu, không dùng output để ra quyết định điều trị thực tế. README phải ghi rõ giới hạn này.

---

# 26. Repository chuẩn

```text
medlink_ie/
├── README.md
├── pyproject.toml
├── uv.lock / poetry.lock / requirements-lock.txt
├── Dockerfile
├── Makefile
├── configs/
│   ├── pipeline.yaml
│   ├── extraction.yaml
│   ├── assertions.yaml
│   ├── linking.yaml
│   ├── thresholds.yaml
│   └── profiles/
│       ├── fast.yaml
│       └── competition.yaml
├── specs/
│   ├── TASK_CONTRACT.md
│   ├── ANNOTATION_GUIDE.md
│   ├── terminology_manifest.yaml
│   └── json_schema.json
├── data/
│   ├── official/
│   ├── synthetic/
│   ├── gold/
│   ├── challenge/
│   └── terminology/
├── artifacts/
│   ├── models/
│   ├── indexes/
│   ├── calibrators/
│   └── manifests/
├── src/medlink/
│   ├── io/
│   ├── normalize/
│   ├── structure/
│   ├── propose/
│   ├── ground/
│   ├── fuse/
│   ├── type_classify/
│   ├── assertions/
│   ├── clinical_parse/
│   ├── retrieve/
│   ├── rerank/
│   ├── ontology/
│   ├── decode/
│   ├── resolve/
│   ├── validate/
│   ├── evaluate/
│   ├── tracking/
│   └── cli.py
├── scripts/
│   ├── prepare_terminology.py
│   ├── build_indexes.py
│   ├── generate_synthetic.py
│   ├── train_span_type.py
│   ├── train_assertions.py
│   ├── train_biencoder.py
│   ├── train_crossencoder.py
│   ├── fit_calibrators.py
│   ├── tune_thresholds.py
│   ├── run_inference.py
│   ├── evaluate.py
│   └── package_submission.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/
│   ├── regression/
│   └── smoke/
├── reports/
├── outputs/
└── .github/workflows/
```

---

# 27. Configuration chuẩn

## 27.1 Pipeline profile

```yaml
profile: competition
seed: 42
offline: true
fail_fast_on_missing_artifact: true

proposal_sources:
  medication_rules: true
  lab_rules: true
  span_model: true
  llm_proposer: false

llm:
  max_parameters_billion: 9
  constrained_json: true
  max_retries: 1

runtime:
  batch_size: 8
  max_gpu_memory_gb: TBD
  max_latency_seconds_per_sample: TBD
```

## 27.2 Initial thresholds

Chỉ là giá trị khởi tạo, không phải giá trị cuối:

```yaml
grounding:
  fuzzy_enabled: true
  fuzzy_min_similarity_short: 0.98
  fuzzy_min_similarity_long: 0.95

span_acceptance:
  high_precision_rule: 0.90
  supervised_model: 0.85
  llm_only: 0.95

minimum_type_margin:
  THUỐC: 0.08
  CHẨN_ĐOÁN: 0.12
  TRIỆU_CHỨNG: 0.12
  TÊN_XÉT_NGHIỆM: 0.10
  KẾT_QUẢ_XÉT_NGHIỆM: 0.10

assertion:
  isNegated: 0.90
  isHistorical: 0.90
  isFamily: 0.95

ontology_gate:
  top1_top2_margin: 0.08
```

## 27.3 Feature flags

Mỗi module lớn có feature flag để ablation không cần sửa code.

---

# 28. Inference pseudocode

```python
def run_pipeline(document: SourceDocument, resources: Resources) -> list[dict]:
    views = build_text_views(document)
    structure = analyze_structure(document.raw_text)

    proposals = []
    proposals += resources.medication_rules.propose(document, views, structure)
    proposals += resources.lab_rules.propose(document, views, structure)
    proposals += resources.span_model.propose(document, views, structure)

    if resources.config.llm_proposer_enabled:
        proposals += resources.llm_proposer.propose(document, views, structure)

    grounded = []
    for proposal in proposals:
        grounded.extend(
            ground_proposal(
                proposal=proposal,
                raw_text=document.raw_text,
                views=views,
                structure=structure,
            )
        )

    hypotheses = cluster_and_fuse(grounded, structure, resources.calibrators)

    typed = []
    for hyp in hypotheses:
        typed_hyp = classify_type(hyp, document.raw_text, structure, resources)
        if accept_span_and_type(typed_hyp, resources.thresholds):
            typed.append(typed_hyp)

    asserted = [
        classify_assertions(h, document.raw_text, structure, resources)
        for h in typed
    ]

    parsed = [
        parse_structured_clinical_fields(h, document.raw_text, resources)
        for h in asserted
    ]

    linked = []
    for hyp in parsed:
        if hyp.final_type in {"CHẨN_ĐOÁN", "THUỐC"}:
            pool = retrieve_candidates(hyp, document.raw_text, resources)
            ranked = rerank_candidates(hyp, pool, document.raw_text, resources)
            constrained = apply_gated_ontology(hyp, ranked, resources)
            hyp.candidate_scores = constrained
        linked.append(hyp)

    decoded = score_aware_joint_decode(linked, resources)
    resolved = resolve_global_conflicts(decoded, document.raw_text, resources)
    final_entities = validate_and_serialize(resolved, document.raw_text, resources)

    return final_entities
```

Batch runner:

```python
def run_batch(input_dir, output_dir, resources):
    preflight_validate_resources(resources)
    for path in sorted_input_files(input_dir):
        try:
            doc = load_source(path)
            result = run_pipeline(doc, resources)
            write_json_atomic(output_dir / f"{doc.document_id}.json", result)
        except Exception as exc:
            handle_sample_failure(path, exc, output_dir, resources.config)
    validate_output_directory(input_dir, output_dir, resources)
```

---

# 29. Test strategy

## 29.1 Unit tests

- boundary map composition;
- all-occurrence grounding;
- medication slot parser;
- lab value parser;
- section/list propagation;
- Jaccard/candidate scoring;
- schema validation;
- terminology lookup.

## 29.2 Golden tests

Golden tests không thay đổi khi refactor:

- official example;
- wrong type double penalty;
- exact offsets;
- repeated mentions;
- empty fields;
- medication strengths;
- lab qualitative result;
- family/negation scope.

## 29.3 Integration tests

- raw file → final JSON;
- terminology files → indexes → retrieval;
- model logits → calibrator → thresholds;
- directory → output.zip.

## 29.4 Regression tests

Mỗi bug đã sửa phải thêm một fixture. CI fail nếu final score giảm quá tolerance trên regression set.

## 29.5 Smoke tests

- CPU-only tiny profile;
- GPU competition profile;
- network disabled;
- clean container build;
- one sample and full directory.

---

# 30. Roadmap triển khai

## Sprint 0 — Contract và scorer

Deliverables:

- task contract;
- scorer clone;
- annotation guideline v0.1;
- terminology manifest;
- official example golden test;
- raw offset test suite.

Exit gate: scorer và offsets được team thống nhất.

## Sprint 1 — Deterministic baseline

- raw loader/normalization;
- structure analyzer;
- drug/lab rules;
- exact grounding;
- simple type/assertion rules;
- alias/BM25 linker;
- JSON/package validator.

Exit gate: end-to-end output hợp lệ bằng một lệnh.

## Sprint 2 — Gold dev và error taxonomy

- annotate/adjudicate gold dev;
- challenge set;
- baseline report;
- top error buckets.

Exit gate: biết rõ score loss nằm ở đâu.

## Sprint 3 — Neural extraction/type

- span/type model benchmark;
- source fusion;
- calibration;
- score-aware thresholds.

Exit gate: final score tăng ổn định qua folds/seeds.

## Sprint 4 — Assertions

- section/list propagation;
- scope rules;
- assertion classifier;
- per-label calibration.

Exit gate: giảm false positive khi assertion GT rỗng.

## Sprint 5 — Linking

- terminology enrichment;
- char-ngram/dense retrieval;
- structured medication parser;
- bi-encoder/cross-encoder;
- hard negatives;
- candidate set decoder.

Exit gate: retrieval oracle cao và candidate Jaccard tăng.

## Sprint 6 — Ontology gating và joint decoder

- hierarchy constraints;
- top-margin gate;
- global resolver;
- ILP/weighted scheduling nếu cần;
- full ablation.

Exit gate: graph/ontology có positive score delta sau latency cost.

## Sprint 7 — Packaging và reproduce drill

- clean container;
- offline inference;
- README;
- artifact manifests;
- team khác dựng lại từ đầu;
- submission validator.

Exit gate: reproduce thành công trên máy sạch.

---

# 31. Model selection protocol

Không khóa model theo danh tiếng. Dùng benchmark matrix:

| Component | Candidates | Primary criterion | Secondary criterion |
|---|---|---|---|
| span/type | encoder/span models | official score delta | latency/VRAM |
| LLM proposer | <=9B instruct models | precision after fusion | JSON validity |
| embeddings | multilingual/biomedical | retrieval oracle | index size |
| cross-encoder | small multilingual models | candidate Jaccard | throughput |
| assertion | rules/encoder | per-label Jaccard impact | calibration |

Mỗi model candidate dùng cùng data split, scorer và runtime profile.

---

# 32. Acceptance checklist trước submission

## Correctness

- [ ] 100% final spans exact-grounded.
- [ ] Position convention khớp golden tests.
- [ ] Không type ngoài enum.
- [ ] Không assertion/candidate ở type không hợp lệ.
- [ ] Mọi code tồn tại trong snapshot.
- [ ] Repeated mentions không bị dùng chung position.
- [ ] `output.zip` đúng cấu trúc.

## Performance

- [ ] Threshold được tune theo official scorer.
- [ ] Calibration dùng out-of-fold predictions.
- [ ] Có ablation cho LLM, dense, reranker và ontology.
- [ ] Không module nào được giữ chỉ vì “có vẻ hợp lý”.
- [ ] Latency/VRAM nằm trong budget.

## Reproducibility

- [ ] Git commit được tag.
- [ ] Config, weights, index có checksum.
- [ ] Environment lock hoàn chỉnh.
- [ ] Network-disabled smoke test pass.
- [ ] Một thành viên khác reproduce được.

## Documentation

- [ ] README cài đặt.
- [ ] README inference.
- [ ] Data/model provenance.
- [ ] Hardware requirement.
- [ ] Known limitations.
- [ ] Troubleshooting.

---

# 33. Risk register

| Risk | Impact | Detection | Mitigation |
|---|---:|---|---|
| scorer local sai | Critical | mismatch golden examples | clone/test trước model |
| offset lệch do Unicode/newline | Critical | substring invariant fail | raw loader + boundary maps |
| đúng span sai type | Critical | confusion matrix | separate classifier + abstention |
| assertion lan sai scope | High | section/list challenge set | structural analysis + scope model |
| candidate extra làm giảm Jaccard | High | candidate-set ablation | expected utility decoder |
| RxNorm sai strength/form | High | slot error buckets | structured parser + hard negatives |
| ICD quá cụ thể/quá chung | High | hierarchy analysis | gated hierarchy rerank |
| synthetic leakage | High | random-vs-group split gap | grouped split |
| LLM hallucination | High | grounding failure | exact-copy + grounding + abstain |
| graph gây noise/latency | Medium/High | ablation and profiling | gate, not default |
| model/index không tải offline | Critical | network-disabled test | vendor artifacts locally |
| private reproduce fail | Critical | clean-machine drill | lock + manifests + README |
| một sample crash toàn batch | Medium | integration fault injection | sample isolation |

---

# 34. MVP và competition profile

## 34.1 MVP hợp lệ

```text
raw loader
→ lossless views
→ section/list rules
→ medication/lab deterministic proposals
→ exact grounding
→ rule/type classifier
→ assertion rules
→ alias + BM25 linking
→ schema validation
→ package output
```

MVP phải hoàn thành trước khi thêm LLM hoặc graph.

## 34.2 Competition profile

```text
triple-source proposals
→ exact grounding
→ calibrated source fusion
→ calibrated type classifier
→ section-aware assertion hybrid
→ structured medication/lab parsing
→ exact + BM25 + char-ngram + dense retrieval
→ cross-encoder reranking
→ gated ontology constraints
→ score-aware joint decoding
→ global resolver
→ deterministic validation/package
```

## 34.3 Fast fallback profile

Tắt LLM, dense và ontology; giữ rules, encoder, lexical retrieval và cross-encoder nhỏ nếu đủ latency.

---

# 35. Các quyết định không triển khai ở baseline

- full GraphRAG/hypergraph indexing cho mọi query;
- autonomous multi-agent loop trong inference;
- LLM sinh trực tiếp ICD/RxNorm code;
- LLM sinh character offsets;
- fuzzy grounding không threshold;
- union tất cả span proposal;
- một threshold chung cho mọi type/assertion;
- random split synthetic;
- same-text global candidate propagation;
- online API hoặc live terminology lookup.

Các hướng này chỉ được mở lại khi baseline ổn định và ablation chứng minh lợi ích.

---

# 36. Kết luận

MedLink-IE v2.0 đã chuyển từ một bản thiết kế kiến trúc tốt thành một **đặc tả triển khai có cổng kiểm soát**. Các bổ sung quan trọng nhất là:

1. Phase 0 khóa scorer, offset, annotation và terminology trước training.
2. Exact grounding được chuyển lên trước type/assertion.
3. Candidate fusion có source-specific trust và calibration.
4. Medication/lab được parse thành cấu trúc để giải quyết RxNorm và test-result pairing.
5. Candidate set được chọn theo expected Jaccard thay vì top-k cố định.
6. Ontology/graph chỉ chạy qua gate cho ca nhập nhằng.
7. Joint decoder tối ưu trực tiếp official score.
8. Reproducibility, failure handling, testing và packaging được định nghĩa như yêu cầu sản phẩm.

Thứ tự thực hiện tối ưu là:

> scorer/contract → deterministic baseline → gold dev/error taxonomy → neural modules → linking → ontology gating → reproduce drill.

Không bắt đầu bằng fine-tuning LLM hoặc xây GraphRAG. Bắt đầu bằng hệ thống đo đúng, offset đúng và baseline chạy được từ đầu đến cuối.

---

# 37. Nguồn thiết kế

- Đề bài và quy định chi tiết Viettel AI Race vòng sơ loại.
- Bản phân tích chiến lược trích xuất thông tin y khoa.
- Báo cáo chuyên sâu về kiến trúc trích xuất và liên kết thực thể y khoa.
- *Ontological Reasoning Mechanism for Medical Knowledge*.
- *Retrieval-Augmented Generation with Hierarchical Knowledge*.
- *A-RAG: Scaling Agentic Retrieval-Augmented Generation via Hierarchical Retrieval Interfaces*.
- *When to Use Graphs in RAG: A Comprehensive Analysis for Graph Retrieval-Augmented Generation*.
