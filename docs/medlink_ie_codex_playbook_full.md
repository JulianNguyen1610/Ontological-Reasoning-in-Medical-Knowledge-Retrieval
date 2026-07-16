# MedLink-IE — Codex Implementation Playbook

## Mục tiêu

Tài liệu này chuyển `MedLink-IE v2.0 — Implementation-ready specification` thành một kế hoạch vibe coding có kiểm soát. Mỗi task đều có:

- mục tiêu;
- phạm vi code;
- trình tự thực hiện;
- acceptance criteria;
- prompt có thể dán trực tiếp cho Codex;
- exit gate trước khi chuyển task tiếp theo.

Nguyên tắc xuyên suốt:

```text
Spec → Tests → Minimal implementation → Verification → Hostile review → Commit
```

Không giao cho Codex một yêu cầu kiểu “triển khai toàn bộ dự án”. Mỗi branch chỉ giải quyết một task và một concern rõ ràng.

---

# A. Cách vận hành Codex cho mọi task

## A.1 Master preamble

Dán phần sau ở đầu mọi prompt task:

```text
You are the implementation agent for the MedLink-IE project.

Before making changes, read in this order:
1. AGENTS.md
2. specs/TASK_CONTRACT.md
3. specs/ANNOTATION_GUIDE.md
4. specs/terminology_manifest.yaml when terminology is relevant
5. docs/MedLink-IE_v2_Framework.md
6. existing tests for the target module
7. the current implementation and public interfaces

Source-of-truth priority:
1. TASK_CONTRACT.md
2. ANNOTATION_GUIDE.md
3. terminology_manifest.yaml
4. framework document
5. tests
6. current code

Non-negotiable invariants:
- Raw source text and raw bytes are immutable.
- Final position is computed by deterministic code, never by an LLM.
- Every final entity must satisfy text == raw_text[start:end].
- Grounding happens before type and assertion decisions.
- ICD/RxNorm candidates come only from the frozen terminology snapshot.
- Negated, historical, or family mentions may still require concept linking.
- Inference is offline, deterministic, self-hosted, and uses no LLM above 9B.
- No silent fallback, broad exception swallowing, or hidden network access.
- Every keep/drop/link decision must be traceable.
- Do not change unrelated modules to make tests pass.

Workflow:
1. Inspect the repository and relevant specifications.
2. Report ambiguities before editing.
3. Propose files to change, design, edge cases, and tests.
4. Write or update tests first.
5. Implement the smallest correct change.
6. Run formatter, linter, type checker, targeted tests, then the full suite when practical.
7. Review the diff for contract violations and unrelated changes.
8. End with: files changed, commands run, results, assumptions, and remaining risks.

Do not claim completion while an acceptance criterion is unmet.
```

## A.2 Hostile review prompt

Chạy sau mỗi task, tốt nhất trong một lượt Codex mới:

```text
Review the current task diff as a hostile senior engineer. Do not modify code yet.

Check:
- specification violations;
- hidden assumptions;
- raw-text or offset corruption;
- Unicode and newline errors;
- nondeterminism;
- silent fallback;
- hard-coded thresholds or medical codes;
- privacy leaks in logs or exceptions;
- data leakage;
- optional-field/schema mismatches;
- tests that pass without proving the required behavior;
- unrelated architecture or dependencies.

Report findings as BLOCKER, HIGH, MEDIUM, LOW. For each finding include:
- exact file and line;
- violated requirement;
- concrete failure example;
- regression test required.

If no issue is found, cite the exact tests and code paths proving every critical invariant.
```

## A.3 Fix prompt

```text
Fix only the confirmed BLOCKER and HIGH findings.

For each fix:
1. Add a regression test that fails before the fix.
2. Make the smallest production change.
3. Do not redesign unrelated public interfaces.
4. Run all relevant checks.
5. Map every finding to its test and code fix.

Do not address speculative findings without explicit justification.
```

## A.4 Git rule

- Một task = một branch.
- Commit test trước nếu workflow cho phép.
- Không dùng commit “implement whole pipeline”.
- Merge khi exit gate của task đạt.

---

# Phase 0 — Contracts, scorer và project control

## Task 0.1 — Repository skeleton, AGENTS.md và CI

### Mục tiêu

Tạo cấu trúc repository, coding rules và CI tối thiểu trước khi viết logic y khoa.

### Cách thực hiện

1. Kiểm tra Python version và package manager.
2. Tạo package `src/medlink_ie`.
3. Tạo thư mục `specs`, `configs`, `tests`, `scripts`, `data`, `artifacts`, `outputs`.
4. Tạo `AGENTS.md` với invariants.
5. Cấu hình Ruff, mypy và pytest trong `pyproject.toml`.
6. Tạo Makefile hoặc task runner chuẩn.
7. Tạo CI chạy format check, lint, typecheck, unit tests.
8. Không thêm framework ML ở task này.

### Acceptance criteria

- `pip install -e ".[dev]"` chạy được.
- Import `medlink_ie` thành công.
- `make lint`, `make typecheck`, `make test` chạy thành công.
- CI dùng đúng các command local.
- Không có business logic placeholder trong production path.

### Prompt Codex

```text
[Use the master preamble]

Task: Create the initial MedLink-IE repository skeleton and development control files.

In scope:
- pyproject.toml
- Makefile
- AGENTS.md
- src/medlink_ie/__init__.py
- empty package directories only when needed
- tests/test_import.py
- CI workflow
- .gitignore and .env.example

Required repository areas:
- docs/
- specs/
- configs/
- src/medlink_ie/
- tests/unit, tests/golden, tests/integration, tests/fixtures
- scripts/
- data/raw, data/gold, data/synthetic, data/terminology
- artifacts/
- outputs/

Requirements:
- Python 3.11 or the version already fixed by the project.
- src-layout packaging.
- Ruff for formatting and linting.
- mypy for type checking.
- pytest for tests.
- No ML, web, database, or orchestration dependencies yet.
- AGENTS.md must contain the project invariants from the framework.
- CI commands must be identical to documented local commands.
- Add a smoke import test.

First inspect the existing repository. Do not overwrite useful files. Propose a minimal compatible structure, write the import test, then create the configuration.

Acceptance:
- editable install succeeds;
- import test passes;
- formatter/linter/type checker/test commands work;
- no unrelated dependency is introduced.
```

### Exit gate

Một máy sạch có thể clone, cài dev dependencies và chạy test rỗng thành công.

---

## Task 0.2 — TASK_CONTRACT.md

### Mục tiêu

Khóa các quy tắc chấm và output; phân biệt rõ confirmed, assumed và unknown.

### Cách thực hiện

1. Trích mọi quy tắc từ đề bài.
2. Lập bảng: vấn đề, quyết định, bằng chứng, trạng thái, test.
3. Khóa các điểm: position convention, Unicode indexing, entity matching, ordering, optional fields, duplicates, overlap, candidate multiplicity.
4. Với unknown, tạo config mode hoặc câu hỏi cần xác minh; không tự bịa.
5. Tạo change log/version cho contract.

### Acceptance criteria

- Không có quy tắc quan trọng chỉ tồn tại trong chat.
- Mỗi assumption có nhãn rõ.
- Mỗi rule có ít nhất một test dự kiến.
- Contract được tham chiếu bởi scorer và validator.

### Prompt Codex

