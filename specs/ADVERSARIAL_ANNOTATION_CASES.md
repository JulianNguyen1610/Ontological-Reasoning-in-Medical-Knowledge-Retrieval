# Adversarial annotation cases — review set v0.1

**Status:** `NEEDS_ADJUDICATION`; this is not a gold dataset.

## Reading this file

The current `ANNOTATION_GUIDE.md` supplies only these enforceable rules: annotate
exact substrings, do not normalize text, compute offsets by code, and record
ambiguous cases for adjudication.  Its entity-boundary, disambiguation,
assertion, overlap, and repeated-mention policies are blank.  Consequently,
every proposed entity below is a review hypothesis, **not** an expected gold
label.  `NEEDS_ADJUDICATION` in the Expected entities column means that no
annotation decision is asserted by this fixture.

Abbreviations in the table: `S` = TRIỆU_CHỨNG, `D` = CHẨN_ĐOÁN, `TN` =
TÊN_XÉT_NGHIỆM, `TR` = KẾT_QUẢ_XÉT_NGHIỆM, `M` = THUỐC.  Quoted text is an
exact-substring hypothesis only; offsets must be computed from the final raw
text after an adjudicator has selected a policy.

| ID | Raw text | Expected entities (not gold) | Rationale | Policy rule invoked | Ambiguity flag |
|---|---|---|---|---|---|
| SD01 | BN đau ngực 2 giờ, chưa rõ nguyên nhân. | NEEDS_ADJUDICATION: `đau ngực` → S/D | Symptom wording without diagnostic trigger. | §3 symptom vs diagnosis — blank | NEEDS_ADJUDICATION |
| SD02 | Chẩn đoán đau ngực không điển hình. | NEEDS_ADJUDICATION: `đau ngực không điển hình` → S/D | Diagnostic trigger may alter type/boundary. | §2.1, §2.2, §3 — blank | NEEDS_ADJUDICATION |
| SD03 | BN có sốt và được chẩn đoán viêm phổi. | NEEDS_ADJUDICATION: `sốt`→S; `viêm phổi`→D | Straightforward-looking pair tests trigger handling. | §2.1/§2.2 — blank | NEEDS_ADJUDICATION |
| SD04 | Theo dõi tăng huyết áp, hiện không đau đầu. | NEEDS_ADJUDICATION: `tăng huyết áp`→D?; `đau đầu`→S? | Follow-up status and negation coexist. | §2.2; §4.1 — blank | NEEDS_ADJUDICATION |
| SD05 | Khó thở do suy tim mất bù. | NEEDS_ADJUDICATION: `khó thở`→S; `suy tim mất bù`→D | Causal phrase may invite merged versus separate spans. | §2.1/§2.2; §5 — blank | NEEDS_ADJUDICATION |
| SD06 | Nghi viêm ruột thừa vì đau hố chậu phải. | NEEDS_ADJUDICATION: `viêm ruột thừa`→D?; `đau hố chậu phải`→S | Possible diagnosis policy is absent. | §2.2 differential policy — blank | NEEDS_ADJUDICATION |
| SD07 | Ho kéo dài, chẩn đoán theo dõi lao phổi. | NEEDS_ADJUDICATION: `ho kéo dài`→S; `lao phổi`→D? | “Theo dõi” has no defined type/assertion effect. | §2.2; §4.1 — blank | NEEDS_ADJUDICATION |
| SD08 | Bệnh nhân béo phì kèm đau gối. | NEEDS_ADJUDICATION: `béo phì`→S/D; `đau gối`→S | Condition versus diagnosis boundary is unfilled. | §3 symptom vs diagnosis — blank | NEEDS_ADJUDICATION |
| SD09 | Tiền sử migraine, hôm nay đau đầu dữ dội. | NEEDS_ADJUDICATION: `migraine`→D?; `đau đầu dữ dội`→S | History and current symptom must not be conflated. | §2.1/§2.2; §4.2 — blank | NEEDS_ADJUDICATION |
| SD10 | Kết luận: đau thần kinh tọa. | NEEDS_ADJUDICATION: `đau thần kinh tọa`→S/D | Section/triggers are not defined. | §2.1/§2.2; §3 — blank | NEEDS_ADJUDICATION |
| LR01 | Xét nghiệm glucose máu: 8,2 mmol/L. | NEEDS_ADJUDICATION: `glucose máu`→TN; `8,2 mmol/L`→TR | Test-result boundary policy is empty. | §2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| LR02 | HbA1c 7,1%. | NEEDS_ADJUDICATION: `HbA1c`→TN; `7,1%`→TR | Abbreviation and numeric result. | §2.4 abbreviations; §2.5 numeric — blank | NEEDS_ADJUDICATION |
| LR03 | Men gan AST tăng 125 U/L. | NEEDS_ADJUDICATION: `AST`→TN?; `tăng 125 U/L`→TR? | Qualifier may belong to value or be excluded. | §2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| LR04 | Siêu âm bụng: gan nhiễm mỡ độ 2. | NEEDS_ADJUDICATION: `Siêu âm bụng`→TN?; `gan nhiễm mỡ độ 2`→D/TR? | Imaging result policy is explicitly blank. | §2.2 imaging; §2.4 — blank | NEEDS_ADJUDICATION |
| LR05 | Cấy máu âm tính. | NEEDS_ADJUDICATION: `Cấy máu`→TN; `âm tính`→TR | Qualitative result boundary missing. | §2.5 qualitative — blank | NEEDS_ADJUDICATION |
| LR06 | CRP: 30 mg/L (bình thường <5). | NEEDS_ADJUDICATION: `CRP`→TN; `30 mg/L`→TR; range→TR? | Range inclusion is undecided. | §2.5 unit/range — blank | NEEDS_ADJUDICATION |
| LR07 | Test nhanh cúm A dương tính. | NEEDS_ADJUDICATION: `Test nhanh cúm A`→TN; `dương tính`→TR | Procedure/name versus result. | §2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| LR08 | Kết quả INR 1,8, cao. | NEEDS_ADJUDICATION: `INR`→TN; `1,8, cao`→TR? | Flag may be inside or outside result span. | §2.5 H/L flag — blank | NEEDS_ADJUDICATION |
| LR09 | X-quang phổi không thấy tổn thương cấp. | NEEDS_ADJUDICATION: `X-quang phổi`→TN?; result→TR/D? | Imaging and negated finding. | §2.2 imaging; §2.4/§2.5; §4.1 — blank | NEEDS_ADJUDICATION |
| LR10 | Protein niệu vết (+/-). | NEEDS_ADJUDICATION: `Protein niệu`→TN/TR?; `vết (+/-)`→TR? | Same phrase may denote analyte or result. | §3 test name vs result — blank | NEEDS_ADJUDICATION |
| HM01 | Tiền sử dùng amlodipine 5 mg mỗi sáng. | NEEDS_ADJUDICATION: medication span→M; isHistorical? | Historical cue and medication boundary. | §2.3; §4.2 — blank | NEEDS_ADJUDICATION |
| HM02 | Thuốc trước nhập viện: metformin 500 mg x 2 lần/ngày. | NEEDS_ADJUDICATION: medication span→M; isHistorical? | Section-level medication-list policy absent. | §2.3; §4.2 medication-list — blank | NEEDS_ADJUDICATION |
| HM03 | Đã ngừng warfarin 3 tháng trước. | NEEDS_ADJUDICATION: `warfarin`→M; isHistorical? | Discontinued-medication treatment not defined. | §4.2 — blank | NEEDS_ADJUDICATION |
| HM04 | Từng dị ứng penicillin, không còn dùng thuốc. | NEEDS_ADJUDICATION: `penicillin`→M; assertion? | Past exposure versus allergy relation. | §2.3; §4.2 — blank | NEEDS_ADJUDICATION |
| HM05 | Đơn cũ gồm insulin glargine và aspirin. | NEEDS_ADJUDICATION: both medication spans; isHistorical? | List propagation not defined. | §2.3; §4.2 — blank | NEEDS_ADJUDICATION |
| HM06 | Hiện đang dùng losartan; trước đây dùng enalapril. | NEEDS_ADJUDICATION: two M spans; history only for enalapril? | Local temporal scope. | §4.2 local cues — blank | NEEDS_ADJUDICATION |
| HM07 | Ra viện tiếp tục atorvastatin 20 mg mỗi tối. | NEEDS_ADJUDICATION: medication span→M; isHistorical? | Discharge plan is not covered. | §2.3; §4.2 — blank | NEEDS_ADJUDICATION |
| HM08 | Bệnh sử ghi nhận đã tự mua paracetamol khi sốt. | NEEDS_ADJUDICATION: `paracetamol`→M; isHistorical? | Narrative past event. | §2.3; §4.2 — blank | NEEDS_ADJUDICATION |
| HM09 | Danh sách thuốc cũ: vitamin D, canxi, omeprazole. | NEEDS_ADJUDICATION: three M spans; isHistorical? | Coordination/list and section scope. | §2.3; §4.2 — blank | NEEDS_ADJUDICATION |
| HM10 | BN quên tên thuốc huyết áp đã dùng trước đó. | NEEDS_ADJUDICATION: `thuốc huyết áp`→M?; isHistorical? | Generic class mention policy absent. | §2.3; §4.2 — blank | NEEDS_ADJUDICATION |
| NG01 | Không sốt, ho khan 3 ngày. | NEEDS_ADJUDICATION: `sốt`→S+negated?; `ho khan`→S | Negation clause boundary. | §4.1 clause boundary — blank | NEEDS_ADJUDICATION |
| NG02 | Không ho hoặc khó thở khi nghỉ. | NEEDS_ADJUDICATION: `ho`, `khó thở` assertions? | Coordination scope. | §4.1 conjunction exceptions — blank | NEEDS_ADJUDICATION |
| NG03 | Không đau ngực nhưng có hồi hộp. | NEEDS_ADJUDICATION: `đau ngực` negated?; `hồi hộp` positive? | Contrast boundary. | §4.1 clause boundary — blank | NEEDS_ADJUDICATION |
| NG04 | Bác sĩ không loại trừ viêm phổi. | NEEDS_ADJUDICATION: `viêm phổi`→D; negated? | “Không loại trừ” policy absent. | §4.1 rule-out policy — blank | NEEDS_ADJUDICATION |
| NG05 | Không thấy phù chân, trừ mắt cá phải hơi sưng. | NEEDS_ADJUDICATION: `phù chân`, `sưng` assertions? | Exception to negation. | §4.1 conjunction exceptions — blank | NEEDS_ADJUDICATION |
| NG06 | Phủ nhận buồn nôn, nôn và tiêu chảy. | NEEDS_ADJUDICATION: three S spans; all negated? | List propagation. | §4.1 clause boundary — blank | NEEDS_ADJUDICATION |
| NG07 | Không còn đau đầu sau khi uống thuốc. | NEEDS_ADJUDICATION: `đau đầu` negated? | Temporal “không còn” treatment. | §4.1 trigger list — blank | NEEDS_ADJUDICATION |
| NG08 | Chưa ghi nhận suy hô hấp, đang thở oxy. | NEEDS_ADJUDICATION: `suy hô hấp`→D?; negated? | “Chưa ghi nhận” not defined. | §4.1 trigger list — blank | NEEDS_ADJUDICATION |
| NG09 | Không chỉ định xét nghiệm troponin hôm nay. | NEEDS_ADJUDICATION: `xét nghiệm troponin`→TN?; negated? | Negation of plan versus entity. | §2.4; §4.1 — blank | NEEDS_ADJUDICATION |
| NG10 | BN không sốt cao, chỉ 37,5°C. | NEEDS_ADJUDICATION: `sốt cao` negated?; `37,5°C`→TR? | Modifier scope and result type. | §4.1; §2.5 — blank | NEEDS_ADJUDICATION |
| FS01 | Mẹ bệnh nhân bị đái tháo đường. | NEEDS_ADJUDICATION: `đái tháo đường`→D+family? | Kinship scope. | §4.3 kinship list — blank | NEEDS_ADJUDICATION |
| FS02 | Bố từng tăng huyết áp, BN hiện khỏe. | NEEDS_ADJUDICATION: `tăng huyết áp`→D+family? | Family entity versus patient status. | §4.3 — blank | NEEDS_ADJUDICATION |
| FS03 | Chị gái ho kéo dài, bệnh nhân không ho. | NEEDS_ADJUDICATION: two `ho` spans with different assertions | Speaker/kinship scope and repetition. | §4.3; §4.1; §5 — blank | NEEDS_ADJUDICATION |
| FS04 | Gia đình có người mắc ung thư đại tràng. | NEEDS_ADJUDICATION: `ung thư đại tràng`→D+family? | Indefinite family member policy. | §4.3 — blank | NEEDS_ADJUDICATION |
| FS05 | Mẹ dùng insulin, BN dùng metformin. | NEEDS_ADJUDICATION: both M spans; family only first? | Family propagation across coordinated clauses. | §4.3; §2.3 — blank | NEEDS_ADJUDICATION |
| FS06 | Tiền sử gia đình: bố và em trai hen phế quản. | NEEDS_ADJUDICATION: `hen phế quản`→D+family? | Multiple relatives and shared entity. | §4.3 multiple family members — blank | NEEDS_ADJUDICATION |
| FS07 | Con bệnh nhân sốt, BN đến khám vì đau họng. | NEEDS_ADJUDICATION: `sốt` family?; `đau họng` patient? | Subject switch. | §4.3; §2.1 — blank | NEEDS_ADJUDICATION |
| FS08 | Bệnh nhân kể dì ruột từng bị đột quỵ. | NEEDS_ADJUDICATION: `đột quỵ`→D+family? | Extended kinship list missing. | §4.3 kinship list — blank | NEEDS_ADJUDICATION |
| FS09 | Anh trai không bị lao phổi. | NEEDS_ADJUDICATION: `lao phổi` family+negated? | Multi-label combination policy absent. | §4.3; §4.1; §4.4 — blank | NEEDS_ADJUDICATION |
| FS10 | Gia đình không ai dị ứng thuốc. | NEEDS_ADJUDICATION: `dị ứng thuốc`→S/D?; family+negated? | Group family and negation scope. | §4.3; §4.1; §4.4 — blank | NEEDS_ADJUDICATION |
| OV01 | Đau ngực do nhồi máu cơ tim. | NEEDS_ADJUDICATION: `đau ngực`→S; `nhồi máu cơ tim`→D; merged span? | Coordination/overlap policy. | §5 nested policy — blank | NEEDS_ADJUDICATION |
| OV02 | Viêm phổi cộng đồng nặng. | NEEDS_ADJUDICATION: full D; `viêm phổi` nested D? | Nested same-type policy. | §5 nested policy — blank | NEEDS_ADJUDICATION |
| OV03 | Kết quả xét nghiệm glucose máu tăng. | NEEDS_ADJUDICATION: `xét nghiệm glucose máu`→TN?; `glucose máu tăng`→TR? | Partly overlapping test/result spans. | §2.4/§2.5; §5 — blank | NEEDS_ADJUDICATION |
| OV04 | Dùng aspirin 81 mg để phòng nhồi máu cơ tim. | NEEDS_ADJUDICATION: M span; `nhồi máu cơ tim`→D; indication overlap? | Medication boundary and relation are absent. | §2.3; §5 — blank | NEEDS_ADJUDICATION |
| OV05 | Đau bụng cấp do viêm ruột thừa cấp. | NEEDS_ADJUDICATION: symptom/diagnosis full and nested adjectives | Multiple candidate boundaries. | §2.1/§2.2; §5 — blank | NEEDS_ADJUDICATION |
| OV06 | Hb 8 g/dL, thiếu máu nặng. | NEEDS_ADJUDICATION: `Hb`→TN; `8 g/dL`→TR; `thiếu máu nặng`→D | Adjacent versus overlapping evidence. | §2.4/§2.5; §5 — blank | NEEDS_ADJUDICATION |
| OV07 | Không có dấu hiệu suy tim cấp. | NEEDS_ADJUDICATION: `suy tim cấp`→D; `dấu hiệu suy tim cấp`→S/D? | Nested phrase and negation. | §2.1/§2.2; §4.1; §5 — blank | NEEDS_ADJUDICATION |
| OV08 | X-quang cho thấy tràn dịch màng phổi. | NEEDS_ADJUDICATION: `X-quang`→TN?; finding→D/TR? | Imaging finding type/overlap. | §2.2 imaging; §2.4/§2.5; §5 — blank | NEEDS_ADJUDICATION |
| OV09 | Tăng men gan AST. | NEEDS_ADJUDICATION: `men gan AST`→TN?; `tăng men gan`→TR/D? | Overlapping analyte/result phrase. | §3 test name vs result; §5 — blank | NEEDS_ADJUDICATION |
| OV10 | Đau lưng do thoát vị đĩa đệm thắt lưng. | NEEDS_ADJUDICATION: S/D spans; possible nested diagnosis | Cause phrase spans not specified. | §2.1/§2.2; §5 — blank | NEEDS_ADJUDICATION |
| RP01 | BN ho buổi sáng, chiều vẫn ho. | NEEDS_ADJUDICATION: two `ho` spans | Repeated same surface form. | §5 same text/different positions — blank | NEEDS_ADJUDICATION |
| RP02 | Đau đầu giảm rồi đau đầu trở lại. | NEEDS_ADJUDICATION: two `đau đầu` spans | Repetition with temporal change. | §5 — blank | NEEDS_ADJUDICATION |
| RP03 | Metformin sáng và metformin tối. | NEEDS_ADJUDICATION: two M spans or one? | Repeated medication mention policy. | §2.3; §5 — blank | NEEDS_ADJUDICATION |
| RP04 | CRP tăng, sau điều trị CRP giảm. | NEEDS_ADJUDICATION: two TN/TR pairs | Same test name, distinct results. | §2.4/§2.5; §5 — blank | NEEDS_ADJUDICATION |
| RP05 | Không sốt hôm qua, hôm nay sốt 39°C. | NEEDS_ADJUDICATION: two `sốt` spans with distinct assertion | Repetition across temporal clauses. | §4.1; §5 — blank | NEEDS_ADJUDICATION |
| RP06 | Mẹ bị hen, BN cũng bị hen. | NEEDS_ADJUDICATION: two `hen` spans; family differs | Repeated mention and family scope. | §4.3; §5 — blank | NEEDS_ADJUDICATION |
| RP07 | Aspirin gây đau dạ dày, ngừng aspirin. | NEEDS_ADJUDICATION: two M spans; possible historical second | Repetition with action. | §2.3; §4.2; §5 — blank | NEEDS_ADJUDICATION |
| RP08 | Siêu âm lần 1 bình thường, siêu âm lần 2 có sỏi mật. | NEEDS_ADJUDICATION: two TN spans and result/finding spans | Same procedure in different contexts. | §2.4/§2.5; §5 — blank | NEEDS_ADJUDICATION |
| RP09 | BN không đau ngực nhưng sau đó đau ngực tăng. | NEEDS_ADJUDICATION: two spans; first negated only? | Negation must not leak to repeat. | §4.1; §5 — blank | NEEDS_ADJUDICATION |
| RP10 | Chẩn đoán đái tháo đường, kiểm soát đái tháo đường kém. | NEEDS_ADJUDICATION: two D spans or one? | Repeated diagnosis term and boundary. | §2.2; §5 — blank | NEEDS_ADJUDICATION |
| MF01 | Paracetamol 500 mg viên uống khi sốt. | NEEDS_ADJUDICATION: M boundary includes strength/form/route/PRN? | All medication slots unresolved. | §2.3 include fields — blank | NEEDS_ADJUDICATION |
| MF02 | Insulin glargine 100 đơn vị/mL, tiêm 10 đơn vị tối. | NEEDS_ADJUDICATION: one or two M spans; include dose? | Strength and administration ambiguity. | §2.3 — blank | NEEDS_ADJUDICATION |
| MF03 | Amoxicillin/clavulanate 875/125 mg po bid. | NEEDS_ADJUDICATION: combined M full or split? | Combination-drug policy absent. | §2.3 combination policy — blank | NEEDS_ADJUDICATION |
| MF04 | Salbutamol xịt 100 mcg, 2 nhát khi khó thở. | NEEDS_ADJUDICATION: M boundary includes device/dose/frequency? | Form and dosage fragment. | §2.3 — blank | NEEDS_ADJUDICATION |
| MF05 | Furosemide 40 mg IV mỗi 12 giờ. | NEEDS_ADJUDICATION: full M span or ingredient only? | Route/frequency inclusion blank. | §2.3 — blank | NEEDS_ADJUDICATION |
| MF06 | Kem clotrimazole 1% bôi vùng tổn thương. | NEEDS_ADJUDICATION: M boundary includes concentration/application? | Topical form policy missing. | §2.3 — blank | NEEDS_ADJUDICATION |
| MF07 | Prednisolone 5 mg giảm liều dần. | NEEDS_ADJUDICATION: M span includes taper instruction? | Frequency/instruction boundary. | §2.3 — blank | NEEDS_ADJUDICATION |
| MF08 | Ceftriaxone 2 g truyền tĩnh mạch mỗi ngày. | NEEDS_ADJUDICATION: M boundary includes infusion route/frequency? | Medication-slot inclusion blank. | §2.3 — blank | NEEDS_ADJUDICATION |
| MF09 | Thuốc nhỏ mắt timolol 0,5%, 1 giọt mỗi bên. | NEEDS_ADJUDICATION: M boundary includes site/count? | Form/route and dose wording. | §2.3 — blank | NEEDS_ADJUDICATION |
| MF10 | Aspirin 81-mg enteric-coated tablet daily. | NEEDS_ADJUDICATION: M boundary includes English form/frequency? | Mixed-language form policy missing. | §2.3 — blank | NEEDS_ADJUDICATION |
| QL01 | Nước tiểu trong, không có protein. | NEEDS_ADJUDICATION: `trong`→TR?; `protein`→TN/TR? | Qualitative result and negation. | §2.5 qualitative; §4.1 — blank | NEEDS_ADJUDICATION |
| QL02 | Cấy đờm mọc Klebsiella pneumoniae. | NEEDS_ADJUDICATION: test and organism result spans | Microbiology-result boundary absent. | §2.5 qualitative — blank | NEEDS_ADJUDICATION |
| QL03 | HBsAg dương tính yếu. | NEEDS_ADJUDICATION: `HBsAg`→TN; `dương tính yếu`→TR | Qualifier inclusion. | §2.5 qualitative — blank | NEEDS_ADJUDICATION |
| QL04 | Xét nghiệm HIV âm tính. | NEEDS_ADJUDICATION: `Xét nghiệm HIV`→TN; `âm tính`→TR | Test versus concept naming. | §2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| QL05 | Soi phân không thấy trứng giun. | NEEDS_ADJUDICATION: test and negative qualitative result | Negated/qualitative scope. | §2.5; §4.1 — blank | NEEDS_ADJUDICATION |
| QL06 | Dịch màng phổi màu vàng chanh. | NEEDS_ADJUDICATION: phrase→TR? | Descriptive qualitative result boundary. | §2.5 qualitative — blank | NEEDS_ADJUDICATION |
| QL07 | Hồng cầu niệu ++. | NEEDS_ADJUDICATION: `Hồng cầu niệu`→TN/TR?; `++`→TR | Analyte/result split unclear. | §3 test name vs result; §2.5 — blank | NEEDS_ADJUDICATION |
| QL08 | Phết máu ngoại vi có blast. | NEEDS_ADJUDICATION: test and finding spans | Procedure/finding policy. | §2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| QL09 | Men tim troponin I tăng nhẹ. | NEEDS_ADJUDICATION: `troponin I`→TN; `tăng nhẹ`→TR | Result qualifiers and test boundary. | §2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| QL10 | PCR SARS-CoV-2 không phát hiện. | NEEDS_ADJUDICATION: `PCR SARS-CoV-2`→TN; `không phát hiện`→TR? | Qualitative negative wording. | §2.5 qualitative; §4.1 — blank | NEEDS_ADJUDICATION |
| MX01 | Tiền sử mẹ bị tăng huyết áp; BN không tăng huyết áp. | NEEDS_ADJUDICATION: two D spans, family/negation differ | Family, negation, repeat. | §4.1/§4.3/§5 — blank | NEEDS_ADJUDICATION |
| MX02 | Không thấy viêm phổi trên X-quang, nhưng CRP tăng. | NEEDS_ADJUDICATION: D?/TN/TR spans | Imaging, negation, test result. | §2.2/§2.4/§2.5/§4.1 — blank | NEEDS_ADJUDICATION |
| MX03 | Danh sách thuốc cũ: aspirin 81 mg; hiện ngừng aspirin. | NEEDS_ADJUDICATION: two M spans, historical scope | List, boundary, repeat. | §2.3/§4.2/§5 — blank | NEEDS_ADJUDICATION |
| MX04 | Bố ho, BN ho kèm sốt. | NEEDS_ADJUDICATION: two `ho`; `sốt` | Family scope and repeated surface. | §2.1/§4.3/§5 — blank | NEEDS_ADJUDICATION |
| MX05 | Siêu âm: gan nhiễm mỡ, men gan ALT bình thường. | NEEDS_ADJUDICATION: imaging/test/result/finding spans | Diagnosis vs imaging and qualitative lab. | §2.2/§2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| MX06 | Không đau bụng sau dùng omeprazole 20 mg po daily. | NEEDS_ADJUDICATION: S negation; M boundary | Negation plus medication slots. | §2.3/§4.1 — blank | NEEDS_ADJUDICATION |
| MX07 | Nghi sốt xuất huyết vì tiểu cầu 70 G/L. | NEEDS_ADJUDICATION: D?; TN/TR spans | Possible diagnosis and numeric lab. | §2.2/§2.4/§2.5 — blank | NEEDS_ADJUDICATION |
| MX08 | Không có khó thở, trừ khi gắng sức; mẹ có hen. | NEEDS_ADJUDICATION: S scope; D family | Exception, family, symptom boundary. | §4.1/§4.3 — blank | NEEDS_ADJUDICATION |
| MX09 | Metformin 500 mg x 2 lần/ngày điều trị đái tháo đường. | NEEDS_ADJUDICATION: M boundary; D span | Medication form and indication. | §2.2/§2.3 — blank | NEEDS_ADJUDICATION |
| MX10 | Cấy nước tiểu âm tính, nhưng tiểu buốt vẫn tái diễn. | NEEDS_ADJUDICATION: TN/TR; S | Qualitative result versus current symptom. | §2.1/§2.4/§2.5 — blank | NEEDS_ADJUDICATION |

