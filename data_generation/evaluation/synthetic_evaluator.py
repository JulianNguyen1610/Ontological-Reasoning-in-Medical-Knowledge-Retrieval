import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from data_generation.config import VALID_ASSERTIONS, VALID_ENTITY_TYPES


COMMON_ABBREVIATIONS = {"BN", "NV", "TS", "CD", "KQXN", "HA", "HR", "RR", "SpO2"}
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+84|0)(?:\d[\s.-]?){8,10}\d(?!\d)")
ID_PATTERN = re.compile(r"(?<!\d)\d{9}(?:\d{3})?(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
DOB_PATTERN = re.compile(
    r"\b(?:0?[1-9]|[12]\d|3[01])[/-](?:0?[1-9]|1[0-2])[/-](?:19\d{2}|20\d{2})\b"
)
ADDRESS_PATTERN = re.compile(
    r"\b(?:số nhà|đường|phường|quận|hẻm|ngõ|ấp|xã|thôn)\b",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"\b\w+\b", re.UNICODE)
PUNCT_PATTERN = re.compile(r"[.,;:!?()\[\]{}\-\/]")

SPLIT_ALIASES = {
    "clean": "synthetic_clean",
    "hard": "synthetic_hard",
    "human": "human_reviewed",
    "synthetic_clean": "synthetic_clean",
    "synthetic_hard": "synthetic_hard",
    "human_reviewed": "human_reviewed",
}


class SyntheticDataEvaluator:
    """Split-aware synthetic data evaluation framework."""

    def load_samples(self, input_path: str | Path) -> List[Dict]:
        path = Path(input_path)
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("JSON input must be a list of samples")
            return data
        if path.suffix.lower() == ".jsonl":
            samples = []
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        samples.append(json.loads(line))
            return samples
        raise ValueError(f"Unsupported input format: {path.suffix}")

    def load_manifest(self, manifest_path: str | Path) -> Dict[str, str]:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        splits = manifest.get("splits", {})
        if not isinstance(splits, dict):
            raise ValueError("Manifest must contain a 'splits' object")
        normalized = {}
        for key, value in splits.items():
            if key not in SPLIT_ALIASES:
                continue
            if not isinstance(value, str):
                continue
            normalized[SPLIT_ALIASES[key]] = value
        return normalized

    def evaluate_file(self, input_path: str | Path, output_path: str | Path | None = None) -> Dict:
        samples = self.load_samples(input_path)
        report = self.evaluate_samples(samples, input_path=str(input_path))
        if output_path is not None:
            self.save_report(report, output_path)
        return report

    def evaluate_samples(self, samples: List[Dict], input_path: str = "") -> Dict:
        split_report = self._evaluate_split(samples, split_name="synthetic_clean", input_path=input_path)
        report = {
            "synthetic_clean": split_report,
            "synthetic_hard": self._empty_split_report("synthetic_hard"),
            "human_reviewed": self._empty_split_report("human_reviewed"),
            "cross_split_analysis": self._build_cross_split_analysis(
                split_report,
                self._empty_split_report("synthetic_hard"),
                self._empty_split_report("human_reviewed"),
            ),
            "downstream_utility": self._build_downstream_utility(status="proxy_only"),
            "final_recommendation": self._build_final_recommendation(
                split_report,
                self._empty_split_report("synthetic_hard"),
                self._empty_split_report("human_reviewed"),
            ),
        }
        return report

    def evaluate_splits(
        self,
        split_paths: Dict[str, str | Path],
        output_path: str | Path | None = None,
    ) -> Dict:
        resolved = self._normalize_split_paths(split_paths)
        split_reports = {
            split_name: self._evaluate_split(
                self.load_samples(path),
                split_name=split_name,
                input_path=str(path),
            )
            for split_name, path in resolved.items()
        }

        clean_report = split_reports.get("synthetic_clean", self._empty_split_report("synthetic_clean"))
        hard_report = split_reports.get("synthetic_hard", self._empty_split_report("synthetic_hard"))
        human_report = split_reports.get("human_reviewed", self._empty_split_report("human_reviewed"))

        report = {
            "synthetic_clean": clean_report,
            "synthetic_hard": hard_report,
            "human_reviewed": human_report,
            "cross_split_analysis": self._build_cross_split_analysis(clean_report, hard_report, human_report),
            "downstream_utility": self._build_downstream_utility(status="proxy_only"),
            "final_recommendation": self._build_final_recommendation(clean_report, hard_report, human_report),
        }
        if output_path is not None:
            self.save_report(report, output_path)
        return report

    def evaluate_splits_from_samples(
        self,
        split_samples: Dict[str, List[Dict]],
        output_path: str | Path | None = None,
    ) -> Dict:
        normalized = {
            SPLIT_ALIASES[key]: value
            for key, value in split_samples.items()
            if key in SPLIT_ALIASES
        }
        clean_report = self._evaluate_split(
            normalized.get("synthetic_clean", []),
            split_name="synthetic_clean",
        )
        hard_report = self._evaluate_split(
            normalized.get("synthetic_hard", []),
            split_name="synthetic_hard",
        )
        human_report = self._evaluate_split(
            normalized.get("human_reviewed", []),
            split_name="human_reviewed",
        )
        report = {
            "synthetic_clean": clean_report,
            "synthetic_hard": hard_report,
            "human_reviewed": human_report,
            "cross_split_analysis": self._build_cross_split_analysis(clean_report, hard_report, human_report),
            "downstream_utility": self._build_downstream_utility(status="proxy_only"),
            "final_recommendation": self._build_final_recommendation(clean_report, hard_report, human_report),
        }
        if output_path is not None:
            self.save_report(report, output_path)
        return report

    def evaluate_manifest(self, manifest_path: str | Path, output_path: str | Path | None = None) -> Dict:
        split_paths = self.load_manifest(manifest_path)
        return self.evaluate_splits(split_paths, output_path=output_path)

    def save_report(self, report: Dict, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)

    def _normalize_split_paths(self, split_paths: Dict[str, str | Path]) -> Dict[str, Path]:
        normalized = {}
        for key, value in split_paths.items():
            alias = SPLIT_ALIASES.get(key)
            if alias is None or value is None:
                continue
            normalized[alias] = Path(value)
        return normalized

    def _evaluate_split(self, samples: List[Dict], split_name: str, input_path: str = "") -> Dict:
        structural = self._evaluate_structural_fidelity(samples)
        realism = self._evaluate_text_realism(samples)
        privacy = self._evaluate_privacy(samples)
        utility_proxy = self._evaluate_utility_proxy(structural, realism, privacy)
        quality_gate = self._build_split_quality_gate(split_name, structural, utility_proxy)
        return {
            "input_path": input_path,
            "split_name": split_name,
            "structural_fidelity": structural,
            "text_realism": realism,
            "privacy": privacy,
            "utility_proxy": utility_proxy,
            "quality_gate": quality_gate,
        }

    def _empty_split_report(self, split_name: str) -> Dict:
        return self._evaluate_split([], split_name=split_name, input_path="")

    def _evaluate_structural_fidelity(self, samples: List[Dict]) -> Dict:
        entity_type_distribution = {entity_type: 0 for entity_type in VALID_ENTITY_TYPES}
        assertion_distribution = {assertion: 0 for assertion in VALID_ASSERTIONS}
        total_entities = 0
        empty_entity_samples = 0
        bad_position_count = 0
        duplicate_span_count = 0

        for sample in samples:
            text = sample.get("text", "") or ""
            entities = sample.get("entities", []) or []
            total_entities += len(entities)
            if not entities:
                empty_entity_samples += 1

            seen_spans = set()
            for entity in entities:
                entity_type = entity.get("type")
                if entity_type in entity_type_distribution:
                    entity_type_distribution[entity_type] += 1

                for assertion in entity.get("assertions", []):
                    if assertion in assertion_distribution:
                        assertion_distribution[assertion] += 1

                if not self._has_valid_position(text, entity):
                    bad_position_count += 1

                position = entity.get("position", [])
                if len(position) == 2:
                    span_key = (position[0], position[1], entity_type)
                    if span_key in seen_spans:
                        duplicate_span_count += 1
                    else:
                        seen_spans.add(span_key)

        total_samples = len(samples)
        return {
            "total_samples": total_samples,
            "empty_entity_samples": empty_entity_samples,
            "total_entities": total_entities,
            "avg_entities_per_sample": (total_entities / total_samples) if total_samples else 0.0,
            "entity_type_distribution": entity_type_distribution,
            "assertion_distribution": assertion_distribution,
            "bad_position_count": bad_position_count,
            "bad_position_rate": (bad_position_count / total_entities) if total_entities else 0.0,
            "duplicate_span_count": duplicate_span_count,
            "missing_entity_types": [
                entity_type for entity_type, count in entity_type_distribution.items() if count == 0
            ],
            "missing_assertions": [
                assertion for assertion, count in assertion_distribution.items() if count == 0
            ],
        }

    def _evaluate_text_realism(self, samples: List[Dict]) -> Dict:
        texts = [(sample.get("text", "") or "") for sample in samples]
        lengths = [len(text) for text in texts]
        tokens = []
        abbreviation_count = 0
        punctuation_count = 0
        repeated_ngram_hits = 0
        total_ngram_windows = 0

        for text in texts:
            sample_tokens = TOKEN_PATTERN.findall(text)
            tokens.extend(sample_tokens)
            punctuation_count += len(PUNCT_PATTERN.findall(text))
            abbreviation_count += sum(1 for token in sample_tokens if token in COMMON_ABBREVIATIONS)

            lower_tokens = [token.lower() for token in sample_tokens]
            for n in (2, 3):
                if len(lower_tokens) >= n:
                    ngrams = [tuple(lower_tokens[i:i + n]) for i in range(len(lower_tokens) - n + 1)]
                    total_ngram_windows += len(ngrams)
                    counts = Counter(ngrams)
                    repeated_ngram_hits += sum(count - 1 for count in counts.values() if count > 1)

        total_tokens = len(tokens)
        unique_tokens = len({token.lower() for token in tokens})
        total_chars = sum(lengths)
        return {
            "avg_text_length": (sum(lengths) / len(lengths)) if lengths else 0.0,
            "lexical_diversity": (unique_tokens / total_tokens) if total_tokens else 0.0,
            "repetition_rate": (repeated_ngram_hits / total_ngram_windows) if total_ngram_windows else 0.0,
            "abbreviation_rate": (abbreviation_count / total_tokens) if total_tokens else 0.0,
            "punctuation_density": (punctuation_count / total_chars) if total_chars else 0.0,
        }

    def _evaluate_privacy(self, samples: List[Dict]) -> Dict:
        phone_like_count = 0
        id_like_count = 0
        email_count = 0
        date_of_birth_like_count = 0
        address_like_count = 0

        for sample in samples:
            text = sample.get("text", "") or ""
            phone_like_count += len(PHONE_PATTERN.findall(text))
            id_like_count += len(ID_PATTERN.findall(text))
            email_count += len(EMAIL_PATTERN.findall(text))
            date_of_birth_like_count += len(DOB_PATTERN.findall(text))
            address_like_count += len(ADDRESS_PATTERN.findall(text))

        privacy_warning_count = (
            phone_like_count
            + id_like_count
            + email_count
            + date_of_birth_like_count
            + address_like_count
        )
        return {
            "phone_like_count": phone_like_count,
            "id_like_count": id_like_count,
            "email_count": email_count,
            "date_of_birth_like_count": date_of_birth_like_count,
            "address_like_count": address_like_count,
            "privacy_warning_count": privacy_warning_count,
        }

    @staticmethod
    def _evaluate_utility_proxy(structural: Dict, realism: Dict, privacy: Dict) -> Dict:
        if structural["total_samples"] == 0:
            return {
                "score": 0.5,
                "components": {
                    "structural_score": 0.5,
                    "realism_penalty": 0.0,
                    "privacy_penalty": 0.0,
                },
            }
        structural_score = max(
            0.0,
            1.0
            - structural["bad_position_rate"]
            - min(0.5, structural["empty_entity_samples"] / max(1, structural["total_samples"])),
        )
        realism_penalty = min(0.4, realism["repetition_rate"])
        privacy_penalty = min(0.5, privacy["privacy_warning_count"] / max(1, structural["total_samples"]))
        overall_score = max(0.0, min(1.0, structural_score - realism_penalty - privacy_penalty))
        return {
            "score": overall_score,
            "components": {
                "structural_score": structural_score,
                "realism_penalty": realism_penalty,
                "privacy_penalty": privacy_penalty,
            },
        }

    @staticmethod
    def _build_downstream_utility(status: str) -> Dict:
        return {
            "status": status,
            "train_recipe": {
                "synthetic_only": "Train span extractor/linker/assertion heads on synthetic_clean + synthetic_hard.",
                "synthetic_plus_reviewed": "Fine-tune on synthetic data, then calibrate and evaluate with human_reviewed.",
            },
            "expected_metrics": [
                "span_f1",
                "assertion_macro_f1",
                "candidate_recall_at_k",
            ],
            "results": None,
        }

    def _build_split_quality_gate(self, split_name: str, structural: Dict, utility_proxy: Dict) -> Dict:
        passed = True
        warnings = []
        if split_name == "synthetic_clean" and structural["bad_position_rate"] > 0:
            passed = False
            warnings.append("Clean split has non-zero bad positions.")
        if split_name == "synthetic_hard":
            if structural["avg_entities_per_sample"] == 0:
                passed = False
                warnings.append("Hard split coverage collapsed to zero entities.")
            if utility_proxy["score"] < 0.3:
                warnings.append("Hard split utility proxy is low.")
        if split_name == "human_reviewed":
            if structural["total_samples"] == 0:
                warnings.append("Human-reviewed split is missing; conclusions are weaker.")
        if structural["missing_entity_types"]:
            warnings.append(f"Missing entity types: {', '.join(structural['missing_entity_types'])}")
        if structural["missing_assertions"]:
            warnings.append(f"Missing assertions: {', '.join(structural['missing_assertions'])}")
        return {"passed": passed, "warnings": warnings}

    def _build_cross_split_analysis(self, clean_report: Dict, hard_report: Dict, human_report: Dict) -> Dict:
        clean_struct = clean_report["structural_fidelity"]
        hard_struct = hard_report["structural_fidelity"]

        clean_vs_hard_entity_drop = (
            clean_struct["avg_entities_per_sample"] - hard_struct["avg_entities_per_sample"]
        )
        clean_total_asserts = sum(clean_struct["assertion_distribution"].values())
        hard_total_asserts = sum(hard_struct["assertion_distribution"].values())
        clean_assert_rate = (clean_total_asserts / max(1, clean_struct["total_entities"]))
        hard_assert_rate = (hard_total_asserts / max(1, hard_struct["total_entities"]))

        priority_note = (
            "Prioritize human_reviewed split for go/no-go decisions and threshold tuning."
            if human_report["structural_fidelity"]["total_samples"] > 0
            else "Human-reviewed split missing; treat synthetic-only conclusions as provisional."
        )
        return {
            "clean_vs_hard_entity_drop": clean_vs_hard_entity_drop,
            "clean_vs_hard_assertion_shift": hard_assert_rate - clean_assert_rate,
            "human_split_priority_note": priority_note,
        }

    def _build_final_recommendation(self, clean_report: Dict, hard_report: Dict, human_report: Dict) -> Dict:
        blocking_issues = []
        warnings = []

        if clean_report["structural_fidelity"]["total_samples"] == 0:
            blocking_issues.append("synthetic_clean split is missing or empty.")
        if clean_report["structural_fidelity"]["bad_position_rate"] > 0:
            blocking_issues.append("synthetic_clean has bad positions and should be fixed before training.")
        if clean_report["structural_fidelity"]["empty_entity_samples"] > 0:
            blocking_issues.append("synthetic_clean contains empty-entity samples.")
        if hard_report["structural_fidelity"]["total_samples"] > 0:
            if hard_report["structural_fidelity"]["avg_entities_per_sample"] == 0:
                blocking_issues.append("synthetic_hard coverage collapsed to zero entities.")
            elif (
                hard_report["structural_fidelity"]["avg_entities_per_sample"]
                < 0.5 * max(1e-8, clean_report["structural_fidelity"]["avg_entities_per_sample"])
            ):
                warnings.append("synthetic_hard is much sparser than synthetic_clean.")
        if hard_report["structural_fidelity"]["bad_position_rate"] > clean_report["structural_fidelity"]["bad_position_rate"]:
            warnings.append("synthetic_hard has worse span quality than synthetic_clean.")
        if human_report["structural_fidelity"]["total_samples"] == 0:
            warnings.append("human_reviewed split missing; utility conclusions are provisional.")
        if human_report["privacy"]["privacy_warning_count"] > 0:
            warnings.append("human_reviewed split contains privacy-like patterns; inspect before reuse.")

        return {
            "ready_for_training": len(blocking_issues) == 0,
            "blocking_issues": blocking_issues,
            "warnings": warnings,
        }

    @staticmethod
    def _has_valid_position(text: str, entity: Dict) -> bool:
        position = entity.get("position", [])
        if len(position) != 2:
            return False
        start, end = position
        return 0 <= start < end <= len(text) and text[start:end] == entity.get("text", "")
