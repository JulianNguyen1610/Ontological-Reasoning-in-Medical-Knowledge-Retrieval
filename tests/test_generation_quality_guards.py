from pathlib import Path

from data_generation.generators.text_generator import TextGenerator
from data_generation.local_validator import LocalSampleValidator


def test_local_validator_rejects_cjk_surface_noise():
    validator = LocalSampleValidator(TextGenerator(None).assertion_cues)
    text = "BN \u4e2d đau đầu"
    entity = {"text": "đau đầu", "type": "TRIỆU_CHỨNG", "position": [5, 12], "assertions": [], "candidates": []}
    result = validator.validate(text, [entity])
    assert "contains_cjk_noise" in result["errors"]


def test_topic_extractor_uses_nonempty_rxnorm_candidates():
    from data_generation.generators.topic_extractor import TopicExtractor

    seeds_dir = Path(__file__).resolve().parents[1] / "data_generation" / "knowledge_seeds"
    extractor = TopicExtractor(seeds_dir)
    assert extractor.rxnorm_seeds
    assert all(seed["rxcui"].isdigit() for seed in extractor.rxnorm_seeds)