```text
[Use the master preamble]

Task: Review and complete specs/TASK_CONTRACT.md. Do not implement production code.

Read the competition statement, official examples, framework, and any existing scorer notes.

Create a decision table with columns:
- contract item;
- current decision;
- evidence/source;
- status: CONFIRMED, ASSUMED, UNKNOWN;
- risk if wrong;
- verification method;
- required golden test.

Cover at minimum:
- character indexing and start/end convention;
- BOM and newline effects on offsets;
- Unicode code point versus byte indexing;
- entity matching policy;
- repeated identical mentions;
- ordering requirements;
- overlapping or nested spans;
- wrong-type double penalty;
- missing versus empty optional fields;
- allowed entity types and assertion labels;
- which types may contain assertions and candidates;
- candidate list ordering and duplicates;
- empty sample behavior;
- invalid JSON/sample failure behavior;
- output folder and zip structure.

Do not silently resolve unknown behavior. Add an explicit `Open questions` section and a proposed verification plan.

Acceptance:
- every rule is testable;
- no unsupported claim is marked CONFIRMED;
- the document has a version and change log.
```

### Exit gate

Team review và ký duyệt Task Contract v1.0.

---

## Task 0.3 — Official scorer clone và golden tests

### Mục tiêu

Tạo scorer local là nguồn tối ưu duy nhất cho threshold và ablation.

### Cách thực hiện

1. Viết golden tests trước.
2. Tách entity alignment khỏi metric calculation.
3. Triển khai text, assertions và candidates score.
4. Hỗ trợ explicit mode cho behavior chưa xác nhận.
5. Tạo score breakdown per sample/entity.
6. Không tích hợp model code.

### Acceptance criteria

- Golden official example đạt điểm kỳ vọng.
- Test extra/missing/wrong type/repeated text/empty fields pass.
- Scorer deterministic.
- Có diagnostic breakdown, không chỉ final float.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the local clone of the official competition scorer.

In scope:
- src/medlink_ie/evaluation/scorer.py
- src/medlink_ie/evaluation/alignment.py
- domain result types needed by the scorer
- tests/golden/test_official_scorer.py
- tests/fixtures/scorer/

Out of scope:
- extraction, linking, model, threshold tuning, CLI inference.

Tests first. Add golden cases for:
1. perfect prediction;
2. empty ground truth and prediction;
3. extra entity;
4. missing entity;
5. correct text/position but wrong type;
6. repeated identical text at distinct positions;
7. assertion exact match, missing label, extra label;
8. candidate exact match, missing code, extra code;
9. missing optional field versus empty list according to contract;
10. deterministic ordering;
11. the official sample when available.

Design requirements:
- alignment policy is isolated and documented;
- metric functions are pure;
- return final score and a structured breakdown;
- unknown contract behaviors use explicit configuration, never hidden assumptions;
- no model dependencies;
- no mutation of inputs.

Run golden tests and show the expected arithmetic for at least one non-trivial case.
```

### Exit gate

Scorer golden suite được team review; mọi experiment sau dùng đúng scorer này.

---

## Task 0.4 — Annotation guide và adjudication matrix

### Mục tiêu

Đảm bảo người gán nhãn, synthetic generator và model dùng cùng một định nghĩa.

### Cách thực hiện

1. Viết quy tắc span boundary cho từng type.
2. Viết type decision tree.
3. Viết assertion scope/multi-label policy.
4. Tạo 100 adversarial examples.
5. Gắn `NEEDS_ADJUDICATION` cho trường hợp chưa khóa.
6. Tạo form adjudication và versioning.

### Acceptance criteria

- Có ví dụ positive/negative/boundary cho từng rule.
- Có policy thuốc gồm strength/form/route/frequency.
- Có policy lab name/result.
- Có policy symptom vs diagnosis.
- Có policy nested/overlap/repeated mentions.

### Prompt Codex

```text
[Use the master preamble]

Task: Expand specs/ANNOTATION_GUIDE.md and create an adjudication test matrix. Do not implement model code.

Deliver:
- annotation rule IDs;
- decision trees for entity type;
- span boundary rules;
- assertion rules and scope examples;
- overlap/nesting/repeated-mention policy;
- medication and laboratory-specific rules;
- 100 adversarial Vietnamese clinical examples in a machine-readable fixture;
- an adjudication template.

Every example must include:
- raw text;
- expected entities with exact spans;
- rationale;
- rule IDs invoked;
- ambiguity status;
- reviewer decision field.

Coverage:
- symptom versus diagnosis;
- test name versus test result;
- medication with strength/form/route/frequency/PRN;
- historical medication lists;
- negation with contrast clauses;
- family history and negated family history;
- multiple simultaneous assertions;
- repeated text with different local contexts;
- qualitative and quantitative lab results;
- punctuation, abbreviations, typos, mixed Vietnamese/English.

Do not invent policy for unresolved cases. Mark them NEEDS_ADJUDICATION.
```

### Exit gate

Annotation Guide v1.0 được adjudicate và đóng băng cho gold dev đầu tiên.

---

## Task 0.5 — Terminology và provenance manifests

### Mục tiêu

Khóa nguồn ICD/RxNorm, license, version, checksum và artifact provenance.

### Cách thực hiện

1. Thiết kế manifest schema.
2. Ghi source, variant, version, release date, checksum, license.
3. Khóa allowed term types/granularity.
4. Ghi active/inactive handling.
5. Tạo model/data artifact manifest chung.
6. Validator phải fail khi checksum sai.

### Acceptance criteria

- Không có terminology “latest” không version.
- Mọi index dẫn ngược về snapshot.
- Mọi model artifact có config/data/code version.
- Manifest không chứa secret.

### Prompt Codex

```text
[Use the master preamble]

Task: Define and validate frozen terminology and artifact provenance manifests.

In scope:
- specs/terminology_manifest.yaml
- specs/artifact_manifest.schema.json or typed equivalent
- src/medlink_ie/provenance/manifest.py
- tests/unit/provenance/

Requirements:
- ICD source, variant, version, release date, path, SHA-256, license, active-status policy;
- RxNorm source, release, allowed TTY/granularity, path, SHA-256, license, obsolete handling;
- alias/enrichment source declarations;
- model artifact fields: model name, parameter count, checksum, training config, dataset versions, code commit, seed;
- synthetic-data provenance fields;
- validation rejects missing version, missing checksum, mismatched checksum, unsupported terminology variant, and model >9B when parameter count is declared;
- no network download in validator;
- no secrets in manifest.

Create typed loaders and unit tests. Do not build terminology indices yet.
```

### Exit gate

Terminology snapshot và provenance contract được khóa trước khi index/train.

---

# Phase 1 — Text integrity và core domain

## Task 1.1 — Core domain models

### Mục tiêu

Tạo data contracts bất biến cho toàn pipeline.

### Cách thực hiện

Tạo tối thiểu:

- `SourceDocument`;
- `TextView`;
- `SpanProposal`;
- `GroundedSpan`;
- `EntityHypothesis`;
- `FinalEntity`;
- `DecisionTrace`;
- enums type/assertion/source/match method.

Validation nằm ở boundary; không nhét business logic model vào dataclass.

### Acceptance criteria

- Invalid interval/confidence/type bị reject.
- FinalEntity không thể chứa text lệch raw span khi validate cùng document.
- Objects phù hợp serialization.
- Không phụ thuộc ML framework.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the core immutable domain contracts described in framework section 5.

Create or complete:
- SourceDocument
- TextView
- SpanProposal
- GroundedSpan
- EntityHypothesis
- FinalEntity
- DecisionTrace
- EntityType, AssertionLabel, ProposalSource, GroundingMethod enums

Requirements:
- Python 3.11 type hints;
- frozen/slots dataclasses where appropriate;
- confidence values validated in [0,1];
- intervals validated for non-negative ordered boundaries;
- no ML-library dependency;
- no file I/O inside domain objects;
- serialization methods must be deterministic;
- FinalEntity semantic validation accepts a SourceDocument and verifies text == raw_text[start:end];
- optional fields follow TASK_CONTRACT.

Write unit tests for valid construction, every invalid boundary, invalid confidence, unsupported labels, deterministic serialization, and semantic span mismatch.
```

