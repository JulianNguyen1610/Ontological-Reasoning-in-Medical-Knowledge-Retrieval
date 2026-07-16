# ANNOTATION GUIDE — Medical Entity Extraction

**Version:** 1.0.0-framework_v1
**Status:** Framework-derived annotation policy; scorer-dependent rules remain configurable

## 1. Status and rule-ID convention

Only rules marked **CONFIRMED** may produce gold labels. Rules marked
**NEEDS_ADJUDICATION** are routing questions, not defaults. The synthetic-data
generator is not annotation authority.

| Rule ID | Status | Requirement |
|---|---|---|
| GEN-001 | CONFIRMED | Annotate exact substrings from unmodified raw text. |
| GEN-002 | CONFIRMED | Do not normalize, trim, or otherwise rewrite output text. |
| GEN-003 | CONFIRMED | Compute half-open positions with raw Python Unicode-string indexing (TASK_CONTRACT C002/C003). |
| GEN-004 | CONFIRMED | Record every ambiguous case in the adjudication matrix. |
| GEN-005 | CONFIRMED | Only a BTC-confirmed decision can become a training label, expected rejection, or scorer golden. |
| TYPE-001 through TYPE-004 | NEEDS_ADJUDICATION | Entity-type decision tree leaves. |
| SPAN-001 through SPAN-006 | NEEDS_ADJUDICATION | Boundary, nesting, overlap, and repeated-mention policy. |
| ASSERT-001 through ASSERT-006 | NEEDS_ADJUDICATION | Assertion triggers, scope, and combinations. |
| MED-001 through MED-005 | CONFIRMED | Framework-derived medication component boundaries, authorized for implementation on 2026-07-16. |
| LAB-001 through LAB-004 | NEEDS_ADJUDICATION | Laboratory name/result boundaries. |

## 2. Entity-type decision trees

The following trees are review routing aids. They deliberately do **not**
assign a type while their leaves are unresolved.

### 2.1 Symptom versus diagnosis

```text
Exact raw substring (GEN-001)
  └─ Is it a symptom, sign, condition, or diagnostic statement?
       └─ Yes/unclear → TYPE-001: NEEDS_ADJUDICATION
```

Questions for BTC: diagnostic triggers, possible/differential language,
imaging conclusions, and conditions such as obesity or pain syndromes.

### 2.2 Test name versus test result

```text
Exact raw substring (GEN-001)
  └─ Is it a procedure/analyte/abbreviation, a value/finding, or both?
       └─ Any branch → TYPE-002: NEEDS_ADJUDICATION
```

Questions for BTC: abbreviations, imaging/procedure names, qualitative values,
units, ranges, flags, and microbiology findings.

### 2.3 Medication versus dosage fragment

```text
Exact raw substring (GEN-001)
  └─ Does the phrase include an ingredient/brand and adjacent administration data?
       └─ Any inclusion or split decision → TYPE-003 / MED-001: NEEDS_ADJUDICATION
```

### 2.4 Diagnosis versus imaging finding

```text
Exact raw substring (GEN-001)
  └─ Is the finding reported in imaging/procedure text?
       └─ TYPE-004: NEEDS_ADJUDICATION
```

## 3. Span boundary rules

| Rule ID | Status | Decision required from BTC |
|---|---|---|
| SPAN-001 | CONFIRMED | Text must be an exact raw substring (GEN-001). |
| SPAN-002 | CONFIRMED | Use raw Python Unicode-string positions with `[start, end)` boundaries (TASK_CONTRACT C002/C003). |
| SPAN-003 | NEEDS_ADJUDICATION | Punctuation and coordination inclusion. |
| SPAN-004 | NEEDS_ADJUDICATION | Nested and partially overlapping spans. |
| SPAN-005 | NEEDS_ADJUDICATION | Repeated mentions: one entity per occurrence, including identical text in different contexts. |
| SPAN-006 | NEEDS_ADJUDICATION | Medication and laboratory component inclusion. |

## 4. Assertion rules and scope examples

No assertion is inferred from a cue until BTC confirms trigger and scope rules.

| Rule ID | Status | Examples requiring adjudication |
|---|---|---|
| ASSERT-001 | NEEDS_ADJUDICATION | `không đau ngực nhưng có hồi hộp` — contrast-clause scope. |
| ASSERT-002 | NEEDS_ADJUDICATION | `không loại trừ viêm phổi` / `nghi viêm ruột thừa` — uncertainty and rule-out wording. |
| ASSERT-003 | NEEDS_ADJUDICATION | `tiền sử dùng amlodipine` / medication-list headings — historical scope. |
| ASSERT-004 | NEEDS_ADJUDICATION | `mẹ bị đái tháo đường` / `gia đình không ai dị ứng thuốc` — family scope. |
| ASSERT-005 | NEEDS_ADJUDICATION | `anh trai không bị lao phổi` — family plus negation. |
| ASSERT-006 | NEEDS_ADJUDICATION | Multiple simultaneous labels and allowed label combinations. |

