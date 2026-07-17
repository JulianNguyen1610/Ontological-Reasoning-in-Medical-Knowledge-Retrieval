# TASK CONTRACT — Viettel AI Race Medical IE

**Version:** 1.0.0-framework_v1
**Status:** Draft — external competition contract and scorer material pending
**Owners:** Unassigned
**Last updated:** 2026-07-16

## 1. Purpose and evidence policy

This document is the repository's decision record for competition-facing
behavior. It deliberately distinguishes:

- **CONFIRMED**: supported by a binding project invariant or BTC/official
  material available in this repository;
- **ASSUMED**: a reversible implementation default derived from the framework,
  not from BTC/official material; and
- **UNKNOWN**: must not be inferred or encoded as a competition rule.

The BTC-provided framework and playbook are binding project material. No
separate competition statement, official scorer, frozen terminology snapshot,
or externally scored examples are present in the workspace as of this version.
The legacy synthetic-data generator is explicitly not evidence for this
contract.

## 2. Decision table

| ID | Contract item | Current decision | Evidence/source | Status | Risk if wrong | Verification method | Required golden test |
|---|---|---|---|---|---|---|---|
| C001 | Raw text preservation | Raw source bytes and decoded raw text are immutable; final entity text must equal the raw slice selected by its position. | `AGENTS.md` architectural invariants; `ANNOTATION_GUIDE.md` GEN-001/002 | CONFIRMED | Any normalization, trim, or newline conversion can invalidate every span. | Raw-byte fixture plus semantic validator. | G001 raw-slice equality with whitespace, CRLF, and Unicode. |
| C002 | Character indexing unit | Internal and framework_v1 positions use raw Python Unicode-string indexes (one Python `str` code point per index). | User-authorized framework-derived policy; Framework §3.1 requires this contract decision; `AGENTS.md` raw-slice invariant. | CONFIRMED for framework_v1 | A future organizer scorer may use a different unit. | Verify raw slices with BMP, combining-mark, and non-BMP fixtures. | G002 non-ASCII/BMP and G003 non-BMP offset fixture. |
| C003 | Position endpoint convention | Positions are half-open `[start, end)`. Framework §1.2 gives `amlodipine 10 mg po daily` (length 25) at `[58, 83]`; `raw_text[58:83]` is the exact mention. | User-authorized Framework §1.2 output example; `tests/golden/test_framework_contract.py`. | CONFIRMED for framework_v1 | An unavailable external scorer could differ despite the framework example. | Golden raw-slice test and semantic validator. | G004 framework §1.2 position example; G005 final-character entity. |
| C004 | UTF-8/BOM policy | Loader exposes `preserve`, `strip`, and `reject`. Default `strip` is a reversible local default, not a confirmed submission rule. | Framework §6.1 example; Raw Loader design note | ASSUMED | Preserving versus stripping BOM changes positions at document start. | BTC canonical file with and without BOM; compare expected span positions. | G006 each BOM mode with an entity at offset zero. |
| C005 | Newline and whitespace effects | Preserve raw decoded newline and whitespace; framework_v1 indexes count them exactly as Python string characters. | `AGENTS.md`; `ANNOTATION_GUIDE.md` GEN-001/002; C002/C003. | CONFIRMED for framework_v1 | Organizer input decoding rules may differ. | CRLF/LF and whitespace raw-slice fixtures. | G007 CRLF, LF, mixed newline, leading/trailing spaces. |
| C006 | Entity matching algorithm | Prediction-to-gold alignment is unknown. Do not derive it from synthetic-data utilities. | Framework §3.1; `TASK_CONTRACT.md` v0.1 open question 2 | UNKNOWN | Local scorer, threshold tuning, and error analysis can optimize the wrong objective. | Obtain official scorer or enough official scored examples to discriminate algorithms. | G008 repeated text; G009 shifted boundary; G010 duplicate prediction. |
| C007 | Repeated identical mentions | Keep occurrences positionally distinct in internal representations. Official matching treatment is unknown. | `AGENTS.md`; Framework §9.2 and §17.1 | CONFIRMED internally; UNKNOWN for scorer | Surface-text deduplication can merge different contexts. | Official repeated-mention example/scorer. | G008 two identical strings at different raw positions. |
| C008 | Output ordering | Sort deterministically by `start asc, end asc, type rank, text`. | Framework §18.3. | CONFIRMED for framework_v1 | Organizer byte-level ordering requirements may add fields. | Deterministic permutation test. | G011 equivalent entity permutations. |
| C009 | Nested and partial overlaps | Apply the Framework §10.4 overlap matrix under named `framework_v1` policy; its unresolved default remains configurable and must emit a trace. | Framework §10.4; `ANNOTATION_GUIDE.md` SPAN-004/005. | ASSUMED (`framework_v1`) | Official scorer may accept, reject, or score overlap differently. | Matrix fixtures plus official scorer examples when available. | G012 nested same-type; G013 partial overlap; G014 same interval/different type. |
| C010 | Wrong-type behavior | The possibility of a wrong-type double penalty is unresolved. | Framework §3.1; playbook Task 0.2 | UNKNOWN | Decoder utility and type thresholds can be materially wrong. | Score right-span/wrong-type prediction using official scorer. | G014 right span, wrong type. |
| C011 | Allowed entity types | Allowed types are `TRIỆU_CHỨNG`, `TÊN_XÉT_NGHIỆM`, `KẾT_QUẢ_XÉT_NGHIỆM`, `CHẨN_ĐOÁN`, and `THUỐC`. | BTC-provided Framework §1.3 | CONFIRMED | Rejecting a valid type or emitting an invalid one. | Schema validator and one fixture per type. | G015 one valid entity of each type; G016 unsupported type rejection. |
| C012 | Assertion labels and applicability | Labels are `isNegated`, `isHistorical`, and `isFamily`; assertions are multi-label. Applicability by entity type and exact combinations remain unknown. | BTC-provided Framework §1.4; `ANNOTATION_GUIDE.md` ASSERT-001–006 | CONFIRMED labels/multi-label; UNKNOWN applicability | Invalid fields or incorrect assertion Jaccard. | BTC schema or examples with empty, single, and multi-label assertions. | G017 assertion presence; G018 empty list; G019 multi-label. |
| C013 | Candidate applicability and terminology | Project mapping is diagnosis→ICD and medication→RxNorm. The frozen baseline uses WHO ICD-10 2019 (including COVID-19 updates) and NLM RxNorm Current Prescribable Content 2026-07-06; only the manifest-declared code levels and TTYs are allowed. | Framework §1.3/§3.1 and §14; user-authorized external baseline in `terminology_manifest.yaml` | CONFIRMED for project baseline | The external baseline can differ from an unavailable organizer snapshot. | Verify archive checksums offline and validate every candidate against canonical tables. | G020 type-specific candidates; G021 invalid snapshot code. |
| C014 | Candidate list multiplicity, ordering, and duplicates | Candidate multiplicity, order significance, and duplicate handling are unknown. Internal output must be deterministic and duplicate-free only after BTC confirms equivalence. | Framework §3.1 and §14.7; no official scorer | UNKNOWN | Candidate Jaccard can change substantially. | Official scorer cases for one, multiple, reordered, and duplicate codes. | G022 candidate exact/missing/extra/reordered/duplicate. |
| C015 | Missing versus empty `assertions` / `candidates` | Field presence requirements are unknown for every type. Do not serialize a fixed policy as competition behavior. | Framework §3.1 and §18.1 defer to task contract | UNKNOWN | Schema rejection or score mismatch. | BTC JSON schema and official zero-field samples. | G018 empty/omitted assertions; G023 empty/omitted candidates. |
| C016 | Duplicate output objects | Remove exact duplicate output objects; never merge distinct positions by surface text alone. | Framework §17.1 and §18.1; `AGENTS.md` decision trace invariant. | CONFIRMED for framework_v1 | Official duplicate scoring remains unknown. | Exact-duplicate and repeated-position fixtures. | G010 exact duplicate and G024 same text/different positions. |
| C017 | Empty sample behavior | The expected JSON shape, file emission, and score behavior for zero entities are unknown. | Framework §3.2 lists zero-entity sample as required test; no official artifact | UNKNOWN | Missing output file or wrong empty serialization. | Official empty sample and scorer. | G025 empty source / zero entity output. |
| C018 | Invalid JSON and per-sample failures | Submission/parser behavior is unknown. Internally a failed sample must not stop the batch and must be reported safely. | `AGENTS.md` architectural invariants; Framework §25.3 | CONFIRMED internally; UNKNOWN for organizer handling | Batch loss or malformed submission handling mismatch. | Validator tests plus BTC submission rules. | G026 malformed JSON and G027 one bad sample in batch. |
| C019 | JSON top-level and allowed keys | Use a JSON array with enum, bounds, raw-slice, finite-number, and no-duplicate validation under `framework_v1`; per-type required/optional fields remain configurable. | Framework §1.2 and §18.1. | CONFIRMED for framework_v1 validation; ASSUMED for unspecified fields | Official schema can reject a framework-valid object. | Framework validator tests and official JSON schema when available. | G028 top-level/object-key schema fixture. |
| C020 | Output directory and zip structure | Framework proposes `output/<sample>.json` directly inside the zip; official naming/count rules are absent. | Framework §18.4/§18.5 | ASSUMED | Packaging rejection despite valid entities. | BTC packaging instructions and a reference zip. | G029 zip tree, filename, count, and reopen test. |
| C021 | Medication span assembly | A `THUỐC` proposal begins at an ingredient/brand alias and includes contiguous strength, unit/range, form, route, frequency, duration, PRN, release modifier, and combination components. Include internal component punctuation; exclude terminal punctuation, list markers, and treatment indications. | BTC-provided Framework §1.2, §8.1, §13.1; `ANNOTATION_GUIDE.md` MED-001–005 | CONFIRMED for project implementation | Boundary mismatch can reduce text score; scorer treatment remains unknown. | Unit fixtures for positive, negative, punctuation, list, and combination cases. | G030 framework output example; G031 `clonazepam 0.5 mg po qam:prn`; G032 combination; G033 dosage-only negative. |