### Exit gate

Các module sau chỉ trao đổi qua domain contracts này.

---

## Task 1.2 — Raw loader

### Mục tiêu

Đọc nguyên bytes và decode tường minh, không làm thay đổi bất kỳ ký tự nào.

### Cách thực hiện

1. Binary read.
2. Explicit UTF-8/error/BOM policy.
3. Bảo toàn CRLF/LF/whitespace/NFC/NFD/emoji.
4. Raw bytes immutable.
5. Error không log clinical text.

### Acceptance criteria

- UTF-8 BOM, CRLF, LF, mixed newline, NFC, NFD, spaces, leading/trailing, emoji, empty, invalid UTF-8 đều có test.
- Không dùng `Path.read_text`, text mode, strip/replace/normalize.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement Task 1.2 Raw Loader.

Critical invariant:
- SourceDocument.raw_bytes is byte-for-byte identical to the file.
- raw_text is exactly the configured decode result.

Allowed production scope:
- src/medlink_ie/io/raw_loader.py
- source-document fields only if required
- typed loader exceptions
- tests/unit/io/test_raw_loader.py
- binary fixtures

Required behavior:
- read with binary mode or Path.read_bytes;
- explicit encoding, default UTF-8 strict;
- explicit UTF-8 BOM policy: preserve/strip/reject according to config and Task Contract;
- no encoding guessing;
- no newline translation;
- no Unicode normalization;
- no whitespace modification;
- no full clinical text in logs/exceptions;
- empty file is valid unless the contract says otherwise;
- invalid UTF-8 under strict mode raises a typed error with safe metadata.

Forbidden:
- Path.read_text
- open(..., "r")
- strip/lstrip/rstrip
- replace/splitlines-and-join
- unicodedata.normalize
- implicit utf-8-sig behavior
- fallback to Latin-1
- except Exception returning an empty document

Tests first. Required cases:
1. UTF-8 BOM under every supported policy;
2. CRLF preserved;
3. LF preserved;
4. mixed CRLF/LF/CR preserved;
5. NFC unchanged;
6. NFD unchanged;
7. multiple spaces;
8. leading and trailing spaces;
9. trailing newline and no trailing newline;
10. tab, blank lines, and embedded null;
11. emoji/non-BMP round-trip;
12. empty file;
13. invalid UTF-8 strict failure;
14. deterministic repeated load;
15. load_path proves binary identity.

Do not implement normalization views in this task.
```

### Exit gate

Raw loader tests chứng minh text integrity trên Linux/Windows newline fixtures.

---

## Task 1.3 — Text views và boundary maps

### Mục tiêu

Tạo các view phục vụ retrieval nhưng map start/end chính xác về raw text.

### Cách thực hiện

1. Raw view identity.
2. NFC/search/lowercase/accentless/whitespace-normalized views.
3. Boundary map có `len(view)+1` entries.
4. Mỗi transform thực hiện theo character segments, không đoán offset sau cùng.
5. Fuzz/property test mapping monotonic.

### Acceptance criteria

- Start/end map chính xác khi transform co/giãn.
- Map monotonic và trong range.
- Không view nào được dùng làm final raw position.
- NFD→NFC, whitespace collapse, accent removal có test.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement lossless TextView transformations with boundary maps.

In scope:
- src/medlink_ie/normalization/text_views.py
- src/medlink_ie/normalization/boundary_map.py
- tests/unit/normalization/

Required views:
- raw identity view;
- NFC search view;
- lowercase retrieval view;
- accentless retrieval view;
- whitespace-normalized retrieval view.

Boundary-map contract:
- mapping represents boundaries, not only characters;
- map length equals len(view_text) + 1;
- every normalized start/end maps to raw start/end;
- values are monotonic and within [0, len(raw_text)];
- transformations may collapse or expand code points;
- raw SourceDocument is never mutated;
- only raw boundaries may appear in final output.

Tests:
- identity mapping;
- NFC/NFD examples;
- combining marks;
- Vietnamese accents;
- lowercase characters that may change representation;
- multiple whitespace collapsed into one while mapping the full raw range;
- CRLF and tabs;
- emoji/non-BMP;
- empty text;
- mapping arbitrary extracted view spans back to the expected raw slice;
- property/fuzz tests for monotonicity and range when the project already uses Hypothesis.

Do not implement grounding or entity logic here.
```

### Exit gate

Tất cả view transform có golden offset tests và không phá raw text.

---

## Task 1.4 — Structural analyzer

### Mục tiêu

Tạo section/list/sentence/clause spans trên raw coordinates để assertion và extraction dùng lại.

### Cách thực hiện

1. Xác định section headings theo rule configurable.
2. List item detector cho số thứ tự, bullet, dòng thuốc.
3. Sentence segmentation bảo toàn offsets.
4. Clause boundaries theo punctuation/conjunction.
5. Trả cấu trúc cây/quan hệ, không sửa text.

### Acceptance criteria

- Mọi structural span thỏa raw slice invariant.
- Danh sách thuốc nhiều dòng được nhận diện.
- Contrast clause “không sốt nhưng ho” tách đúng.
- Không phụ thuộc model.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the deterministic document structural analyzer.

Create typed outputs for:
- sections;
- list blocks and list items;
- sentences;
- clauses;
- parent-child relationships.

Requirements:
- all boundaries are raw-text boundaries;
- no input mutation;
- rules are configurable and identified by rule IDs;
- section headings may include Vietnamese and common English clinical headings;
- list detection supports numbered items, bullets, newline-separated medication entries;
- sentence segmentation must not split decimal numbers, common medical abbreviations, or dosage expressions incorrectly where covered by rules;
- clause segmentation recognizes contrast and coordination cues needed for assertion scope;
- each structural unit validates raw_text[start:end].

Tests:
- medication history list;
- lab report lines;
- numbered and bullet lists;
- abbreviations and decimals;
- `Không sốt nhưng ho nhiều`;
- multiline text with CRLF;
- empty and one-line documents;
- deterministic ordering.

Do not implement assertions in this task.
```

### Exit gate

Structure analyzer cung cấp raw intervals ổn định cho mọi downstream module.

---

# Phase 2 — Deterministic end-to-end baseline

## Task 2.1 — Proposal protocol và decision trace

### Mục tiêu

Chuẩn hóa interface cho mọi extractor và log bằng chứng.

### Cách thực hiện

1. Tạo `SpanProposer` protocol.
2. Tạo source trust/config.
3. Mỗi proposal có raw hoặc view coordinates, source, rule/model ID, score, evidence.
4. Không quyết định final entity ở proposer.

### Acceptance criteria

- Mock proposer dùng được trong integration tests.
- Proposal serialization deterministic.
- DecisionTrace không chứa full note ngoài span cần thiết.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the span-proposal plugin contract and decision tracing primitives.

Create:
- SpanProposer protocol;
- ProposalContext;
- source trust configuration;
- proposal evidence metadata;
- deterministic proposal IDs;
- DecisionTrace event API.

Requirements:
- proposer only proposes; it does not ground, classify final type, link, or apply global thresholds;
- support deterministic rule proposers and future model proposers;
- proposal coordinates explicitly state which TextView they refer to;
- no global mutable registry;
- traces record source, rule/model version, score, evidence, and reason;
- privacy-safe logs;
- mock proposer for integration tests.

Write protocol and serialization tests. Do not implement medical rules yet.
```

