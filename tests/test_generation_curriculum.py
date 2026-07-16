import json
from pathlib import Path

import requests

from data_generation.config import GenerationConfig, FAMILY_HISTORY_DIAGNOSIS_CODES
from data_generation.generation_planner import ChallengePlanner
from data_generation.generators.text_generator import EntityAnnotation, TextGenerator
from data_generation.generators.topic_extractor import TopicExtractor
from data_generation.llm_client import LLMClient
from data_generation.local_validator import LocalSampleValidator
from data_generation.pipeline import DataGenerationPipeline


ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "data_generation" / "knowledge_seeds"


class NoopClient:
    def call_text_gen(self, *args, **kwargs):
        return ""

    def call_critic(self, *args, **kwargs):
        return '{"is_valid": true, "errors": [], "suggestions": []}'


def test_quota_selection_prioritizes_missing_profile():
    planner = ChallengePlanner({"basic": 0.1, "negation_scope": 0.9})
    assert planner.select_profile({"basic": 1, "negation_scope": 0}, 10) == "negation_scope"


def test_error_driven_weighting_boosts_missing_assertion():
    planner = ChallengePlanner({}, {"structural_fidelity": {"missing_assertions": ["isFamily"]}})
    assert planner.adjustments["family_scope"] > 1.0


def test_error_driven_weighting_changes_selection_before_base_quotas_are_full():
    planner = ChallengePlanner(
        {"basic": 0.9, "family_scope": 0.1},
        {"structural_fidelity": {"missing_assertions": ["isFamily"]}},
    )

    assert planner.select_profile({"basic": 8, "family_scope": 1}, 10) == "family_scope"


def test_profile_changes_scenario_and_prompt():
    extractor = TopicExtractor(SEEDS)
    family = extractor.extract_topic("few_entities", "family_scope")
    lab = extractor.extract_topic("single_entity", "lab_name_result_pair")
    assert family.challenge_profile == "family_scope"
    assert family.assertions == ["isFamily"]
    assert family.diagnosis["code"] in FAMILY_HISTORY_DIAGNOSIS_CODES
    assert lab.lab_tests
    instruction = TextGenerator._build_challenge_profile_instruction(
        "repeated_mention", [EntityAnnotation("đau ngực", "TRIỆU_CHỨNG", [], [])]
    )
    assert "lặp lại" in instruction


def test_critic_routing_is_risk_based(tmp_path):
    pipeline = DataGenerationPipeline(GenerationConfig(), NoopClient(), tmp_path, SEEDS)
    entity = {"text": "đau", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": [], "position": [0, 3]}
    assert not pipeline._should_call_critic("basic", [entity], [])
    assert pipeline._should_call_critic("mixed_language", [entity], [])
    pipeline.config.force_critic_all = True
    assert pipeline._should_call_critic("basic", [entity], [])


def test_hard_profiles_have_deterministic_validation():
    validator = LocalSampleValidator(TextGenerator(NoopClient()).assertion_cues)
    repeated = [
        {"text": "pain", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": [], "position": [0, 4]},
        {"text": "pain", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": [], "position": [6, 10]},
    ]
    assert validator.validate("pain. pain.", repeated, "repeated_mention")["valid"]
    assert not validator.validate("pain. pain.", repeated[:1], "repeated_mention")["valid"]
    assert not validator.validate("pain once.", repeated[:1], "repeated_mention")["valid"]

    abbreviation = {"text": "pain", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": [], "position": [3, 7]}
    assert validator.validate("BN pain.", [abbreviation], "abbreviation_or_typo")["valid"]
    assert not validator.validate("The pain.", [abbreviation], "abbreviation_or_typo")["valid"]
    entity_only_abbreviation = {"text": "ECG", "type": "TÊN_XÉT_NGHIỆM", "assertions": [], "candidates": [], "position": [0, 3]}
    assert not validator.validate("ECG.", [entity_only_abbreviation], "abbreviation_or_typo")["valid"]

    mixed = {"text": "pain", "type": "TRIỆU_CHỨNG", "assertions": [], "candidates": [], "position": [0, 4]}
    assert validator.validate("pain; follow-up tomorrow.", [mixed], "mixed_language")["valid"]
    assert not validator.validate("pain tomorrow.", [mixed], "mixed_language")["valid"]


def test_hard_profiles_upgrade_single_entity_before_selecting_entities():
    extractor = TopicExtractor(SEEDS)
    scenario = extractor.extract_topic("single_entity", "repeated_mention")
    assert scenario.complexity == "few_entities"
    assert len(scenario.symptoms) >= 1


def test_retry_classification_and_backoff_bounds():
    response = requests.Response()
    response.status_code = 429
    rate_limited = requests.exceptions.HTTPError(response=response)
    auth = requests.Response()
    auth.status_code = 401
    unauthorized = requests.exceptions.HTTPError(response=auth)
    client = LLMClient("", "", "", "", "", "", api_retry_base_delay=1, api_retry_max_delay=2, api_retry_jitter=0)
    assert client.is_retryable_error(rate_limited)
    assert not client.is_retryable_error(unauthorized)
    assert client.compute_backoff(3) == 2


def test_rate_limit_uses_retry_after_or_minimum_cooldown():
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "20"
    error = requests.exceptions.HTTPError(response=response)
    client = LLMClient("", "", "", "", "", "", api_retry_base_delay=1, api_retry_jitter=0, api_rate_limit_cooldown=15)
    assert client._retry_delay(error, 0) == 20

    response.headers.pop("Retry-After")
    assert client._retry_delay(error, 0) == 15


def test_checkpoint_resume_restores_samples_without_duplicates(tmp_path):
    pipeline = DataGenerationPipeline(GenerationConfig(checkpoint_interval=1), NoopClient(), tmp_path, SEEDS)
    pipeline.timestamp = "resume_case"
    pipeline._completed_attempts = 1
    sample = {"text": "BN đau ngực", "entities": [], "scenario_id": "existing"}
    checkpoint = pipeline._save_checkpoint([sample], total_planned=2)
    resumed = DataGenerationPipeline(
        GenerationConfig(resume_from_checkpoint=str(checkpoint)), NoopClient(), tmp_path, SEEDS
    )
    loaded = resumed._load_resume_checkpoint()
    assert loaded == [sample]
    assert resumed._completed_attempts == 1
    assert resumed.stats["resume"]["resumed"] is True


def test_run_targets_valid_samples_until_attempt_limit(tmp_path):
    pipeline = DataGenerationPipeline(
        GenerationConfig(num_samples=2, max_total_attempts=3), NoopClient(), tmp_path, SEEDS
    )
    samples = pipeline.run()

    assert samples == []
    assert pipeline.stats["total_generated"] == 3
    assert pipeline.stats["generation_target"]["target_reached"] is False


def test_local_validator_preserves_family_and_historical_rules():
    validator = LocalSampleValidator(TextGenerator(NoopClient()).assertion_cues)
    text = "Tiền sử gia đình: mẹ bị tăng huyết áp."
    start = text.index("tăng huyết áp")
    valid_family = {
        "text": "tăng huyết áp", "type": "CHẨN_ĐOÁN", "assertions": ["isFamily"],
        "candidates": ["I10"], "position": [start, start + len("tăng huyết áp")],
    }
    assert validator.validate(text, [valid_family])["valid"]
    invalid_family = dict(valid_family, candidates=["Z99"])
    assert not validator.validate(text, [invalid_family])["valid"]
