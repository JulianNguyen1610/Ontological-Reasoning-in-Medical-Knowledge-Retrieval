import json

from data_generation.dataset_curator import GeneratedDataCurator
from data_generation.generators.text_generator import TextGenerator


def _sample(text, entities, profile="basic"):
    return {"text": text, "entities": entities, "challenge_profile": profile}


def _entity(text, entity_type, start, assertions=None, candidates=None):
    return {
        "text": text,
        "type": entity_type,
        "position": [start, start + len(text)],
        "assertions": assertions or [],
        "candidates": candidates or [],
    }


def test_curator_preserves_raw_and_separates_validity_and_profiles(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "curated"
    raw_dir.mkdir()
    modern_text = "BN follow-up sau điều trị. Đau ngực tái diễn."
    legacy_text = "Bệnh nhân đau đầu 2 ngày nay."
    invalid_text = "Mẹ có đau bụng từng đợt."
    payload = [
        _sample(modern_text, [_entity("Đau ngực", "TRIỆU_CHỨNG", 27)], "mixed_language"),
        _sample(legacy_text, [_entity("đau đầu", "TRIỆU_CHỨNG", 10)]),
        _sample(
            invalid_text,
            [_entity("đau bụng", "TRIỆU_CHỨNG", 6, ["isFamily"])],
        ),
    ]
    source = raw_dir / "training_data_20260713_000000.json"
    source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    curator = GeneratedDataCurator(TextGenerator(None).assertion_cues)
    report = curator.curate(raw_dir, output_dir, validation_ratio=0.5)

    assert json.loads(source.read_text(encoding="utf-8")) == payload
    assert report["counts"] == {
        "input": 3,
        "gold": 1,
        "gold_train": 0,
        "gold_validation": 1,
        "standard": 1,
        "rejected": 1,
    }
    rejected = json.loads((output_dir / "rejected.json").read_text(encoding="utf-8"))
    assert rejected[0]["reason"] == "validation_failed"
    assert "invalid_family_semantics" in rejected[0]["validation_errors"]
    provenance = json.loads((output_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["gold"][0]["source_file"] == source.name
    assert provenance["gold"][0]["quality_score"] > 100


def test_curator_prefers_modern_profile_for_hard_near_duplicate(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    text = "BN follow-up, đau ngực khi gắng sức và khó thở."
    payload = [
        _sample(text, [_entity("đau ngực", "TRIỆU_CHỨNG", 14)]),
        _sample(text, [_entity("đau ngực", "TRIỆU_CHỨNG", 14)], "mixed_language"),
    ]
    (raw_dir / "training_data_20260713_000000.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    report = GeneratedDataCurator(TextGenerator(None).assertion_cues).curate(
        raw_dir, tmp_path / "curated"
    )

    assert report["counts"]["gold"] == 1
    assert report["rejection_reasons"] == {"exact_duplicate": 1}