### Exit gate

Tất cả proposer sau dùng cùng protocol.

---

## Task 2.2 — Medication proposer

### Mục tiêu

High-precision rule proposer cho tên thuốc kèm strength/form/route/frequency.

### Cách thực hiện

1. Lexicon ingredient/brand lấy từ terminology snapshot hoặc fixture.
2. Regex dosage/strength/form/route/frequency.
3. Span assembly theo annotation guide.
4. Rule IDs và evidence.
5. Không link code ở đây.

### Acceptance criteria

- Đúng span examples chính thức.
- Không nhận nhầm đơn vị/lab value thành thuốc.
- Hỗ trợ combination drug, PRN, XL/SR.
- Có hard negatives.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement a precision-first deterministic medication span proposer.

Inputs:
- SourceDocument;
- DocumentStructure;
- a frozen medication alias lexicon interface.

Output:
- SpanProposal objects only.

Required rule families:
- ingredient/brand alias match;
- strength values and ranges;
- dose form;
- route;
- frequency and PRN;
- release modifiers such as XL/SR/ER;
- combination medications;
- list-item context.

Span assembly must follow ANNOTATION_GUIDE exactly. Do not infer RxNorm codes. Do not include treatment indications after medication spans unless the guide requires it.

Tests:
- official medication list examples;
- `clonazepam 0.5 mg po qam:prn`;
- same ingredient with different strengths;
- ingredient only;
- brand plus generic;
- strength without medication as a negative;
- lab unit values as negatives;
- punctuation and newline boundaries;
- mixed Vietnamese/English.

Every proposal must include rule ID, matched alias, component spans, and confidence tier.
```

### Exit gate

Medication rule proposer đạt precision tốt trên challenge fixture.

---

## Task 2.3 — Lab proposer

### Mục tiêu

Trích `TÊN_XÉT_NGHIỆM` và `KẾT_QUẢ_XÉT_NGHIỆM` với quan hệ nội bộ.

### Cách thực hiện

1. Test-name lexicon/pattern.
2. Numeric/range/inequality/unit result patterns.
3. Qualitative result patterns.
4. Pair test-result trong line/clause.
5. Không xuất relation trong final JSON, chỉ giữ nội bộ.

### Acceptance criteria

- Hỗ trợ decimal dot/comma, range, `<`, `>`, H/L, âm/dương tính.
- Không gộp test name và result thành một span nếu guide tách.
- Pairing không nối nhầm giữa các dòng.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement deterministic laboratory test-name and result proposers plus internal pairing evidence.

Required result patterns:
- integers and decimals using dot or comma;
- ranges;
- inequalities;
- units;
- H/L flags;
- `tăng`, `giảm`, `cao`, `thấp`;
- `dương tính`, `âm tính`, `không phát hiện`;
- reference ranges when the annotation guide includes or excludes them.

Requirements:
- emit separate SpanProposal types for test name and test result;
- preserve raw spans;
- build an internal `has_result` relation based on same line/clause/list item and nearest compatible test;
- no final relation field is added to competition JSON;
- rule IDs and component evidence required.

Tests:
- single test and value;
- multiple tests on one line;
- multiple lines;
- qualitative result;
- result without explicit unit;
- unit without test as negative;
- medication dosage as a negative;
- ambiguous nearest-neighbor pairing.
```

### Exit gate

Lab proposer và pairing fixture pass.

---

## Task 2.4 — Symptom/diagnosis proposer

### Mục tiêu

Sinh candidate span recall vừa phải nhưng precision-first cho symptom và diagnosis.

### Cách thực hiện

1. Alias lexicon chung, chưa chốt type.
2. Trigger diagnosis: chẩn đoán, kết luận, mắc, bệnh.
3. Symptom contexts: than phiền, đau, ho, sốt...
4. Proposal có type distribution hoặc provisional type.
5. Tránh family/history cue gắn type sai.

### Acceptance criteria

- Hard negatives symptom vs diagnosis.
- Mention trong “loại trừ” vẫn được proposal nhưng assertion/type xử lý sau.
- Không dùng LLM.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement deterministic symptom/diagnosis concept proposals without making irreversible final type decisions.

Use:
- approved concept aliases;
- diagnosis triggers;
- symptom lexical patterns;
- structural context.

Output proposals should contain either:
- a provisional type distribution, or
- source-specific type evidence,
not a forced final type when ambiguous.

Requirements:
- follow annotation boundaries;
- keep assertion handling separate;
- do not drop negated/historical/family mentions;
- record trigger spans and local context IDs;
- avoid proposing headings or unrelated administrative phrases.

Tests:
- symptom versus diagnosis minimal pairs;
- `được chẩn đoán tăng huyết áp`;
- `đau ngực` in complaint context;
- disease mentioned in family history;
- disease in rule-out context;
- repeated mention with different context;
- abbreviation aliases;
- punctuation boundaries.
```

### Exit gate

Proposal recall/precision được đo riêng, chưa phụ thuộc final classifier.

---

## Task 2.5 — Exact grounding và repeated mention resolution

### Mục tiêu

Gắn mọi proposal vào raw interval trước typing/assertion.

### Cách thực hiện

1. Exact raw match.
2. Unicode-view constrained match qua boundary map.
3. Case-insensitive/token-aligned match.
4. Liệt kê mọi occurrence.
5. Chọn occurrence dựa predicted location, order, structure, unused/conflict context.
6. Fuzzy mặc định off.

### Acceptance criteria

- Mọi GroundedSpan thỏa raw slice invariant.
- Repeated mention không dùng global text identity.
- Ambiguous grounding có trace hoặc abstain.
- Fuzzy không tự bật.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement exact source grounding and repeated-mention disambiguation.

Matching cascade:
1. exact raw-character match;
2. exact match in an approved Unicode/search TextView mapped through boundary maps;
3. case-insensitive constrained match;
4. token-aligned match;
5. fuzzy match only behind a disabled-by-default feature flag.

For every proposal:
- enumerate all candidate occurrences;
- score using expected position, proposal order, section/list/sentence IDs, local context, and overlap constraints;
- return GroundedSpan with method, candidate occurrences, selected reason, and confidence;
- abstain when ambiguity is unresolved.

Tests:
- unique exact match;
- repeated `ho` occurrences;
- same drug ingredient with different strengths;
- NFC/NFD view grounding;
- case differences;
- punctuation and whitespace variations allowed by contract;
- overlap conflicts;
- no match;
- ambiguous equal matches;
- fuzzy disabled.

Critical assertion for every success:
`grounded.text == raw_text[start:end]`.
```

### Exit gate

Grounding golden tests pass, including repeated mentions.

---

## Task 2.6 — Span clustering, baseline type và assertion rules

### Mục tiêu

Hợp nhất proposals, chọn boundary và tạo baseline entity hypotheses.

### Cách thực hiện

1. Cluster exact/near-overlap proposals.
2. Feature source trust, support count, exactness, rule specificity.
3. Boundary resolution theo annotation guide.
4. Heuristic type classifier riêng.
5. Basic negation/history/family rules riêng, không keyword-only.
6. Threshold config theo type/source.

### Acceptance criteria

- Không union mù.
- Mọi reject có trace.
- Overlap policy deterministic.
- Assertion hard masks áp đúng type.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the deterministic baseline for span clustering, boundary resolution, heuristic type classification, and basic assertion rules.

Separate components:
- SpanClusterer
- BoundaryResolver
- HeuristicTypeClassifier
- BasicAssertionEngine

