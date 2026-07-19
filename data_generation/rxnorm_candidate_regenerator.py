"""Deterministically remap generated drug candidates from a local RxNorm snapshot."""

from __future__ import annotations

import copy
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Tuple

from medlink_ie.provenance.manifest import load_terminology_manifest
from medlink_ie.terminology.preparation import normalize_alias_for_retrieval

DRUG_ENTITY_TYPE = "THUỐC"
ROUTE_PATTERN = re.compile(r"\s+(?:po|iv|im|sc|oral|uống)\b", re.IGNORECASE)


def build_active_rxnorm_alias_index(manifest_path: Path) -> Dict[str, Tuple[str, ...]]:
    """Load exact aliases for active, allowed-TTY RxNorm concepts from a verified archive."""
    manifest = load_terminology_manifest(manifest_path, verify_paths=True)
    aliases: Dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(manifest.rxnorm.source_path) as archive:
        with archive.open("rrf/RXNCONSO.RRF") as handle:
            for raw_row in handle:
                fields = raw_row.decode("utf-8").rstrip("\r\n").split("|")
                if len(fields) <= 16:
                    continue
                if fields[12] not in manifest.rxnorm.allowed_ttys or fields[16] == "O":
                    continue
                aliases[normalize_alias_for_retrieval(fields[14])].add(fields[0])
    return {key: tuple(sorted(values)) for key, values in aliases.items()}


def remap_rxnorm_candidates(
    input_path: Path,
    output_dir: Path,
    alias_index: Mapping[str, Tuple[str, ...]],
) -> Dict[str, Any]:
    """Create immutable JSONL views with exact, active RxNorm mappings only."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    accepted: list[Dict[str, Any]] = []
    rejected: list[Dict[str, Any]] = []
    remap_trace: list[Dict[str, Any]] = []
    remapped_entities = 0

    for line_number, raw_line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
        sample = json.loads(raw_line)
        mapped_sample, updates, reason = _remap_sample(sample, alias_index)
        if reason is not None:
            rejected.append(
                {
                    "source_line": line_number,
                    "decision_trace": {"decision": "rejected", "reason": reason},
                    "sample": sample,
                }
            )
            continue
        accepted.append(mapped_sample)
        remapped_entities += len(updates)
        remap_trace.append(
            {
                "source_line": line_number,
                "decision_trace": {"decision": "accepted", "entity_updates": updates},
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem
    _write_jsonl(output_dir / f"{stem}_rxnorm_remapped.jsonl", accepted)
    _write_jsonl(output_dir / f"{stem}_rxnorm_rejected.jsonl", rejected)
    _write_jsonl(output_dir / f"{stem}_rxnorm_remap_trace.jsonl", remap_trace)
    report = {
        "format_version": 1,
        "input_path": str(input_path),
        "policy": "exact active RxNorm alias only; ambiguous or unmatched mentions are rejected",
        "counts": {
            "input": len(accepted) + len(rejected),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "remapped_entities": remapped_entities,
        },
        "rejection_reasons": dict(Counter(item["decision_trace"]["reason"] for item in rejected)),
    }
    (output_dir / f"{stem}_rxnorm_remap_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _remap_sample(
    sample: Dict[str, Any], alias_index: Mapping[str, Tuple[str, ...]]
) -> tuple[Dict[str, Any], list[Dict[str, str]], str | None]:
    mapped_sample = copy.deepcopy(sample)
    updates: list[Dict[str, str]] = []
    for entity in mapped_sample.get("entities", []):
        if entity.get("type") != DRUG_ENTITY_TYPE:
            continue
        ingredient = _ingredient_surface(entity.get("text"))
        candidates = alias_index.get(normalize_alias_for_retrieval(ingredient), ())
        if len(candidates) != 1:
            return sample, [], "no_exact_active_rxnorm_alias"
        previous = entity.get("candidates", [])
        entity["candidates"] = [candidates[0]]
        updates.append(
            {
                "text": entity["text"],
                "matched_alias": ingredient,
                "previous_candidates": ",".join(previous),
                "new_candidate": candidates[0],
            }
        )
    return mapped_sample, updates, None


def _ingredient_surface(entity_text: Any) -> str:
    if not isinstance(entity_text, str) or not entity_text.strip():
        raise ValueError("drug entity text must be non-empty")
    return ROUTE_PATTERN.split(entity_text, maxsplit=1)[0].strip()


def _write_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