## 5. Medication and laboratory-specific rules

| Rule ID | Status | Decision required from BTC |
|---|---|---|
| MED-001 | CONFIRMED | A `THUỐC` span starts at a matched ingredient or brand alias. A dosage fragment without an adjacent matched alias is not a medication span. |
| MED-002 | CONFIRMED | Include contiguous strength/unit/range, dose form, route, frequency, duration, PRN, and release modifier when they modify the ingredient/brand in the same medication expression. |
| MED-003 | CONFIRMED | Include contiguous combination components and their internal separator when they form one medication expression; do not split a combination solely because it has multiple ingredients. |
| MED-004 | CONFIRMED | Do not include a list marker, terminal punctuation, or an indication/treatment clause in the medication span. Assertion scope for historical/current/discontinued status remains governed by ASSERT rules. |
| MED-005 | CONFIRMED | Preserve internal punctuation required by a component, including dosage slashes/hyphens and `:` in compact frequency/PRN forms such as `qam:prn`; preserve the exact raw substring. |
| LAB-001 | NEEDS_ADJUDICATION | Test/procedure name and abbreviation inclusion. |
| LAB-002 | NEEDS_ADJUDICATION | Numeric value, unit, range, and H/L flag inclusion. |
| LAB-003 | NEEDS_ADJUDICATION | Qualitative and microbiology finding boundaries. |
| LAB-004 | NEEDS_ADJUDICATION | Imaging/procedure finding type and assertion treatment. |

### 5.1 Medication boundary policy

The following policy is frozen for implementation because it is the most direct
reading of the BTC-provided framework output example (`amlodipine 10 mg po
daily`), its required medication pattern families, and its requirement not to
split `q6h:prn` structurally.

1. Emit one precision-first `THUỐC` proposal for a contiguous medication
   expression that begins with an ingredient or brand alias.
2. Extend rightward only across adjacent components recognized by MED-002,
   MED-003, or MED-005. Stop before a treatment indication, a new list item,
   a terminal sentence/list punctuation mark, or unrelated prose.
3. Include an ingredient-only mention when it is an alias match. Do not emit a
   dosage, route, frequency, or unit without that anchor as `THUỐC`.
4. For `clonazepam 0.5 mg po qam:prn`, the full raw substring is one proposal.
   For a combination product, the full contiguous combination is one proposal
   and component spans are recorded in proposal evidence.
5. A parenthesized generic/brand counterpart is included only when it is
   contiguous and part of the same medication expression; the enclosing
   parentheses are excluded unless they are required to preserve an internal
   component boundary. This is a conservative project policy, not scorer
   evidence.

These rules govern proposal assembly only. They do not infer RxNorm codes or
final assertions, and all final positions remain raw-text positions.

## 6. Overlap, nesting, and repeated mentions

`SPAN-004` and `SPAN-005` use the explicit `framework_v1` review policy: retain
each positional candidate separately, but record an expected rejection unless a
confirmed type/boundary rule yields an exact entity. Do not propagate an
assertion from one repeated surface form to another without a confirmed local
scope rule.

## 7. Adjudication template

```yaml
case_id: ""
raw_text: ""
expected_entities: null # null until BTC supplies exact text/type/assertions/candidates/position
rationale: ""
rule_ids: []
ambiguity_status: NEEDS_ADJUDICATION
reviewer_decision:
  status: PENDING # PENDING | CONFIRMED | REJECTED
  reviewer: null
  decided_at: null
  entities: null
  rationale: null
  btc_reference: null
```

## 8. Adjudication protocol

1. Select a fixture from `tests/fixtures/annotation/adjudication_matrix.yaml`.
2. Apply only CONFIRMED rules. If an unresolved rule is required, record an
   explicit `framework_v1` expected rejection with the blocking rule ID.
3. BTC supplies exact entities and confirms the offset convention before any
   position is recorded.
4. Record the reviewer decision, BTC reference, and newly confirmed rule ID.
5. Promote a case to gold only after the decision is complete.

## 9. Change log

### 1.0.0-framework_v1 — 2026-07-16

- Confirmed raw Python Unicode-string indexing and half-open boundaries from
  TASK_CONTRACT C002/C003.
- Versioned the matrix policy: framework-derived medication cases may be gold;
  cases without an authorized exact policy are explicit expected rejections.

### 0.3 — 2026-07-16

- Froze MED-001 through MED-005 as framework-derived project policy following
  explicit user authorization.
- Added an implementable medication span-assembly policy for Task 2.2.
- Kept laboratory, type, assertion, offset, overlap, and scorer-dependent
  rules pending where the framework does not resolve them.