Fusion features:
- proposal source and trust tier;
- exact grounding method;
- number of independent supporting sources;
- rule specificity;
- boundary agreement;
- provisional type evidence;
- dictionary evidence.

Requirements:
- no blind union;
- deterministic overlap policy;
- thresholds in config, never hard-coded;
- type and assertion decisions occur on grounded spans and local structure;
- basic assertion rules must use cue plus scope, not keyword presence alone;
- family/historical/negated mentions are not removed from linking eligibility;
- lab types receive assertion hard masks according to contract;
- every decision emits a trace.

Tests must cover conflicting proposals, exact same span/different type, nested medication components, symptom versus diagnosis, list-level historical cue, negation with contrast, and family scope.
```

### Exit gate

Baseline hypotheses ổn định và traceable.

---

## Task 2.7 — Baseline orchestrator, schema validator và packaging

### Mục tiêu

Chạy một lệnh từ input directory đến output JSON/zip hợp lệ.

### Cách thực hiện

1. Orchestrator chỉ gọi modules.
2. Per-sample failure isolation.
3. Atomic write.
4. Schema + semantic validation.
5. Sort deterministic.
6. Package đúng folder/filename.
7. Pre-submit validator mở zip kiểm tra lại.

### Acceptance criteria

- End-to-end smoke test.
- Invalid entity không lọt ra output.
- Một sample lỗi không làm mất batch.
- Re-run cho output byte-identical nếu metadata ngoài output không đổi.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the deterministic baseline pipeline orchestration and submission validation.

Use only existing components. Do not add new medical rules.

Create:
- MedLinkPipeline.predict_document;
- batch predict_directory;
- JSON schema validator;
- semantic validator;
- deterministic sorter;
- atomic JSON writer;
- output.zip packager;
- pre-submit validator;
- batch report.

Requirements:
- process input filenames in deterministic numeric order;
- isolate sample failures and record safe errors;
- final entities satisfy raw span, allowed type/assertion, candidate applicability, no duplicate output object, and contract ordering;
- optional fields follow Task Contract;
- never partially overwrite a valid output;
- package exact required directory structure;
- validator reopens zip and checks filenames, JSON, sample count, and semantics;
- output contains no debug confidence or trace fields;
- decision traces remain in separate artifacts.

Add an end-to-end fixture with at least three samples, including an empty result and a repeated mention.
```

### Exit gate

MVP baseline tạo submission hợp lệ bằng một command.

---

# Phase 3 — Gold data, evaluation và error loop

## Task 3.1 — Annotation data format và validation tooling

### Mục tiêu

Tạo gold format dùng exact raw offsets và validate trước adjudication.

### Cách thực hiện

1. Schema cho raw sample + annotations.
2. Validator text/raw position/type/assertion/candidate.
3. Import/export JSONL.
4. Diff giữa annotators.
5. Không tạo web app phức tạp nếu chưa cần.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the gold-annotation data format, validators, and annotator-diff tooling.

Create:
- typed GoldSample and GoldEntity models;
- JSONL reader/writer;
- validation against raw text and annotation guide constraints;
- duplicate/overlap checks;
- two-annotator comparison report;
- adjudication status fields.

Requirements:
- raw text or immutable source reference is preserved;
- every gold text equals raw_text[start:end];
- optional fields follow contract;
- comparison aligns primarily by position and type, not surface text alone;
- report boundary, type, assertion, and candidate disagreements separately;
- no automatic adjudication.

Tests include Unicode, repeated mentions, empty annotations, wrong offsets, and malformed records.
```

### Exit gate

Gold records không thể commit nếu validator fail.

---

## Task 3.2 — Gold dev, grouped split và challenge set

### Mục tiêu

Ngăn leakage và tạo tập kiểm thử lỗi khó.

### Cách thực hiện

1. Group theo scenario/template/concept/prompt parent.
2. Stratify tương đối theo type/assertion.
3. Challenge buckets riêng.
4. Lưu split manifest/checksum.
5. Không random row split.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement deterministic grouped dataset splitting and challenge-set construction.

Inputs contain metadata such as:
- scenario_id;
- template_family;
- seed_concept;
- generator_prompt_version;
- paraphrase_parent;
- specialty;
- annotation version.

Requirements:
- prevent group leakage across train/dev/test;
- deterministic seed;
- produce split manifests with checksums and statistics;
- detect duplicated or near-identical records across splits using safe fingerprints;
- create challenge buckets for type confusion, assertion scope, repeated mentions, drug strength/form, lab pairing, ICD level, RxNorm granularity, Unicode/offset, and output schema;
- do not silently rebalance by moving individual rows out of groups.

Add tests proving no group leakage and stable manifests.
```

### Exit gate

Dev/challenge split được đóng băng và versioned.

---

## Task 3.3 — Evaluation report, error taxonomy và experiment tracking

### Mục tiêu

Biết điểm mất ở module nào và tái lập mọi run.

### Cách thực hiện

1. Chạy official scorer clone.
2. Diagnostic metrics per type/module.
3. Error bucketing deterministic.
4. Run manifest config/data/model/code/seed.
5. Produce machine-readable + Markdown report.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the evaluation/reporting and experiment tracking layer.

Deliver:
- scorer integration;
- extraction metrics by type and boundary error;
- assertion metrics by label and scope error;
- linking recall@k, MRR, oracle candidate score, final Jaccard;
- system latency and failure counts;
- deterministic error taxonomy;
- run manifest containing config hashes, data manifests, model artifacts, terminology snapshot, code commit, seed, environment, and feature flags;
- JSON and Markdown reports.

Requirements:
- no LLM judge for primary metrics;
- every reported number traces to sample/entity IDs;
- predictions and gold are never mutated;
- reports avoid full clinical text unless explicitly enabled for a secure local debug artifact;
- compare two runs and report statistically relevant deltas and changed error buckets.
```

### Exit gate

Baseline report chỉ rõ top score-loss buckets.

---

# Phase 4 — Assertion system hoàn chỉnh

## Task 4.1 — Cue lexicon và scope engine

### Mục tiêu

Xác định cue, scope boundaries và entity-cue association.

### Cách thực hiện

1. Versioned cue lexicon.
2. Cue categories negation/history/family.
3. Scope based on clause/sentence/list/section.
4. Blockers/terminators/contrast conjunction.
5. Return evidence spans.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement a versioned assertion cue lexicon and deterministic scope engine.

Create:
- cue records with label, language, pattern, direction, allowed structure levels, terminators, blockers, rule ID;
- cue detector on raw text;
- scope boundary resolver using section/list/sentence/clause structure;
- entity-cue association scoring;
- AssertionDecision evidence including cue span, scope span, rule ID, and confidence tier.

Requirements:
- no keyword-only classification;
- contrast conjunctions terminate or redirect scope correctly;
- cues inside quoted/template text can be excluded when structural rules support it;
- multiple cues may apply to one entity;
- no entity is removed because of an assertion.

Tests: `không sốt nhưng ho`, `chưa ghi nhận`, `tiền sử`, `trước nhập viện`, family relations, multiple entities in a list, and cue terminators.
```

### Exit gate

Rule scope challenge set pass.

---

## Task 4.2 — Section/list propagation và multi-label assertions

### Mục tiêu

Xử lý cue ở heading hoặc đầu list áp dụng lên nhiều entities và exception cục bộ.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement section/list-level assertion propagation and multi-label composition.

Requirements:
- section or list cues may propagate to descendant entities;
- local cues can override or add labels according to the annotation guide;
- support simultaneous labels such as family + negated or historical + negated when allowed;
- propagation records the source structural unit and inheritance path;
- do not propagate across section/list boundaries;
- local exception handling is deterministic;
- duplicate labels are removed without losing evidence traces.