## Coverage check

| Category | IDs | Count |
|---|---|---:|
| Symptom vs diagnosis | SD01–SD10 | 10 |
| Test name vs test result | LR01–LR10 | 10 |
| Historical medication list | HM01–HM10 | 10 |
| Negation scope | NG01–NG10 | 10 |
| Family scope | FS01–FS10 | 10 |
| Overlapping entities | OV01–OV10 | 10 |
| Repeated mentions | RP01–RP10 | 10 |
| Medication strength/form | MF01–MF10 | 10 |
| Qualitative lab results | QL01–QL10 | 10 |
| Cross-category adversarial cases | MX01–MX10 | 10 |
| **Total** | **SD01–MX10** | **100** |

## Current fixture disposition

| Bucket | Cases now | Reason |
|---|---:|---|
| Valid gold fixtures | 0 | No entity-boundary, type, assertion, overlap, or position decision has been adjudicated. |
| Expected-rejection fixtures | 0 | The task contract does not yet define which patterns must be rejected. |
| Out-of-scope fixtures | 0 | Every case exercises a requested task dimension; none is declared out of scope. |
| `NEEDS_ADJUDICATION` queue | 100 | These are the only safe current status; do not use them as labels or scorer goldens. |

### Intended destination after adjudication

| Case families | Candidate destination | Blocking decision |
|---|---|---|
| SD, LR, HM, NG, FS, MF, QL | Valid gold candidate | Type, boundary, assertion, and field policies |
| OV, RP, MX | Valid gold or expected-rejection candidate | Nested/partial-overlap and repeated-mention policy; matching/scorer behavior |

The table is a workflow plan, not a declaration that any case is valid or must
be rejected.

## Required adjudication output

For each ID, an adjudicator must replace `NEEDS_ADJUDICATION` with exact entity
objects (`text`, `type`, `assertions`, optional `candidates`, and code-computed
`position`), cite the newly filled rule in `ANNOTATION_GUIDE.md`, and add the
decision to that guide's adjudication log.  Until then, these cases must not be
used as training labels or scorer goldens.
