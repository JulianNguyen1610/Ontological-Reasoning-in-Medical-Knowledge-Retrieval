"""Deterministic curation for generated medical annotation data.

Raw generation batches are treated as immutable input.  This module produces
clean training views and an auditable rejection trail without calling an LLM.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from data_generation.local_validator import LocalSampleValidator


TOKEN_PATTERN = re.compile(r"\b\w+\b", re.UNICODE)
MODERN_PROFILES = frozenset(
    {
        "repeated_mention",
        "abbreviation_or_typo",
        "mixed_language",
        "lab_name_result_pair",
    }
)


@dataclass
class CuratedCandidate:
    sample: Dict[str, Any]
    source_file: str
    source_index: int
    validation: Dict[str, Any]
    quality_score: int = 0
    flags: List[str] = field(default_factory=list)

    @property
    def profile(self) -> str:
        return str(self.sample.get("challenge_profile", "basic"))

    @property
    def text(self) -> str:
        return str(self.sample.get("text", ""))


class GeneratedDataCurator:
    """Validate, deduplicate, and split local generated-data batches."""

    def __init__(self, assertion_cues: Dict[str, List[str]]):
        self.validator = LocalSampleValidator(assertion_cues)

    def curate(
        self,
        raw_dir: Path,
        output_dir: Path,
        hard_duplicate_threshold: float = 0.72,
        soft_duplicate_threshold: float = 0.62,
        validation_ratio: float = 0.15,
    ) -> Dict[str, Any]:
        if not 0.0 <= soft_duplicate_threshold <= hard_duplicate_threshold <= 1.0:
            raise ValueError("Require 0 <= soft threshold <= hard threshold <= 1.")
        if not 0.0 < validation_ratio < 1.0:
            raise ValueError("validation_ratio must be between 0 and 1.")

        candidates, source_counts = self._load_candidates(raw_dir)
        rejected: List[Dict[str, Any]] = []
        valid_candidates: List[CuratedCandidate] = []
        for candidate in candidates:
            if not candidate.validation["valid"]:
                rejected.append(self._rejection(candidate, "validation_failed"))
            else:
                valid_candidates.append(candidate)

        unique_candidates = self._reject_exact_duplicates(valid_candidates, rejected)
        retained, soft_pairs = self._deduplicate_near_templates(
            unique_candidates,
            rejected,
            hard_duplicate_threshold,
            soft_duplicate_threshold,
        )

        gold = [candidate for candidate in retained if candidate.profile in MODERN_PROFILES]
        standard = [candidate for candidate in retained if candidate.profile not in MODERN_PROFILES]
        gold_train, gold_validation = self._split_gold(gold, validation_ratio)

        output_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(output_dir / "gold.json", [item.sample for item in gold])
        self._write_json(output_dir / "gold_train.json", [item.sample for item in gold_train])
        self._write_json(output_dir / "gold_validation.json", [item.sample for item in gold_validation])
        self._write_json(output_dir / "standard.json", [item.sample for item in standard])
        self._write_json(output_dir / "rejected.json", rejected)
        provenance = {
            "gold": [self._provenance_record(item) for item in gold],
            "gold_train": [self._provenance_record(item) for item in gold_train],
            "gold_validation": [self._provenance_record(item) for item in gold_validation],
            "standard": [self._provenance_record(item) for item in standard],
        }
        self._write_json(output_dir / "provenance.json", provenance)

        report = {
            "format_version": 1,
            "source_dir": str(raw_dir),
            "thresholds": {
                "hard_duplicate": hard_duplicate_threshold,
                "soft_duplicate": soft_duplicate_threshold,
                "validation_ratio": validation_ratio,
            },
            "source_counts": dict(sorted(source_counts.items())),
            "counts": {
                "input": len(candidates),
                "gold": len(gold),
                "gold_train": len(gold_train),
                "gold_validation": len(gold_validation),
                "standard": len(standard),
                "rejected": len(rejected),
            },
            "rejection_reasons": dict(Counter(item["reason"] for item in rejected)),
            "soft_near_duplicate_pairs": soft_pairs,
        }
        manifest = {
            "format_version": 1,
            "description": "Curated views of immutable raw generated batches.",
            "datasets": {
                "gold": "gold.json",
                "gold_train": "gold_train.json",
                "gold_validation": "gold_validation.json",
                "standard": "standard.json",
                "rejected": "rejected.json",
            },
            "report": "curation_report.json",
            "provenance": "provenance.json",
            "counts": report["counts"],
        }
        self._write_json(output_dir / "curation_report.json", report)
        self._write_json(output_dir / "manifest.json", manifest)
        return report

    def _load_candidates(self, raw_dir: Path) -> Tuple[List[CuratedCandidate], Counter]:
        candidates: List[CuratedCandidate] = []
        source_counts: Counter = Counter()
        for path in sorted(raw_dir.glob("training_data_*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError(f"Expected a JSON list in {path}")
            source_counts[path.name] = len(payload)
            for index, sample in enumerate(payload):
                if not isinstance(sample, dict):
                    sample = {"text": "", "entities": []}
                text = sample.get("text", "")
                entities = sample.get("entities", [])
                profile = sample.get("challenge_profile", "basic")
                validation = self.validator.validate(text, entities, profile)
                candidate = CuratedCandidate(sample, path.name, index, validation)
                candidate.quality_score = self._quality_score(candidate)
                candidates.append(candidate)
        return candidates, source_counts

    @staticmethod
    def _quality_score(candidate: CuratedCandidate) -> int:
        score = 100
        if candidate.profile in MODERN_PROFILES:
            score += 20
        if any(entity.get("assertions") for entity in candidate.sample.get("entities", [])):
            score += 5
        if candidate.profile != "basic":
            score += 5
        return score

    def _reject_exact_duplicates(
        self, candidates: Iterable[CuratedCandidate], rejected: List[Dict[str, Any]]
    ) -> List[CuratedCandidate]:
        by_text: Dict[str, List[CuratedCandidate]] = defaultdict(list)
        for candidate in candidates:
            by_text[self._normalized_text(candidate.text)].append(candidate)
        retained: List[CuratedCandidate] = []
        for duplicates in by_text.values():
            winner = self._best_candidate(duplicates)
            retained.append(winner)
            for candidate in duplicates:
                if candidate is not winner:
                    rejected.append(self._rejection(candidate, "exact_duplicate"))
        return retained

    def _deduplicate_near_templates(
        self,
        candidates: List[CuratedCandidate],
        rejected: List[Dict[str, Any]],
        hard_threshold: float,
        soft_threshold: float,
    ) -> Tuple[List[CuratedCandidate], List[Dict[str, Any]]]:
        parent = list(range(len(candidates)))
        soft_pairs: List[Dict[str, Any]] = []

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left in range(len(candidates)):
            for right in range(left + 1, len(candidates)):
                similarity = self._jaccard(candidates[left].text, candidates[right].text)
                if similarity >= hard_threshold:
                    union(left, right)
                elif similarity >= soft_threshold:
                    candidates[left].flags.append("soft_near_duplicate")
                    candidates[right].flags.append("soft_near_duplicate")
                    soft_pairs.append(self._pair_record(candidates[left], candidates[right], similarity))

        components: Dict[int, List[CuratedCandidate]] = defaultdict(list)
        for index, candidate in enumerate(candidates):
            components[find(index)].append(candidate)

        retained: List[CuratedCandidate] = []
        for component in components.values():
            winner = self._best_candidate(component)
            retained.append(winner)
            for candidate in component:
                if candidate is not winner:
                    rejected.append(self._rejection(candidate, "hard_near_duplicate"))
        return retained, soft_pairs

    @staticmethod
    def _best_candidate(candidates: Iterable[CuratedCandidate]) -> CuratedCandidate:
        return max(
            candidates,
            key=lambda item: (item.quality_score, item.source_file, -item.source_index),
        )

    @staticmethod
    def _normalized_text(text: str) -> str:
        return " ".join(text.casefold().split())

    @staticmethod
    def _jaccard(left: str, right: str) -> float:
        left_tokens = set(TOKEN_PATTERN.findall(left.casefold()))
        right_tokens = set(TOKEN_PATTERN.findall(right.casefold()))
        if not left_tokens and not right_tokens:
            return 1.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    @staticmethod
    def _split_gold(
        gold: List[CuratedCandidate], validation_ratio: float
    ) -> Tuple[List[CuratedCandidate], List[CuratedCandidate]]:
        ordered = sorted(
            gold,
            key=lambda item: hashlib.sha256(item.text.encode("utf-8")).hexdigest(),
        )
        validation_count = max(1, round(len(ordered) * validation_ratio)) if ordered else 0
        return ordered[validation_count:], ordered[:validation_count]

    @staticmethod
    def _pair_record(
        left: CuratedCandidate, right: CuratedCandidate, similarity: float
    ) -> Dict[str, Any]:
        return {
            "similarity": round(similarity, 4),
            "left": {"source_file": left.source_file, "source_index": left.source_index},
            "right": {"source_file": right.source_file, "source_index": right.source_index},
        }

    @staticmethod
    def _rejection(candidate: CuratedCandidate, reason: str) -> Dict[str, Any]:
        return {
            "reason": reason,
            "source_file": candidate.source_file,
            "source_index": candidate.source_index,
            "quality_score": candidate.quality_score,
            "validation_errors": candidate.validation["errors"],
            "validation_warnings": candidate.validation["warnings"],
            "sample": candidate.sample,
        }

    @staticmethod
    def _provenance_record(candidate: CuratedCandidate) -> Dict[str, Any]:
        return {
            "source_file": candidate.source_file,
            "source_index": candidate.source_index,
            "scenario_id": candidate.sample.get("scenario_id"),
            "challenge_profile": candidate.profile,
            "quality_score": candidate.quality_score,
            "quality_flags": sorted(set(candidate.flags)),
        }

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
