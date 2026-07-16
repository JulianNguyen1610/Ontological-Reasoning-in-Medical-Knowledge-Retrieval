# ANNOTATION GUIDE — Medical Entity Extraction

**Version:** 0.1  
**Status:** Draft — no adjudicated entity policy yet

> The blank policy fields below are intentional unresolved decisions.  They are
> not defaults, and the current synthetic-data pipeline must not be treated as
> the annotation authority.

## 1. General principles

1. Annotate exact substrings only.
2. Never normalize output text.
3. Compute offsets by code.
4. Follow the most specific rule in this guide.
5. Record ambiguous cases for adjudication.

## 2. Entity boundaries

### 2.1 TRIỆU_CHỨNG

- Include:
- Exclude:
- Coordination policy:
- Examples:

### 2.2 CHẨN_ĐOÁN

- Diagnostic triggers:
- Differential/possible diagnosis policy:
- Imaging conclusion policy:
- Examples:

### 2.3 THUỐC

- Include ingredient/brand:
- Include strength:
- Include dose form:
- Include route/frequency/PRN:
- Combination drug policy:
- Examples:

### 2.4 TÊN_XÉT_NGHIỆM

- Include abbreviations:
- Imaging/procedure policy:
- Examples:

### 2.5 KẾT_QUẢ_XÉT_NGHIỆM

- Numeric result:
- Unit:
- Reference range:
- Qualitative result:
- H/L flag:
- Examples:

## 3. Type disambiguation

| Ambiguity | Rule | Positive example | Counterexample |
|---|---|---|---|
| symptom vs diagnosis |  |  |  |
| test name vs result |  |  |  |
| diagnosis vs imaging result |  |  |  |
| medication vs dosage fragment |  |  |  |

## 4. Assertions

### 4.1 isNegated

- Trigger list:
- Clause boundary:
- Conjunction exceptions:
- “rule out / theo dõi / nghi” policy:

### 4.2 isHistorical

- Local temporal cues:
- Section-level propagation:
- Medication-list policy:

### 4.3 isFamily

- Kinship list:
- Section-level propagation:
- Multiple family members:

### 4.4 Multi-label cases

- Family + negated:
- Historical + negated:
- Allowed combinations:

## 5. Overlap and repeated mentions

- Nested policy:
- Same text at different positions:
- Same interval, competing types:

## 6. Adjudication log

| ID | Text | Annotator A | Annotator B | Final | Rationale |
|---|---|---|---|---|---|

## 7. Adjudication protocol for adversarial fixtures

1. Select a case from `ADVERSARIAL_ANNOTATION_CASES.md`.
2. Record competing exact-substring annotations without normalizing the raw
   text; compute positions by code only after the position contract is known.
3. Cite the applicable confirmed BTC rule.  If none exists, leave `Final` as
   `NEEDS_ADJUDICATION` and add the question to `TASK_CONTRACT.md`.
4. Only a completed `Final` decision may become a training label, expected
   rejection, or scorer golden.