Tests:
- `Danh sách thuốc trước nhập viện` applied to all list medications;
- a local current-medication exception;
- family-history section with multiple diseases;
- negated family history;
- nested lists;
- heading without descendants;
- multiple assertions on one entity.
```

### Exit gate

Historical medication list và family section fixtures pass.

---

## Task 4.3 — Assertion classifier interface, hard masks và calibration

### Mục tiêu

Cho phép classifier học máy bổ sung rule engine nhưng tách score, calibration và threshold.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the assertion-classifier interface, rule/model fusion, hard masks, and calibration hooks.

Do not train a model unless a trained artifact already exists.

Create:
- AssertionClassifier protocol returning raw logits per label;
- deterministic mock classifier;
- calibrated probability wrapper;
- rule/model feature fusion interface;
- per-label threshold configuration;
- type-based hard masks;
- abstention behavior producing an empty assertion list when evidence is insufficient.

Requirements:
- labels are independent multi-label decisions;
- raw logits, calibrated probabilities, and threshold decisions remain separate;
- calibration artifacts are versioned;
- hard masks follow Task Contract;
- empty ground-truth risk is explicitly measured;
- every included or rejected label has a trace.

Tests cover model/rule disagreement, hard masks, missing calibration artifact, per-label thresholds, and deterministic mock inference.
```

### Exit gate

Per-label calibration và empty-assertion false positives được đo.

---

# Phase 5 — Terminology và entity linking

## Task 5.1 — Terminology loading và offline preparation

### Mục tiêu

Chuyển snapshot gốc thành canonical concept/alias tables có provenance.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement frozen terminology loading and offline canonical-table preparation.

Inputs are local files declared in terminology_manifest.yaml.

Create:
- ConceptRecord and AliasRecord;
- ICD and RxNorm adapter interfaces;
- active/inactive filtering;
- allowed granularity/TTY filtering;
- normalized alias fields for retrieval only;
- duplicate and conflicting alias reports;
- deterministic canonical tables;
- checksums and preparation manifest.

Requirements:
- no network;
- no hard-coded medical codes;
- original preferred terms and aliases are preserved;
- normalized aliases never replace original display values;
- all records trace to source row/version;
- fail on checksum mismatch or unsupported version.

Tests use small synthetic terminology fixtures including ambiguous aliases, obsolete concepts, duplicate rows, and multiple granularities.
```

### Exit gate

Canonical tables tái tạo byte-stable từ snapshot + config.

---

## Task 5.2 — Exact alias, BM25 và character n-gram retrieval

### Mục tiêu

Tạo high-recall lexical candidate pool.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement deterministic lexical terminology retrieval.

Components:
- exact alias index;
- accentless/case-normalized exact index;
- BM25 index;
- character n-gram index with configurable n range;
- retrieval evidence and stable result ordering.

Requirements:
- exact retrieval returns all matching concepts, not just the first;
- type/terminology filters are applied explicitly;
- inactive concepts excluded according to manifest;
- no candidate code generated outside canonical tables;
- index artifacts have checksums and config metadata;
- scores from different channels remain separate at this stage.

Tests:
- unique and ambiguous aliases;
- Vietnamese accents and accentless forms;
- punctuation and hyphen variants;
- common typo tolerance through n-grams;
- empty query;
- stable tie-breaking;
- duplicate aliases;
- wrong terminology/type filtering.
```

### Exit gate

Lexical retrieval recall@k được báo cáo trên gold mentions.

---

## Task 5.3 — Structured medication và lab parsers

### Mục tiêu

Biến raw mention thành slots dùng để filter/rerank, không thay đổi span.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement structured clinical mention parsers for medication and laboratory mentions.

Medication slots:
- ingredient/brand surface;
- strength value/unit/range;
- dose form;
- route;
- release modifier;
- frequency;
- PRN;
- combination components.

Laboratory slots:
- test name surface;
- numeric/qualitative result;
- comparator;
- unit;
- reference range;
- abnormal flag.

Requirements:
- parsers return spans and normalized slot values without mutating the original mention;
- missing slots remain unknown, never guessed;
- parser confidence/evidence recorded;
- structured slots are features, not final entity types or codes;
- same ingredient with different strengths remains distinct.

Tests include official drug examples, combination drugs, XL/SR, decimal comma, qualitative labs, ranges, missing units, and ambiguous tokens.
```

### Exit gate

Parser slots có unit tests và được dùng được trong candidate filtering.

---

## Task 5.4 — Dense retrieval và cross-encoder interfaces

### Mục tiêu

Tạo interfaces và artifact management trước khi chọn model cụ thể.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement dense-retriever and cross-encoder reranker interfaces with offline artifact loading.

Create:
- ConceptEncoder protocol;
- MentionEncoder protocol or shared bi-encoder protocol;
- vector index abstraction;
- CrossEncoderReranker protocol;
- batch APIs;
- deterministic mock implementations;
- artifact version/checksum validation;
- device and precision configuration.

Requirements:
- no model download at inference;
- no model-specific code leaks into pipeline orchestration;
- raw retrieval scores and reranker scores remain separate;
- support mention + local context and candidate metadata inputs;
- stable tie-breaking;
- safe out-of-memory/error handling without silently changing model;
- model parameter count checked against rules when applicable.

Do not select a final model or train in this task. Add interface and mock integration tests.
```

### Exit gate

Có thể thay dense/reranker model bằng config, không sửa pipeline.

---

## Task 5.5 — Candidate fusion, set selection và hard negatives

### Mục tiêu

Hợp nhất channels và chọn candidate set tối ưu expected Jaccard.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement candidate-channel fusion, structured compatibility features, candidate-set selection, and hard-negative generation.

Inputs may include:
- exact alias score;
- BM25 score;
- character n-gram score;
- dense score;
- reranker score;
- medication/lab structured compatibility;
- hierarchy metadata;
- source evidence.

Requirements:
- preserve per-channel scores;
- fusion weights loaded from config/artifact;
- structured filters reject impossible ingredient/strength/form combinations only when evidence is explicit;
- assertion labels do not suppress linking;
- candidate-set selector optimizes configured expected Jaccard utility, not fixed top-k;
- support abstaining with candidates=[] when confidence is insufficient;
- stable ordering and duplicate removal;
- generate ICD sibling/parent/child and RxNorm ingredient-strength-form hard negatives.

Tests cover unique exact match, ambiguous alias, missing strength, conflicting strength, combination drug, extra-code Jaccard penalty, and abstention.
```

### Exit gate

Final candidate set logic có oracle analysis và regression tests.

---

## Task 5.6 — Linking evaluation và oracle report

### Mục tiêu

Phân biệt lỗi retrieval với lỗi reranking/set selection.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement linking-specific evaluation and oracle diagnostics.

Report by entity type and terminology:
- exact-match coverage;
- recall@1/5/10/20/50;
- MRR;
- oracle candidate Jaccard if the gold code is in the pool;
- reranker top-1 accuracy;
- final candidate-set Jaccard;
- abstention precision/coverage;
- error buckets: alias missing, retrieval miss, rerank miss, wrong granularity, structured mismatch, obsolete concept, ambiguous gold.

Requirements:
- use only frozen gold and terminology snapshots;
- no leaking gold into query construction;
- deterministic reports with sample/entity IDs;
- compare lexical-only, dense-only, fused, and reranked variants.
```

### Exit gate

Biết chính xác candidate score mất ở retrieval hay decoding.

---

# Phase 6 — Neural extraction và type classification

