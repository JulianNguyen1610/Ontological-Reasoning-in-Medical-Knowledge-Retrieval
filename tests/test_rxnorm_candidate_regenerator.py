import hashlib
import json

from data_generation.rxnorm_candidate_regenerator import remap_rxnorm_candidates

DRUG = "THU\u1ed0C"


def _drug(text: str, candidate: str) -> dict:
    return {
        "text": text,
        "type": DRUG,
        "position": [0, len(text)],
        "assertions": [],
        "candidates": [candidate],
    }


def test_remap_rxnorm_candidates_updates_exact_aliases_and_rejects_unknowns(tmp_path):
    source = tmp_path / "batch.jsonl"
    mapped = {"text": "aspirin po daily", "entities": [_drug("aspirin po daily", "legacy")]}
    unmatched = {"text": "unknown po daily", "entities": [_drug("unknown po daily", "legacy")]}
    source.write_text(
        "".join(json.dumps(record) + "\n" for record in [mapped, unmatched]), encoding="utf-8"
    )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    report = remap_rxnorm_candidates(source, tmp_path / "output", {"aspirin": ("1191",)})

    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert report["counts"] == {"input": 2, "accepted": 1, "rejected": 1, "remapped_entities": 1}
    accepted = json.loads(
        (tmp_path / "output" / "batch_rxnorm_remapped.jsonl").read_text(encoding="utf-8")
    )
    assert accepted["entities"][0]["candidates"] == ["1191"]
    rejected = json.loads(
        (tmp_path / "output" / "batch_rxnorm_rejected.jsonl").read_text(encoding="utf-8")
    )
    assert rejected["decision_trace"]["reason"] == "no_exact_active_rxnorm_alias"
