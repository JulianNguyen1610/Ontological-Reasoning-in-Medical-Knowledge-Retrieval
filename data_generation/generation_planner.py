"""Curriculum planning for targeted synthetic clinical-note generation."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import random
from typing import Dict, Iterable, List, Optional


CHALLENGE_PROFILES = (
    "basic",
    "negation_scope",
    "historical_scope",
    "family_scope",
    "lab_name_result_pair",
    "repeated_mention",
    "abbreviation_or_typo",
    "mixed_language",
)

PROFILE_SIGNALS = {
    "negation_scope": {"assertions": {"isNegated"}},
    "historical_scope": {"assertions": {"isHistorical"}},
    "family_scope": {"assertions": {"isFamily"}},
    "lab_name_result_pair": {"entity_types": {"TÊN_XÉT_NGHIỆM", "KẾT_QUẢ_XÉT_NGHIỆM"}},
    "repeated_mention": {},
    "abbreviation_or_typo": {},
    "mixed_language": {},
    "basic": {},
}


class ChallengePlanner:
    """Tracks curriculum quotas and applies conservative error-driven boosts."""

    def __init__(self, quotas: Optional[Dict[str, float]] = None, previous_report: Optional[Dict] = None):
        supplied = quotas or {}
        self.quotas = {profile: max(0.0, float(supplied.get(profile, 0.0))) for profile in CHALLENGE_PROFILES}
        if not any(self.quotas.values()):
            self.quotas["basic"] = 1.0
        self.adjustments = self._derive_adjustments(previous_report or {})

    @classmethod
    def from_report_path(cls, quotas: Dict[str, float], report_path: Optional[str]):
        if not report_path:
            return cls(quotas)
        path = Path(report_path)
        if not path.exists():
            return cls(quotas)
        try:
            return cls(quotas, json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return cls(quotas)

    def target_counts(self, total: int) -> Dict[str, int]:
        return self._counts_from_weights(self.quotas, total)

    def effective_target_counts(self, total: int) -> Dict[str, int]:
        """Apply error-driven boosts before converting profile weights to quotas."""
        weights = {
            profile: self.quotas[profile] * self.adjustments.get(profile, 1.0)
            for profile in CHALLENGE_PROFILES
        }
        return self._counts_from_weights(weights, total)

    @staticmethod
    def _counts_from_weights(weights: Dict[str, float], total: int) -> Dict[str, int]:
        total_weight = sum(weights.values()) or 1.0
        raw = {profile: total * weight / total_weight for profile, weight in weights.items()}
        targets = {profile: int(value) for profile, value in raw.items()}
        for profile, _ in sorted(raw.items(), key=lambda item: item[1] - int(item[1]), reverse=True)[: total - sum(targets.values())]:
            targets[profile] += 1
        return targets

    def select_profile(self, generated_counts: Dict[str, int], total_planned: int) -> str:
        targets = self.effective_target_counts(total_planned)
        deficits = {profile: targets[profile] - generated_counts.get(profile, 0) for profile in CHALLENGE_PROFILES}
        missing = [profile for profile, deficit in deficits.items() if deficit > 0]
        if missing:
            highest = max(deficits[profile] for profile in missing)
            choices = [profile for profile in missing if deficits[profile] == highest]
            return random.choice(choices)
        weights = [self.quotas[profile] * self.adjustments.get(profile, 1.0) for profile in CHALLENGE_PROFILES]
        return random.choices(CHALLENGE_PROFILES, weights=weights, k=1)[0]

    def report(self, actual_counts: Dict[str, int], total_planned: int) -> Dict:
        base_targets = self.target_counts(total_planned)
        targets = self.effective_target_counts(total_planned)
        missing = [profile for profile in CHALLENGE_PROFILES if actual_counts.get(profile, 0) < targets[profile]]
        return {
            "base_quota_target": base_targets,
            "quota_target": targets,
            "quota_actual": {profile: actual_counts.get(profile, 0) for profile in CHALLENGE_PROFILES},
            "profiles_missing_quota": missing,
            "error_driven_adjustments": self.adjustments,
        }

    def _derive_adjustments(self, report: Dict) -> Dict[str, float]:
        adjustments = {profile: 1.0 for profile in CHALLENGE_PROFILES}
        structural = report.get("structural_fidelity", report.get("synthetic_clean", {}).get("structural_fidelity", {}))
        missing_types = set(structural.get("missing_entity_types", []))
        missing_assertions = set(structural.get("missing_assertions", []))
        for profile, signals in PROFILE_SIGNALS.items():
            if signals.get("entity_types", set()) & missing_types:
                adjustments[profile] += 1.0
            if signals.get("assertions", set()) & missing_assertions:
                adjustments[profile] += 1.0
        # Accept both evaluator reports and a compact external error-analysis format.
        errors = report.get("error_profiles", report.get("profile_errors", {}))
        if isinstance(errors, dict):
            for profile, count in errors.items():
                if profile in adjustments and isinstance(count, (int, float)) and count > 0:
                    adjustments[profile] += min(float(count) / 10.0, 2.0)
        coverage = report.get("profile_coverage", {})
        if isinstance(coverage, dict):
            targets = coverage.get("quota_target", {})
            actual = coverage.get("quota_actual", {})
            for profile in CHALLENGE_PROFILES:
                deficit = float(targets.get(profile, 0)) - float(actual.get(profile, 0))
                if deficit > 0:
                    adjustments[profile] += min(deficit / 10.0, 1.0)
        # A generic offset failure is most useful for hard contexts with repeated
        # or bilingual surface forms, without trying to rewrite prior data.
        if structural.get("bad_position_count", 0):
            adjustments["repeated_mention"] += 0.5
            adjustments["mixed_language"] += 0.5
        return adjustments