## Task 6.1 — Model protocol, artifact loader và training harness

### Mục tiêu

Tách train/predict/calibrate; mọi artifact có manifest.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the common model protocol, offline artifact loader, and reproducible training harness.

Create interfaces for:
- train(config, dataset_manifest) -> TrainingArtifact;
- predict(batch) -> RawPredictions;
- calibrate(dev_predictions) -> CalibrationArtifact;
- load artifact with checksum verification.

Requirements:
- deterministic seeds and dataloader settings where supported;
- config snapshots and code/data/model manifests;
- no automatic model download;
- parameter count and <=9B compliance recorded;
- training and inference dependencies separated when practical;
- raw logits separated from calibration and thresholds;
- resume behavior explicit;
- no train/dev/test leakage.

Use a tiny deterministic dummy model in tests. Do not train the final model in unit tests.
```

### Exit gate

Mọi model benchmark dùng chung harness và provenance.

---

## Task 6.2 — Span/type encoder benchmark

### Mục tiêu

Benchmark token/span classifier và type classifier trước LLM fine-tune.

### Prompt Codex

```text
[Use the master preamble]

Task: Add a benchmarkable encoder-based span/type model implementation.

Requirements:
- model selected through config, not hard-coded;
- training data built only from versioned grouped splits;
- exact span boundary labels follow annotation guide;
- handle Vietnamese subword alignment explicitly;
- type classifier receives grounded mention plus local structural context;
- output raw logits and span candidates, not final thresholded entities;
- batch inference and deterministic evaluation;
- record model/tokenizer checksum and parameter count;
- include hard-negative sampling for symptom/diagnosis, test name/result, and medication confusions.

Deliver:
- training command;
- inference wrapper;
- metrics report;
- tests using a tiny local fixture/model or mocked backbone;
- no network in tests or competition inference.
```

### Exit gate

Encoder model delta được đo so với deterministic baseline qua folds/seeds.

---

## Task 6.3 — LLM proposer <=9B và constrained JSON

### Mục tiêu

Thêm LLM như một proposer, không cho sinh position/codes.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement an optional self-hosted LLM span proposer constrained to <=9B parameters.

LLM may output only:
- exact copied mention text;
- provisional entity type;
- optional local evidence label.

LLM must not output:
- position;
- ICD/RxNorm code;
- final confidence;
- unsupported types;
- free-form explanations in production output.

Requirements:
- offline artifact loading and parameter-count validation;
- schema-constrained JSON parsing;
- robust handling of malformed output without inventing entities;
- prompts versioned and stored as artifacts;
- exact-copy objective checked before proposal acceptance;
- grounding remains a separate deterministic step;
- deterministic generation settings for competition mode;
- batch/token/time limits;
- privacy-safe logs;
- feature flag OFF by default in MVP.

Tests use a mocked local generator and cover malformed JSON, hallucinated text, duplicate mentions, unsupported type, and timeout.
```

### Exit gate

LLM proposer chỉ được bật nếu ablation có positive score delta.

---

## Task 6.4 — Calibration, source fusion và leakage safeguards

### Mục tiêu

Calibrate out-of-fold scores và fusion multi-source không overfit.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement out-of-fold calibration and source-aware proposal fusion for neural and deterministic sources.

Requirements:
- support temperature scaling, Platt, and isotonic behind a common interface;
- calibration fitted only on designated dev/out-of-fold predictions;
- never evaluate calibration on the same examples used to fit it;
- calibration artifacts versioned and checksum-verified;
- source-specific reliability features;
- per-type thresholds;
- fusion model can be a rule/meta-classifier selected by config;
- missing source scores handled explicitly;
- produce reliability diagrams/tables and expected calibration error;
- dataset group IDs checked to prevent leakage.

Tests include synthetic logits with known calibration behavior, missing classes, single-class failure handling, and deterministic artifact reload.
```

### Exit gate

Calibrated fusion cải thiện official dev score/precision ổn định.

---

# Phase 7 — Score-aware decoding và ontology gating

## Task 7.1 — Entity utility và joint decoder

### Mục tiêu

Quyết định giữ entity/type/assertions/candidate set theo expected official score.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement a score-aware joint entity decoder as a pure deterministic component.

Inputs:
- grounded entity hypotheses;
- calibrated span/type/assertion/link probabilities;
- candidate-score vectors;
- overlap relationships;
- configured utility weights and thresholds.

Decisions:
- keep/drop entity;
- choose final type;
- include assertion labels;
- choose final candidate set;
- abstain at each field independently where allowed.

Requirements:
- optimize a configurable approximation of the official score and double-penalty risk;
- no model inference inside decoder;
- no hard-coded threshold;
- per-type/per-label configuration;
- deterministic tie-breaking;
- every decision produces a utility breakdown and trace;
- pure function suitable for Optuna or grid search;
- constraints enforce schema applicability.

Tests cover low type confidence, high span/low link confidence, empty assertions, extra candidate penalty, conflicting type evidence, and deterministic ties.
```

### Exit gate

Threshold tuning chỉ gọi pure decoder + scorer.

---

## Task 7.2 — Global consistency resolver

### Mục tiêu

Giải overlap/conflict toàn document mà không đồng nhất entity chỉ theo text.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement the global consistency resolver.

Rules/invariants:
- entity identity is positional and context-aware, never surface-text-only;
- same ingredient with different strengths may map to different RxNorm concepts;
- overlapping entities follow annotation policy and utility;
- duplicate exact objects are removed;
- lab result pairing remains locally consistent;
- output ordering is deterministic;
- unsupported global conflict causes abstention or explicit resolution trace.

Start with weighted interval scheduling or deterministic conflict rules. Add ILP only behind an optional interface if simpler methods are insufficient.

Tests:
- two clonazepam strengths;
- repeated symptoms with different assertions;
- nested medication alias/strength spans;
- overlapping symptom/diagnosis proposals;
- lab result assigned to wrong neighboring test;
- exact duplicate proposals;
- tie resolution.
```

### Exit gate

Global resolver không giảm score trên non-conflict fixtures và sửa conflict challenge set.

---

## Task 7.3 — Ontology gate, constraints và ablation

### Mục tiêu

Chỉ dùng hierarchy/graph khi top candidates nhập nhằng và chứng minh lợi ích.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement a gated ontology constraint/reranking layer and its ablation evaluation.

Gate inputs may include:
- number of candidates;
- top1-top2 margin;
- alias ambiguity;
- hierarchy conflict;
- structured medication mismatch;
- model uncertainty.

Ontology actions may include:
- type-candidate compatibility;
- ICD parent/child/sibling features;
- RxNorm ingredient/strength/form compatibility;
- hierarchy-aware hard constraints only when logically safe;
- score adjustments with explanations.

Requirements:
- gate OFF for unique exact matches and high-margin simple cases;
- no full GraphRAG or document QA system;
- no new candidate invented outside terminology snapshot;
- every score adjustment traceable;
- latency and memory measured;
- feature flag and fallback to no-ontology behavior;
- ablation compares OFF, always ON, and gated ON using official score, candidate Jaccard, and latency.

Merge criteria: positive and stable score delta after latency cost. Otherwise leave feature disabled.
```

### Exit gate

Ontology chỉ bật trong competition profile khi ablation thắng.

---

# Phase 8 — Productionization, offline inference và reproduce drill

## Task 8.1 — Config profiles và CLI

### Mục tiêu

Một CLI chuẩn, config validation, profiles MVP/competition/fast fallback.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement typed configuration loading and the MedLink-IE CLI.

Profiles:
- MVP deterministic;
- competition full;
- fast fallback.

