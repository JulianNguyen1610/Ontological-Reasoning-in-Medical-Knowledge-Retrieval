"""Deterministic lexical retrieval over frozen canonical terminology tables."""

from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from medlink_ie.terminology.preparation import AliasRecord, CanonicalTables, ConceptRecord


@dataclass(frozen=True, slots=True)
class LexicalRetrievalConfig:
    """Fixed local retrieval configuration; channel scores are never fused."""

    ngram_min: int = 3
    ngram_max: int = 5
    bm25_k1: float = 1.2
    bm25_b: float = 0.75

    def __post_init__(self) -> None:
        if self.ngram_min < 1 or self.ngram_max < self.ngram_min:
            raise ValueError("ngram range must satisfy 1 <= ngram_min <= ngram_max")
        if self.bm25_k1 <= 0:
            raise ValueError("bm25_k1 must be positive")
        if not 0 <= self.bm25_b <= 1:
            raise ValueError("bm25_b must be between zero and one")


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    """Explicit terminology and entity-type eligibility constraints."""

    terminologies: tuple[str, ...] = ()
    entity_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value for value in self.terminologies):
            raise ValueError("terminologies must contain non-empty strings")
        if any(not isinstance(value, str) or not value for value in self.entity_types):
            raise ValueError("entity_types must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    channel: str
    score: float
    matched_alias: str
    normalized_query: str


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    system: str
    concept_id: str
    preferred_term: str
    evidence: tuple[RetrievalEvidence, ...]


@dataclass(frozen=True, slots=True)
class IndexArtifact:
    path: Path
    checksum_sha256: str
    config: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", MappingProxyType(dict(self.config)))


@dataclass(frozen=True, slots=True)
class LexicalTerminologyIndex:
    """Read-only indexes derived solely from canonical table rows."""

    concepts: Mapping[tuple[str, str], ConceptRecord]
    aliases: Mapping[tuple[str, str], tuple[AliasRecord, ...]]
    exact_index: Mapping[str, tuple[tuple[str, str], ...]]
    accentless_index: Mapping[str, tuple[tuple[str, str], ...]]
    bm25_documents: Mapping[tuple[str, str], tuple[str, ...]]
    ngram_index: Mapping[str, tuple[tuple[str, str], ...]]
    config: LexicalRetrievalConfig
    type_to_terminologies: Mapping[str, tuple[str, ...]]
    artifact_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "concepts",
            "aliases",
            "exact_index",
            "accentless_index",
            "bm25_documents",
            "ngram_index",
            "type_to_terminologies",
            "artifact_metadata",
        ):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))

    def search(
        self, query: str, filters: RetrievalFilters = RetrievalFilters()
    ) -> tuple[RetrievalResult, ...]:
        """Return all eligible concepts with per-channel evidence in stable order."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        exact_query = _case_normalize(query)
        accentless_query = _accentless_normalize(query)
        if not exact_query:
            return ()
        allowed = self._allowed_targets(filters)
        if not allowed:
            return ()
        evidence: dict[tuple[str, str], list[RetrievalEvidence]] = defaultdict(list)
        self._add_exact(
            evidence, self.exact_index.get(exact_query, ()), "exact_alias", 1.0, exact_query
        )
        self._add_exact(
            evidence,
            self.accentless_index.get(accentless_query, ()),
            "accentless_exact",
            1.0,
            accentless_query,
        )
        self._add_bm25(evidence, accentless_query)
        self._add_ngrams(evidence, accentless_query)
        results = [
            RetrievalResult(
                key[0],
                key[1],
                self.concepts[key].preferred_term,
                tuple(sorted(values, key=_evidence_key)),
            )
            for key, values in evidence.items()
            if key in allowed
        ]
        return tuple(sorted(results, key=_result_key))

    def _allowed_targets(self, filters: RetrievalFilters) -> set[tuple[str, str]]:
        systems = set(filters.terminologies)
        for entity_type in filters.entity_types:
            mapped = self.type_to_terminologies.get(entity_type)
            if mapped is None:
                raise ValueError(f"unsupported entity type filter: {entity_type}")
            systems = systems.intersection(mapped) if systems else set(mapped)
        return {
            key
            for key, concept in self.concepts.items()
            if concept.active and (not systems or concept.system in systems)
        }

    def _add_exact(
        self,
        evidence: dict[tuple[str, str], list[RetrievalEvidence]],
        targets: tuple[tuple[str, str], ...],
        channel: str,
        score: float,
        normalized_query: str,
    ) -> None:
        for target in targets:
            evidence[target].append(
                RetrievalEvidence(channel, score, self.aliases[target][0].alias, normalized_query)
            )

    def _add_bm25(
        self, evidence: dict[tuple[str, str], list[RetrievalEvidence]], query: str
    ) -> None:
        tokens = _tokens(query)
        if not tokens:
            return
        document_count = len(self.bm25_documents)
        average_length = (
            sum(len(tokens) for tokens in self.bm25_documents.values()) / document_count
        )
        document_frequency = Counter(
            token for document in self.bm25_documents.values() for token in set(document)
        )
        for target, document in self.bm25_documents.items():
            frequencies = Counter(document)
            score = 0.0
            for token in tokens:
                frequency = frequencies[token]
                if not frequency:
                    continue
                idf = math.log(
                    1
                    + (document_count - document_frequency[token] + 0.5)
                    / (document_frequency[token] + 0.5)
                )
                denominator = frequency + self.config.bm25_k1 * (
                    1 - self.config.bm25_b + self.config.bm25_b * len(document) / average_length
                )
                score += idf * frequency * (self.config.bm25_k1 + 1) / denominator
            if score:
                evidence[target].append(
                    RetrievalEvidence("bm25", score, self.aliases[target][0].alias, query)
                )

    def _add_ngrams(
        self, evidence: dict[tuple[str, str], list[RetrievalEvidence]], query: str
    ) -> None:
        query_grams = _ngrams(query, self.config.ngram_min, self.config.ngram_max)
        if not query_grams:
            return
        overlaps: Counter[tuple[str, str]] = Counter()
        for gram in query_grams:
            overlaps.update(self.ngram_index.get(gram, ()))
        for target, overlap in overlaps.items():
            alias_grams = _ngrams(
                _accentless_normalize(self.aliases[target][0].alias),
                self.config.ngram_min,
                self.config.ngram_max,
            )
            score = overlap / len(query_grams | alias_grams)
            evidence[target].append(
                RetrievalEvidence("ngram", score, self.aliases[target][0].alias, query)
            )


def build_lexical_index(
    tables: CanonicalTables,
    config: LexicalRetrievalConfig = LexicalRetrievalConfig(),
    type_to_terminologies: Mapping[str, tuple[str, ...]] | None = None,
) -> LexicalTerminologyIndex:
    """Build deterministic local lexical indexes from canonical table records."""
    concepts = {
        (record.system, record.concept_id): record for record in tables.concepts if record.active
    }
    aliases: dict[tuple[str, str], list[AliasRecord]] = defaultdict(list)
    for alias in tables.aliases:
        target = (alias.system, alias.concept_id)
        if target in concepts:
            aliases[target].append(alias)
    ordered_aliases = {
        target: tuple(sorted(records, key=lambda item: (item.alias, item.source_row)))
        for target, records in aliases.items()
    }
    exact: dict[str, set[tuple[str, str]]] = defaultdict(set)
    accentless: dict[str, set[tuple[str, str]]] = defaultdict(set)
    documents: dict[tuple[str, str], tuple[str, ...]] = {}
    ngrams: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for target, records in sorted(ordered_aliases.items()):
        token_document: list[str] = []
        seen_terms: set[str] = set()
        for alias in records:
            exact[alias.normalized_alias].add(target)
            normalized = _accentless_normalize(alias.alias)
            accentless[normalized].add(target)
            if normalized not in seen_terms:
                token_document.extend(_tokens(normalized))
                seen_terms.add(normalized)
            for gram in _ngrams(normalized, config.ngram_min, config.ngram_max):
                ngrams[gram].add(target)
        documents[target] = tuple(token_document)
    canonical_checksum = _canonical_checksum(
        {
            "concepts": [
                _concept_payload(record) for record in sorted(concepts.values(), key=_concept_key)
            ],
            "aliases": [
                _alias_payload(record) for records in ordered_aliases.values() for record in records
            ],
        }
    )
    metadata = {
        "schema_version": 1,
        "canonical_tables_checksum": canonical_checksum,
        "config": _config_payload(config),
        "concept_count": len(concepts),
        "alias_count": sum(len(records) for records in ordered_aliases.values()),
    }
    type_mapping = {
        key: tuple(sorted(value)) for key, value in (type_to_terminologies or {}).items()
    }
    return LexicalTerminologyIndex(
        concepts,
        ordered_aliases,
        {key: tuple(sorted(value)) for key, value in exact.items()},
        {key: tuple(sorted(value)) for key, value in accentless.items()},
        documents,
        {key: tuple(sorted(value)) for key, value in ngrams.items()},
        config,
        type_mapping,
        metadata,
    )


def write_index_artifact(index: LexicalTerminologyIndex, path: str | Path) -> IndexArtifact:
    """Persist deterministic index metadata with its checksum and configuration."""
    artifact_path = Path(path)
    payload = {
        **index.artifact_metadata,
        "config": _config_payload(index.config),
        "type_to_terminologies": {
            key: list(value) for key, value in sorted(index.type_to_terminologies.items())
        },
        "indexes": {
            "accentless_exact_keys": len(index.accentless_index),
            "bm25_documents": len(index.bm25_documents),
            "exact_alias_keys": len(index.exact_index),
            "ngram_keys": len(index.ngram_index),
        },
    }
    body = _canonical_json(payload).encode("utf-8")
    checksum = sha256(body).hexdigest()
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(body)
    return IndexArtifact(artifact_path, checksum, payload["config"])


def _case_normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _accentless_normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    unaccented = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    unaccented = unaccented.replace("đ", "d")
    return " ".join("".join(char if char.isalnum() else " " for char in unaccented).split())


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(value.split())


def _ngrams(value: str, minimum: int, maximum: int) -> set[str]:
    padded = f" {value} "
    return {
        padded[start : start + size]
        for size in range(minimum, maximum + 1)
        for start in range(len(padded) - size + 1)
    }


def _evidence_key(item: RetrievalEvidence) -> tuple[int, float, str]:
    ranks = {"exact_alias": 0, "accentless_exact": 1, "bm25": 2, "ngram": 3}
    return ranks[item.channel], -item.score, item.matched_alias


def _result_key(item: RetrievalResult) -> tuple[int, float, str, str]:
    rank, score, _ = _evidence_key(item.evidence[0])
    return rank, score, item.system, item.concept_id


def _concept_key(record: ConceptRecord) -> tuple[str, str]:
    return record.system, record.concept_id


def _concept_payload(record: ConceptRecord) -> dict[str, Any]:
    return {"system": record.system, "concept_id": record.concept_id, "active": record.active}


def _alias_payload(record: AliasRecord) -> dict[str, str]:
    return {"system": record.system, "concept_id": record.concept_id, "alias": record.alias}


def _config_payload(config: LexicalRetrievalConfig) -> dict[str, float | int]:
    return {
        "bm25_b": config.bm25_b,
        "bm25_k1": config.bm25_k1,
        "ngram_max": config.ngram_max,
        "ngram_min": config.ngram_min,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _canonical_checksum(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()
