import hashlib
import json

from data_generation.generated_batch_filter import curate_jsonl_batch

DIAGNOSIS = "CH\u1ea8N_\u0110O\u00c1N"
DRUG = "THU\u1ed0C"


def _sample(text, entities, profile="basic"):
    return {"text": text, "entities": entities, "challenge_profile": profile}


def _entity(text, entity_type, start, candidates=None):
    return {
        "text": text,
        "type": entity_type,
        "position": [start, start + len(text)],
        "assertions": [],
        "candidates": candidates or [],
    }


def test_curate_jsonl_batch_preserves_raw_and_records_rejection_trace(tmp_path):
    source = tmp_path / "training_data.jsonl"
    valid = _sample("Patient has asthma.", [_entity("asthma", DIAGNOSIS, 12, ["J45.9"])])
    repeated = _sample(
        "asthma then asthma", [_entity("asthma", DIAGNOSIS, 0, ["J45.9"])], "repeated_mention"
    )
    cjk_noise = _sample("Patient \u4e2d has asthma.", [_entity("asthma", DIAGNOSIS, 14, ["J45.9"])])
    empty_rxnorm = _sample("aspirin", [_entity("aspirin", DRUG, 0, [""])])
    original = "".join(
        json.dumps(item, ensure_ascii=False) + "\n"
        for item in [valid, repeated, cjk_noise, empty_rxnorm]
    )
    source.write_text(original, encoding="utf-8")
    original_digest = hashlib.sha256(source.read_bytes()).hexdigest()

    report = curate_jsonl_batch(source, tmp_path / "curated")

    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_digest
    assert report["counts"] == {"input": 4, "accepted": 1, "rejected": 3}
    accepted = (tmp_path / "curated" / "training_data_clean.jsonl").read_text(encoding="utf-8")
    assert json.loads(accepted) == valid
    rejected = [
        json.loads(line)
        for line in (tmp_path / "curated" / "training_data_rejected.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {item["decision_trace"]["reason"] for item in rejected} == {
        "missing_repeated_annotation",
        "contains_cjk_noise",
        "empty_linking_candidate",
    }