## 3. Current implementation boundaries

1. Internal validation may enforce C001 and deterministic behavior without
   claiming that those choices reproduce the official scorer.
2. The Raw Loader's BOM default (`strip`) must remain configurable until C004
   is confirmed.
3. All framework_v1 position fixtures use C002/C003. Annotation/type/assertion
   policy provenance must still be recorded before any fixture is promoted.
4. Do not create an official-scorer clone, threshold tuning result, submission
   validator profile, or medication/lab boundary rule that treats an
   `ASSUMED`/`UNKNOWN` row as BTC-confirmed.

## 3.1 Explicit `framework_v1` configurable assumptions

The following are deliberately configuration values, not claims about an
unavailable organizer scorer: prediction-to-gold alignment (C006), wrong-type
penalty (C010), assertion/candidate aggregation and empty-set behavior
(C012/C014), field omission policy (C015), empty-sample behavior (C017),
organizer invalid-input handling (C018), schema details not stated by the
framework (C019), and output package layout (C020). Terminology variant,
release, TTY/granularity, checksums, licenses, and candidate eligibility remain
blocked by C013/C014 until organizer material is supplied.

## 4. Golden-test plan

The G001–G029 cases above are planned tests, not official golds. Their expected
competition outputs remain blocked until BTC material is received. Each case
must record:

- exact raw bytes and decoded raw text;
- expected entity JSON or expected rejection;
- source/BTC reference;
- scorer result when an official scorer is available; and
- the contract IDs it verifies.

When official artifacts arrive, implement the cases first in
`tests/golden/`, then update the associated table rows from `UNKNOWN` or
`ASSUMED` to `CONFIRMED` with the precise evidence reference.

## 5. Open questions for BTC

1. Provide the competition statement, official JSON schema, public examples,
   canonical raw input files, expected outputs, and official scorer or its
   scoring specification.
2. Confirm C002–C005: encoding, BOM treatment, newline treatment, indexing
   unit, zero/one indexing, and endpoint convention.
3. Confirm C006–C010 and C014–C018: entity alignment, wrong-type handling,
   duplicate/repeated/nested/overlap handling, Jaccard/WER arithmetic, empty
   sets, and field omission semantics.
4. Confirm C011–C013: allowed entity and assertion enums, type-specific field
   applicability, multi-label behavior, ICD variant/release, RxNorm
   release/TTY/granularity, and candidate eligibility.
5. Confirm C019–C020: JSON keys, top-level shape, filenames, sample count,
   output directory, and zip layout.
6. Confirm laboratory span boundaries, and externally validate the
   framework-derived medication policy before treating it as scorer gold.

## 6. Proposed verification sequence

1. Archive BTC artifacts with source URL or delivered-file checksum.
2. Recompute raw-text offsets from canonical bytes for G002–G007.
3. Implement a configurable local scorer only for explicitly identified
   alternatives, then select a mode only when it matches every official case.
4. Convert each affected contract row to `CONFIRMED` only after the matching
   golden test passes against organizer material.
5. Freeze a new contract version and only then permit gold annotation,
   threshold tuning, or submission packaging based on those decisions.

## 7. Change log

### 1.0.0-framework_v1 — 2026-07-16

- Froze raw Python Unicode-string indexing (C002) and half-open positions
  (C003) from the user-authorized Framework §1.2 output example.
- Promoted framework-specified newline indexing, deterministic ordering,
  duplicate handling, and validation behavior to framework_v1 decisions.
- Isolated scorer, terminology, and framework-unspecified schema behavior as
  named configurable assumptions rather than official-scorer claims.

### 0.3.0 — 2026-07-16

- Recorded the BTC-provided framework/playbook as binding project material.
- Promoted framework-specified entity, assertion, and diagnosis/medication
  candidate mappings to `CONFIRMED` at project level.
- Added C021 and linked it to the frozen framework-derived medication policy
  in `ANNOTATION_GUIDE.md`.

### 0.3.1 — 2026-07-17

- Froze the user-authorized external terminology baseline in
  `terminology_manifest.yaml`: WHO ICD-10 2019 and NLM RxNorm Current
  Prescribable Content 2026-07-06.
- Recorded the baseline limitation: it is not an organizer-provided snapshot.

### 0.2.0 — 2026-07-16

- Replaced blank fields with a testable decision table (C001–C020).
- Recorded the absence of official competition/scorer artifacts in the
  workspace.
- Marked framework-derived behavior as `ASSUMED`, not `CONFIRMED`.
- Added planned golden IDs, open questions, and a verification sequence.

### 0.1 — prior draft

- Initial blank contract template and BTC question list.
