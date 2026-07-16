# TASK CONTRACT — Viettel AI Race Medical IE

**Version:** 0.1  
**Status:** Draft — awaiting BTC adjudication  
**Owners:**  
**Last updated:**

## 1. Input contract

- Encoding:
- BOM policy:
- Newline policy:
- Whitespace preservation:
- Input filename convention:
- Offset unit: Unicode code point / byte / other
- Position convention: `[start, end)` / `[start, end]`

## 2. Entity schema

| Type | Allowed assertions | Candidate source | Boundary policy |
|---|---|---|---|
| TRIỆU_CHỨNG |  | none |  |
| TÊN_XÉT_NGHIỆM |  | none |  |
| KẾT_QUẢ_XÉT_NGHIỆM |  | none |  |
| CHẨN_ĐOÁN |  | ICD |  |
| THUỐC |  | RxNorm |  |

## 3. Field policy

- Required keys:
- Optional keys:
- Missing `candidates` vs `candidates: []`:
- Missing `assertions` vs `assertions: []`:
- Unknown keys:
- Ordering policy:
- Duplicate object policy:

## 4. Matching and scoring

- Prediction–GT entity matching algorithm:
- Wrong type behavior:
- WER tokenization:
- Candidate Jaccard aggregation:
- Assertion Jaccard aggregation:
- Empty-set behavior:
- Multi-code candidate behavior:

## 5. Span policy

- Nested spans:
- Partial overlap:
- Repeated mentions:
- Punctuation:
- Medication strength/form/route/frequency:
- Lab unit/range/flag:

## 6. Golden decisions

| Case ID | Input | Expected output | Decision rationale |
|---|---|---|---|
| G001 |  |  |  |

### 6.1 Adjudication gate

No case becomes a golden decision until BTC (or a designated adjudicator using
BTC-confirmed material) supplies the expected entity objects and scorer result.
In particular, this contract does **not** infer a span, assertion, overlap, or
field-serialization rule from the synthetic-data generator.

## 7. Open questions for BTC

1. Provide a canonical raw-byte fixture for the public example and confirm the
   position convention and offset unit.
2. Specify prediction–GT matching, WER tokenization, and Jaccard aggregation,
   including wrong type, duplicates, nested spans, partial overlap, and order.
3. Specify field presence (`[]` versus omission), assertion applicability and
   multi-label combinations, medication/lab boundaries, and terminology
   snapshot versions.
