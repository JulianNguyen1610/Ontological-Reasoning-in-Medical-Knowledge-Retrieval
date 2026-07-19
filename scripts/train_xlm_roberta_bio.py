"""Fine-tune the pinned local XLM-R checkpoint on a grouped train split only.

This command is intentionally for the provisional synthetic benchmark.  It must
not be presented as a BTC/competition result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Sequence

import torch
import yaml
from transformers import AutoModelForTokenClassification, AutoTokenizer

from medlink_ie.dataset import DatasetRecord, SplitConfig, create_grouped_splits
from medlink_ie.domain import EntityType


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/encoder_xlm_roberta_base.yaml")
    )
    parser.add_argument("--data", type=Path, default=Path("data/curated/gold.json"))
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=Path("data/benchmarks/provisional_synthetic_v1/grouped_split_manifest.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--max-subwords", type=int, default=256)
    parsed = parser.parse_args(arguments)
    if parsed.epochs < 1 or parsed.learning_rate <= 0 or parsed.max_subwords < 1:
        raise ValueError("epochs, learning-rate, and max-subwords must be positive")
    if parsed.output.exists():
        raise FileExistsError(f"refusing to overwrite training output: {parsed.output}")

    config = _read_mapping(parsed.config)
    if config.get("benchmark_status") != "provisional_synthetic_only":
        raise ValueError("this trainer accepts only a clearly labelled provisional configuration")
    checkpoint = _mapping(config, "base_checkpoint")
    base_dir = Path(_string(checkpoint, "local_directory"))
    _verify_file(Path(_string(checkpoint, "weights_path")), _string(checkpoint, "weights_sha256"))
    _verify_file(
        Path(_string(checkpoint, "tokenizer_path")), _string(checkpoint, "tokenizer_sha256")
    )
    records = _read_records(parsed.data)
    manifest = _read_mapping(parsed.split_manifest)
    _verify_grouped_manifest(records, manifest)
    train_ids = _string_list(_mapping(manifest, "split_record_ids"), "train")
    if not train_ids or any(identifier not in records for identifier in train_ids):
        raise ValueError("split manifest train IDs do not match the supplied dataset")
    _seed(parsed.seed)

    labels = _labels()
    tokenizer = AutoTokenizer.from_pretrained(base_dir, local_files_only=True, use_fast=True)
    model = AutoModelForTokenClassification.from_pretrained(
        base_dir,
        local_files_only=True,
        num_labels=len(labels),
        id2label={index: label for index, label in enumerate(labels)},
        label2id={label: index for index, label in enumerate(labels)},
        ignore_mismatched_sizes=True,
    )
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=parsed.learning_rate)
    label_ids = {label: index for index, label in enumerate(labels)}
    for _ in range(parsed.epochs):
        ordered = list(train_ids)
        random.shuffle(ordered)
        for record_id in ordered:
            record = records[record_id]
            encoded, targets = _encode_labels(
                tokenizer, record["text"], record["entities"], label_ids, parsed.max_subwords
            )
            output = model(**encoded, labels=targets)
            output.loss.backward()
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)

    parsed.output.mkdir(parents=True)
    model.eval()
    model.save_pretrained(parsed.output, safe_serialization=True)
    tokenizer.save_pretrained(parsed.output)
    weights = parsed.output / "model.safetensors"
    report = {
        "schema_version": 1,
        "benchmark_status": "provisional_synthetic_only",
        "base_revision": checkpoint["revision"],
        "base_weights_sha256": checkpoint["weights_sha256"],
        "checkpoint_sha256": _checksum(weights),
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "label_scheme": "BIO",
        "labels": labels,
        "seed": parsed.seed,
        "epochs": parsed.epochs,
        "learning_rate": parsed.learning_rate,
        "max_subwords": parsed.max_subwords,
        "train_split_checksum": _string(_mapping(manifest, "split_checksums"), "train"),
        "dev_split_checksum": _string(_mapping(manifest, "split_checksums"), "dev"),
        "test_split_checksum": _string(_mapping(manifest, "split_checksums"), "test"),
        "train_record_ids": train_ids,
    }
    (parsed.output / "training_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


def _encode_labels(
    tokenizer: Any,
    text: str,
    entities: tuple[dict[str, Any], ...],
    label_ids: dict[str, int],
    max_subwords: int,
) -> tuple[dict[str, torch.Tensor], torch.Tensor]:
    encoded = tokenizer(
        text,
        return_offsets_mapping=True,
        return_tensors="pt",
        truncation=True,
        max_length=max_subwords,
    )
    offsets = [tuple(pair) for pair in encoded.pop("offset_mapping")[0].tolist()]
    targets = [-100] * len(offsets)
    for index, (start, end) in enumerate(offsets):
        if start == end:
            continue
        matched = [entity for entity in entities if start < entity["end"] and entity["start"] < end]
        if not matched:
            targets[index] = label_ids["O"]
            continue
        if len(matched) != 1 or not start >= matched[0]["start"] or not end <= matched[0]["end"]:
            raise ValueError(
                "BIO training cannot represent overlapping or partial-subword entities"
            )
        entity = matched[0]
        prefix = "B" if start == entity["start"] else "I"
        targets[index] = label_ids[f"{prefix}-{entity['type']}"]
    return encoded, torch.tensor([targets], dtype=torch.long)


def _read_records(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("training data must be a JSON array")
    records: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(data):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise ValueError("each training record must contain text")
        entities = item.get("entities")
        if not isinstance(entities, list):
            raise ValueError("each training record must contain entities")
        parsed_entities: list[dict[str, Any]] = []
        for entity in entities:
            if not isinstance(entity, dict) or not isinstance(entity.get("position"), list):
                raise ValueError("entity position must be a two-item list")
            start, end = entity["position"]
            entity_type = EntityType(entity["type"])
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or item["text"][start:end] != entity.get("text")
            ):
                raise ValueError("entity must preserve exact raw-text boundaries")
            parsed_entities.append({"start": start, "end": end, "type": entity_type.value})
        scenario_id = item.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise ValueError("each training record must contain scenario_id")
        records[f"provisional:{index:04d}"] = {
            "text": item["text"],
            "entities": tuple(parsed_entities),
            "scenario_id": scenario_id,
        }
    return records


def _verify_grouped_manifest(records: dict[str, dict[str, Any]], manifest: dict[str, Any]) -> None:
    seed, fields = manifest.get("seed"), manifest.get("group_fields")
    if not isinstance(seed, int) or fields != ["scenario_id"]:
        raise ValueError("trainer requires the versioned scenario_id grouped split policy")
    rebuilt = create_grouped_splits(
        tuple(
            DatasetRecord(
                record_id,
                record["text"],
                {
                    "scenario_id": record["scenario_id"],
                    "benchmark_status": "provisional_synthetic_v1",
                },
            )
            for record_id, record in sorted(records.items())
        ),
        SplitConfig(seed=seed, proportions=(0.6, 0.2, 0.2), group_fields=("scenario_id",)),
    ).manifest.to_dict()
    for key in ("source_checksum", "split_checksums", "split_record_ids", "manifest_checksum"):
        if rebuilt.get(key) != manifest.get(key):
            raise ValueError(f"grouped split manifest mismatch: {key}")


def _labels() -> list[str]:
    return [
        "O",
        *[f"{prefix}-{entity_type.value}" for entity_type in EntityType for prefix in ("B", "I")],
    ]


def _seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_file(path: Path, expected: str) -> None:
    if not path.is_file() or _checksum(path) != expected:
        raise ValueError(f"local artifact is missing or checksum-invalid: {path}")


def _read_mapping(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"expected mapping: {path}")
    return loaded


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, dict):
        raise ValueError(f"missing mapping: {key}")
    return nested


def _string(value: dict[str, Any], key: str) -> str:
    nested = value.get(key)
    if not isinstance(nested, str) or not nested:
        raise ValueError(f"missing string: {key}")
    return nested


def _string_list(value: dict[str, Any], key: str) -> list[str]:
    nested = value.get(key)
    if (
        not isinstance(nested, list)
        or not nested
        or any(not isinstance(item, str) for item in nested)
    ):
        raise ValueError(f"missing string list: {key}")
    return nested


if __name__ == "__main__":
    raise SystemExit(main())
