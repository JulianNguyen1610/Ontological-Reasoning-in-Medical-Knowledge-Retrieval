"""Synthetic clinical-data pipeline with curriculum, hybrid validation and resume."""
import hashlib
import json
import logging
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional

from tqdm import tqdm

from data_generation.config import GenerationConfig, VALID_ASSERTIONS, VALID_ENTITY_TYPES
from data_generation.generation_planner import ChallengePlanner
from data_generation.generators.critic_agent import CriticAgent
from data_generation.generators.style_director import StyleDirector
from data_generation.generators.text_generator import GeneratedSample, TextGenerator
from data_generation.generators.topic_extractor import TopicExtractor
from data_generation.local_validator import LocalSampleValidator
from data_generation.utils.cleanup import clean_sample

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

logger = logging.getLogger(__name__)


class DataGenerationPipeline:
    """Generate notes while treating span correctness as a non-negotiable contract."""

    def __init__(self, config: GenerationConfig, llm_client, output_dir: Path, seeds_dir: Path):
        self.config = config
        self.llm = llm_client
        self.output_dir = Path(output_dir)
        self.seeds_dir = Path(seeds_dir)
        import datetime
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.topic_extractor = TopicExtractor(self.seeds_dir)
        self.style_director = StyleDirector()
        self.text_generator = TextGenerator(llm_client)
        self.critic = CriticAgent(llm_client)
        self.local_validator = LocalSampleValidator(self.text_generator.assertion_cues)
        self.planner = ChallengePlanner.from_report_path(
            config.challenge_profile_quotas, config.previous_evaluation_report
        )
        self.stats = self._initial_stats()
        self._completed_attempts = 0
        self._seen_text_hashes = set()

    @staticmethod
    def _initial_stats() -> Dict:
        return {
            "total_generated": 0,
            "valid_samples": 0,
            "invalid_samples": 0,
            "retry_count": 0,
            "entity_type_distribution": {entity_type: 0 for entity_type in VALID_ENTITY_TYPES},
            "assertion_distribution": {assertion: 0 for assertion in VALID_ASSERTIONS},
            "profile_coverage": {},
            "validation_routing": {
                "local_validator_passed": 0,
                "local_validator_rejected": 0,
                "local_validator_warnings": 0,
                "critic_called": 0,
                "critic_rejected": 0,
                "critic_fixed": 0,
            },
            "resume": {"resumed": False, "checkpoint": None, "completed_attempts": 0},
        }

    def run(self, num_samples: int = None) -> List[Dict]:
        total_planned = num_samples or self.config.num_samples
        samples = self._load_resume_checkpoint() if self.config.resume_from_checkpoint else []
        attempt_limit = self.config.max_total_attempts or total_planned * 3
        logger.info(
            "Starting generation: valid_target=%s, max_attempts=%s, resumed_samples=%s",
            total_planned,
            attempt_limit,
            len(samples),
        )

        while len(samples) < total_planned and self._completed_attempts < attempt_limit:
            sample = self._generate_single_sample(total_planned)
            if sample and self._sample_hash(sample) not in self._seen_text_hashes:
                samples.append(sample)
                self._seen_text_hashes.add(self._sample_hash(sample))
                self.stats["valid_samples"] += 1
            else:
                self.stats["invalid_samples"] += 1
            self.stats["total_generated"] += 1
            self._completed_attempts += 1
            if self.config.checkpoint_interval and self._completed_attempts % self.config.checkpoint_interval == 0:
                self._save_checkpoint(samples, total_planned)

        self.stats["generation_target"] = {
            "valid_samples": total_planned,
            "max_total_attempts": attempt_limit,
            "target_reached": len(samples) >= total_planned,
        }
        self.stats["profile_coverage"] = self.planner.report(
            self.stats["profile_coverage"], total_planned
        )
        if hasattr(self.llm, "retry_metrics"):
            self.stats["api_retry"] = self.llm.retry_metrics
        self._save_final_output(samples)
        self._save_stats()
        logger.info("Generation complete: valid=%s", len(samples))
        return samples

    def _generate_single_sample(self, total_planned: Optional[int] = None) -> Optional[Dict]:
        total_planned = total_planned or self.config.num_samples
        for attempt in range(self.config.max_retries):
            try:
                profile = self.planner.select_profile(self.stats["profile_coverage"], total_planned)
                scenario = self.topic_extractor.extract_topic(self._select_complexity(), profile)
                sample = self.text_generator.generate_sample(scenario, self.style_director)
                if not sample or len(sample.entities) < self.text_generator.last_expected_entity_count:
                    self.stats["retry_count"] += 1
                    continue

                entities = [self._entity_to_dict(entity) for entity in sample.entities]
                local = self.local_validator.validate(
                    sample.text, entities, scenario.challenge_profile
                )
                routing = self.stats["validation_routing"]
                if not local["valid"]:
                    routing["local_validator_rejected"] += 1
                    self.stats["retry_count"] += 1
                    continue
                routing["local_validator_passed"] += 1
                if local["warnings"]:
                    routing["local_validator_warnings"] += 1

                if self._should_call_critic(scenario.challenge_profile, entities, local["warnings"]):
                    routing["critic_called"] += 1
                    critic_result = self.critic.review_sample(sample.text, entities)
                    if not critic_result.is_valid:
                        routing["critic_rejected"] += 1
                        fixed_text, fixed_entities = self.critic.auto_fix(sample.text, entities, critic_result.errors)
                        recheck = self.critic.review_sample(fixed_text, fixed_entities)
                        if not recheck.is_valid:
                            self.stats["retry_count"] += 1
                            continue
                        if not self.local_validator.validate(
                            fixed_text, fixed_entities, scenario.challenge_profile
                        )["valid"]:
                            self.stats["retry_count"] += 1
                            continue
                        sample.text = fixed_text
                        sample.entities = [self._dict_to_entity(entity) for entity in fixed_entities]
                        routing["critic_fixed"] += 1

                cleaned = clean_sample(self._sample_to_dict(sample))
                if len(cleaned["entities"]) != self.text_generator.last_expected_entity_count:
                    self.stats["retry_count"] += 1
                    continue
                if not self.local_validator.validate(
                    cleaned["text"], cleaned["entities"], scenario.challenge_profile
                )["valid"]:
                    self.stats["retry_count"] += 1
                    continue
                cleaned["challenge_profile"] = scenario.challenge_profile
                self._update_stats(cleaned)
                return cleaned
            except Exception as error:
                logger.warning("Sample generation failed (attempt %s/%s): %s", attempt + 1, self.config.max_retries, error)
                self.stats["retry_count"] += 1
        return None

    def _should_call_critic(self, profile: str, entities: List[Dict], warnings: List[str]) -> bool:
        if self.config.force_critic_all or warnings:
            return True
        risky_profiles = {"negation_scope", "historical_scope", "family_scope", "lab_name_result_pair", "repeated_mention", "mixed_language"}
        return profile in risky_profiles or any(entity.get("assertions") for entity in entities)

    def _select_complexity(self) -> str:
        complexities = list(self.config.scenario_distribution.keys())
        return random.choices(complexities, weights=list(self.config.scenario_distribution.values()), k=1)[0]

    @staticmethod
    def _entity_to_dict(entity) -> Dict:
        return {"text": entity.text, "type": entity.type, "assertions": entity.assertions, "candidates": entity.candidates, "position": list(entity.position)}

    @staticmethod
    def _dict_to_entity(data: Dict):
        from data_generation.generators.text_generator import EntityAnnotation
        return EntityAnnotation(data["text"], data["type"], data["assertions"], data["candidates"], tuple(data["position"]))

    def _sample_to_dict(self, sample: GeneratedSample) -> Dict:
        return {"text": sample.text, "entities": [self._entity_to_dict(entity) for entity in sample.entities], "scenario_id": sample.scenario_id}

    def _update_stats(self, sample: Dict) -> None:
        profile = sample.get("challenge_profile", "basic")
        self.stats["profile_coverage"][profile] = self.stats["profile_coverage"].get(profile, 0) + 1
        for entity in sample["entities"]:
            if entity["type"] in self.stats["entity_type_distribution"]:
                self.stats["entity_type_distribution"][entity["type"]] += 1
            for assertion in entity.get("assertions", []):
                if assertion in self.stats["assertion_distribution"]:
                    self.stats["assertion_distribution"][assertion] += 1

    @staticmethod
    def _sample_hash(sample: Dict) -> str:
        return hashlib.sha256(sample.get("text", "").encode("utf-8")).hexdigest()

    def _load_resume_checkpoint(self) -> List[Dict]:
        path = Path(self.config.resume_from_checkpoint)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            samples = payload
        else:
            samples = payload.get("samples", [])
            self.timestamp = payload.get("run_id", self.timestamp)
            self._completed_attempts = int(payload.get("completed_attempts", len(samples)))
            saved_stats = payload.get("stats")
            if isinstance(saved_stats, dict):
                self.stats.update(saved_stats)
        self._seen_text_hashes = {self._sample_hash(sample) for sample in samples}
        self.stats["resume"] = {"resumed": True, "checkpoint": str(path), "completed_attempts": self._completed_attempts}
        logger.info("Resuming from %s at attempt %s", path, self._completed_attempts)
        return samples

    def _save_checkpoint(self, samples: List[Dict], total_planned: int) -> Path:
        checkpoint_dir = self.output_dir / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        path = checkpoint_dir / f"checkpoint_{self.timestamp}_{self._completed_attempts}.json"
        payload = {"format_version": 2, "run_id": self.timestamp, "completed_attempts": self._completed_attempts, "total_planned": total_planned, "samples": samples, "stats": self.stats}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Checkpoint saved: %s", path)
        return path

    def _unique_output_path(self, stem: str, suffix: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        candidate = self.output_dir / f"{stem}{suffix}"
        index = 1
        while candidate.exists():
            candidate = self.output_dir / f"{stem}_{index}{suffix}"
            index += 1
        return candidate

    def _save_final_output(self, samples: List[Dict]) -> None:
        stem = f"training_data_{self.timestamp}"
        jsonl_path = self._unique_output_path(stem, ".jsonl")
        json_path = self._unique_output_path(stem, ".json")
        jsonl_path.write_text("".join(json.dumps(sample, ensure_ascii=False) + "\n" for sample in samples), encoding="utf-8")
        json_path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved %s valid samples to %s", len(samples), json_path)

    def _save_stats(self) -> None:
        path = self._unique_output_path(f"generation_stats_{self.timestamp}", ".json")
        path.write_text(json.dumps(self.stats, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_coverage(samples: List[Dict]) -> Dict:
    coverage = {"entity_types": {value: 0 for value in VALID_ENTITY_TYPES}, "assertions": {value: 0 for value in VALID_ASSERTIONS}, "text_styles": {}, "complexities": {}, "challenge_profiles": {}, "total_entities": 0, "total_samples": len(samples), "avg_entities_per_sample": 0}
    for sample in samples:
        entities = sample.get("entities", [])
        coverage["total_entities"] += len(entities)
        profile = sample.get("challenge_profile")
        if profile:
            coverage["challenge_profiles"][profile] = coverage["challenge_profiles"].get(profile, 0) + 1
        for entity in entities:
            if entity.get("type") in coverage["entity_types"]:
                coverage["entity_types"][entity["type"]] += 1
            for assertion in entity.get("assertions", []):
                if assertion in coverage["assertions"]:
                    coverage["assertions"][assertion] += 1
    if coverage["total_samples"]:
        coverage["avg_entities_per_sample"] = coverage["total_entities"] / coverage["total_samples"]
    coverage["missing_entity_types"] = [key for key, value in coverage["entity_types"].items() if value == 0]
    coverage["missing_assertions"] = [key for key, value in coverage["assertions"].items() if value == 0]
    return coverage