Commands:
- validate-config;
- prepare-terminology;
- train or benchmark module where supported;
- infer one file/directory;
- evaluate;
- package;
- validate-submit;
- show-manifest.

Requirements:
- fail fast on unknown keys and incompatible feature combinations;
- resolved config is saved in run artifacts;
- paths can be relative to project/config location deterministically;
- secrets are not printed;
- offline flag enforced;
- feature flags include LLM, dense, reranker, ontology, fuzzy grounding;
- CLI has stable exit codes and helpful safe errors.

Tests use temporary configs and do not invoke heavy models.
```

### Exit gate

Mọi workflow chính chạy qua CLI, không cần sửa code.

---

## Task 8.2 — Batch inference, failure isolation và observability

### Mục tiêu

Chạy private test bền vững, trace riêng, metrics timing.

### Prompt Codex

```text
[Use the master preamble]

Task: Harden batch inference, failure isolation, and observability.

Requirements:
- deterministic sample order;
- configurable batch sizes;
- per-sample exception isolation;
- atomic writes and resumable behavior with explicit policy;
- no partial/corrupt output considered successful;
- module timing, memory when available, counts, abstentions, and failure categories;
- per-entity decision traces stored separately from submission;
- no raw clinical text in normal logs;
- run manifest written before and finalized after execution;
- graceful failure when artifact/checksum/config is missing;
- no silent model downgrade;
- timeout/OOM behavior explicit.

Integration tests simulate one bad sample among valid samples, interrupted write, resume, and deterministic rerun.
```

### Exit gate

Một lỗi sample/module không làm hỏng toàn run và luôn được báo rõ.

---

## Task 8.3 — Output packaging và pre-submit validator hardening

### Mục tiêu

Loại mọi lỗi submission format trước khi nộp.

### Prompt Codex

```text
[Use the master preamble]

Task: Harden submission packaging and the pre-submit validator.

Validate:
- exact zip and directory structure;
- exact expected filenames and sample count;
- UTF-8 JSON encoding;
- JSON top-level type;
- allowed keys only;
- required/optional fields by entity type;
- position integer convention and bounds;
- text/raw slice equality using original inputs;
- allowed types and assertion labels;
- candidate code membership in frozen terminology;
- duplicate objects and deterministic ordering;
- no NaN/Infinity/debug fields;
- no extra hidden files;
- zip can be reopened and fully read.

Packager must use deterministic ordering and, when practical, deterministic zip metadata for reproducibility.

Create adversarial invalid-package tests for every rule.
```

### Exit gate

`validate-submit output.zip` pass là điều kiện bắt buộc trước submit.

---

## Task 8.4 — Offline artifacts, container và clean reproduce drill

### Mục tiêu

BTC có thể dựng lại không Internet.

### Prompt Codex

```text
[Use the master preamble]

Task: Implement offline artifact verification, containerization, and a clean reproducibility workflow.

Deliver:
- artifact inventory with relative paths, sizes, SHA-256, licenses, and required/optional status;
- offline preflight command;
- Dockerfile or documented clean environment matching competition constraints;
- locked dependencies;
- one-command smoke inference;
- one-command full inference;
- reproduction script that starts from a clean directory/container;
- environment and hardware report.

Requirements:
- build/runtime must not download model or terminology artifacts unexpectedly;
- missing artifact errors are actionable;
- container does not embed secrets;
- all model parameter limits validated;
- generated outputs and metrics compared with expected smoke hashes or semantic golden results;
- document CPU/GPU modes and expected resource use.

Run the reproduce drill in a clean environment and record exact commands and results.
```

### Exit gate

Một thành viên không viết module có thể reproduce từ README trên máy sạch.

---

## Task 8.5 — Final README và submission gate

### Mục tiêu

Đóng gói source, weights, data, docs và checklist cuối.

### Prompt Codex

```text
[Use the master preamble]

Task: Produce the final technical README and automated submission-readiness gate.

README must include:
- problem and architecture overview;
- exact supported environment;
- repository layout;
- artifact acquisition/location without exposing secrets;
- installation;
- terminology preparation;
- training commands and expected artifacts;
- inference command;
- evaluation command;
- packaging and validation;
- offline mode;
- profiles and feature flags;
- resource estimates;
- troubleshooting;
- reproducibility limitations and assumptions;
- license/provenance notes.

Automated final gate checks:
- clean git status or recorded commit;
- config/schema validity;
- artifact checksums;
- tests;
- smoke inference;
- output validation;
- model <=9B compliance;
- no network calls in competition profile;
- required source/data/weights/docs present;
- run manifest complete.

Do not fabricate benchmark numbers. Pull them from versioned evaluation artifacts.
```

### Exit gate

Final gate pass, clean reproduce pass, output.zip pass.

---

# B. Thứ tự chạy khuyến nghị

```text
0.1 → 0.2 → 0.3 → 0.4 → 0.5
  ↓
1.1 → 1.2 → 1.3 → 1.4
  ↓
2.1 → 2.2/2.3/2.4 → 2.5 → 2.6 → 2.7
  ↓
3.1 → 3.2 → 3.3
  ↓
4.1 → 4.2 → 4.3
  ↓
5.1 → 5.2 → 5.3 → 5.4 → 5.5 → 5.6
  ↓
6.1 → 6.2/6.3 → 6.4
  ↓
7.1 → 7.2 → 7.3
  ↓
8.1 → 8.2 → 8.3 → 8.4 → 8.5
```

Các task song song an toàn sau khi contracts ổn:

- 2.2 medication proposer và 2.3 lab proposer;
- 2.4 symptom/diagnosis proposer;
- 4.1 assertion scope trong khi 5.1 terminology preparation;
- 6.2 encoder benchmark và 6.3 LLM proposer;
- documentation có thể cập nhật liên tục nhưng final README chỉ khóa ở 8.5.

---

# C. Definition of Done chuẩn cho issue/task

```markdown
## Goal

## Source specification

## In scope

## Out of scope

## Inputs

## Outputs

## Edge cases

## Acceptance tests

## Observability requirements

## Expected files changed

## Definition of Done
- [ ] Ambiguities documented
- [ ] Tests written first
- [ ] Implementation complete
- [ ] Formatter passes
- [ ] Linter passes
- [ ] Type checker passes
- [ ] Targeted tests pass
- [ ] Full suite passes or exception documented
- [ ] Hostile review completed
- [ ] No unrelated diff
- [ ] Documentation/config updated
- [ ] Decision traces added where required
- [ ] Assumptions and remaining risks recorded
```

---

# D. Prompt mở đầu một phiên Codex mới

```text
You are starting a new MedLink-IE implementation session.

Read AGENTS.md and the task specification before touching code. Inspect the repository and report:
1. current relevant architecture;
2. source-of-truth rules;
3. files likely to change;
4. edge cases;
5. tests to add;
6. ambiguities/blockers.

Current task: [TASK ID AND NAME]

Use the task-specific prompt from `medlink_ie_codex_playbook_full.md`.
Do not broaden scope. Do not implement another phase early. Stop if the contract is ambiguous in a way that affects offsets, scorer behavior, annotation, or terminology.
```

---

# E. Quy tắc merge

Một task chỉ merge khi:

1. acceptance tests pass;
2. hostile review không còn BLOCKER/HIGH;
3. contract không bị sửa ngầm;
4. run/test commands được ghi lại;
5. không có dependency hoặc architecture ngoài scope;
6. branch có commit nhỏ, dễ revert;
7. exit gate của task đạt.

Các module nâng cao như LLM proposer, dense retrieval và ontology phải có ablation positive trước khi bật trong competition profile.
