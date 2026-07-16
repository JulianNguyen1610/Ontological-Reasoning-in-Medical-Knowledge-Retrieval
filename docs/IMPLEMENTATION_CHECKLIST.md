# MedLink-IE v2 — Implementation Checklist

## Gate 0: Specification

- [ ] Freeze task contract.
- [ ] Clone official scorer and pass golden cases.
- [ ] Confirm position convention.
- [ ] Freeze annotation guide v1.
- [ ] Freeze terminology manifest and checksums.

## Gate 1: End-to-end baseline

- [ ] Raw-byte loader.
- [ ] Boundary-map normalization.
- [ ] Section/list segmentation.
- [ ] Drug and lab deterministic proposal rules.
- [ ] Exact grounding with repeated-mention handling.
- [ ] Simple type/assertion rules.
- [ ] Alias + BM25 linker.
- [ ] JSON and zip validator.
- [ ] One-command inference.

## Gate 2: Evaluation foundation

- [ ] Human-reviewed gold dev set.
- [ ] Grouped train/dev/test split.
- [ ] Challenge set.
- [ ] Error taxonomy dashboard/report.
- [ ] Baseline score and latency report.

## Gate 3: Neural extraction

- [ ] Benchmark span/type candidates.
- [ ] Save out-of-fold logits.
- [ ] Fit calibrators.
- [ ] Tune score-aware thresholds.
- [ ] Add source fusion.

## Gate 4: Assertions

- [ ] Section/list propagation.
- [ ] Negation scope.
- [ ] Historical scope.
- [ ] Family scope.
- [ ] Per-label calibration.

## Gate 5: Linking

- [ ] Prepare terminology indexes.
- [ ] Medication structured parser.
- [ ] Lab internal relation parser.
- [ ] Character n-gram retrieval.
- [ ] Dense bi-encoder retrieval.
- [ ] Cross-encoder reranker.
- [ ] Hard-negative mining.
- [ ] Candidate-set expected-Jaccard decoder.

## Gate 6: Advanced constraints

- [ ] Gated ontology rules.
- [ ] Joint decoder.
- [ ] Global conflict resolver.
- [ ] Full ablation with latency.

## Gate 7: Reproduction drill

- [ ] Offline container build.
- [ ] Network-disabled test.
- [ ] All artifact checksums recorded.
- [ ] Clean-machine reproduction by another team member.
- [ ] Final README and troubleshooting.
- [ ] Pre-submit output.zip validation.
