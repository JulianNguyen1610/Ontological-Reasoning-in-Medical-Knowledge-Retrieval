"""Contracts for deterministic, view-relative span proposal plugins.

Proposal plugins identify possible spans only.  Grounding, final typing, linking,
and threshold-based acceptance are intentionally owned by later pipeline stages.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from medlink_ie.domain import ProposalSource, SourceDocument, TextView

_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_SENSITIVE_METADATA_KEYS = frozenset(
    {"document", "document_id", "name", "note", "patient", "raw", "raw_text", "text"}
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _frozen_safe_metadata(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    copied = dict(value)
    for key, item in copied.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        if key.lower() in _SENSITIVE_METADATA_KEYS:
            raise ValueError(f"{field_name} must contain privacy-safe metadata only")
        _validate_safe_value(item, field_name)
    return MappingProxyType(copied)


def _validate_safe_value(value: Any, field_name: str) -> None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            _validate_safe_value(item, field_name)
        return
    if isinstance(value, Mapping):
        _frozen_safe_metadata(value, field_name)
        return
    raise TypeError(f"{field_name} values must be JSON primitives, lists, or mappings")


def _validate_score(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number between 0 and 1")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _validate_code(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SAFE_CODE.fullmatch(value):
        raise ValueError(f"{field_name} must be a privacy-safe code")


@dataclass(frozen=True, slots=True)
class ProposalEvidence:
    """Non-sensitive provenance emitted by a rule or model proposer."""

    kind: str
    identifier: str
    version: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_code(self.kind, "kind")
        _validate_code(self.identifier, "identifier")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("version must be a non-empty string")
        object.__setattr__(self, "metadata", _frozen_safe_metadata(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "kind": self.kind,
            "metadata": dict(self.metadata),
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class SourceTrust:
    """Source-local trust metadata; this is not an acceptance threshold."""

    weight: float
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_score(self.weight, "weight")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class SourceTrustConfiguration:
    """Immutable, explicit trust configuration passed into each proposal run."""

    sources: Mapping[ProposalSource, SourceTrust] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.sources, Mapping):
            raise TypeError("sources must be a mapping")
        copied = dict(self.sources)
        for source, trust in copied.items():
            if not isinstance(source, ProposalSource):
                raise TypeError("sources keys must be ProposalSource values")
            if not isinstance(trust, SourceTrust):
                raise TypeError("sources values must be SourceTrust values")
        object.__setattr__(self, "sources", MappingProxyType(copied))

    def trust_for(self, source: ProposalSource) -> SourceTrust:
        if not isinstance(source, ProposalSource):
            raise TypeError("source must be a ProposalSource")
        return self.sources.get(source, SourceTrust(1.0, True))

    def to_dict(self) -> dict[str, Any]:
        return {
            source.value: trust.to_dict()
            for source, trust in sorted(self.sources.items(), key=lambda item: item[0].value)
        }


@dataclass(frozen=True, slots=True)
class ProposalContext:
    """All immutable inputs available to a proposer for one source document."""

    document: SourceDocument
    text_views: Mapping[str, TextView]
    source_trust: SourceTrustConfiguration = field(default_factory=SourceTrustConfiguration)

    def __post_init__(self) -> None:
        if not isinstance(self.document, SourceDocument):
            raise TypeError("document must be a SourceDocument")
        if not isinstance(self.text_views, Mapping):
            raise TypeError("text_views must be a mapping")
        views = dict(self.text_views)
        for name, view in views.items():
            if not isinstance(name, str) or not name:
                raise ValueError("text view names must be non-empty strings")
            if not isinstance(view, TextView):
                raise TypeError("text_views values must be TextView values")
            if name != view.name:
                raise ValueError("text view mapping keys must match TextView.name")
        if not isinstance(self.source_trust, SourceTrustConfiguration):
            raise TypeError("source_trust must be a SourceTrustConfiguration")
        object.__setattr__(self, "text_views", MappingProxyType(views))

    def view_for(self, name: str) -> TextView:
        try:
            return self.text_views[name]
        except KeyError as exc:
            raise ValueError(f"unknown text view: {name}") from exc


def make_proposal_id(
    context: ProposalContext,
    source: ProposalSource,
    producer_version: str,
    view_name: str,
    view_start: int,
    view_end: int,
    evidence: tuple[ProposalEvidence, ...],
) -> str:
    """Create a content-addressed ID without exposing source text in traces."""

    if not isinstance(context, ProposalContext):
        raise TypeError("context must be a ProposalContext")
    if not isinstance(source, ProposalSource):
        raise TypeError("source must be a ProposalSource")
    view = context.view_for(view_name)
    if not 0 <= view_start < view_end <= len(view.text):
        raise ValueError("proposal span must be a non-empty interval in its text view")
    payload = {
        "document_id": context.document.document_id,
        "evidence": [item.to_dict() for item in evidence],
        "producer_version": producer_version,
        "source": source.value,
        "view_end": view_end,
        "view_name": view_name,
        "view_start": view_start,
    }
    return f"proposal-{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class SpanProposal:
    """A candidate span whose coordinates explicitly belong to one TextView."""

    proposal_id: str
    source: ProposalSource
    producer_version: str
    view_name: str
    view_start: int
    view_end: int
    proposed_text: str
    score: float
    evidence: tuple[ProposalEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise ValueError("proposal_id must be a non-empty string")
        if not isinstance(self.source, ProposalSource):
            raise TypeError("source must be a ProposalSource")
        if not isinstance(self.producer_version, str) or not self.producer_version:
            raise ValueError("producer_version must be a non-empty string")
        if not isinstance(self.view_name, str) or not self.view_name:
            raise ValueError("view_name must be a non-empty string")
        if not isinstance(self.view_start, int) or not isinstance(self.view_end, int):
            raise TypeError("view coordinates must be integers")
        if not self.view_start < self.view_end:
            raise ValueError("view coordinates must form a non-empty interval")
        if not isinstance(self.proposed_text, str) or not self.proposed_text:
            raise ValueError("proposed_text must be a non-empty string")
        _validate_score(self.score, "score")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if any(not isinstance(item, ProposalEvidence) for item in self.evidence):
            raise TypeError("evidence must contain ProposalEvidence values")

    @classmethod
    def create(
        cls,
        context: ProposalContext,
        source: ProposalSource,
        producer_version: str,
        view_name: str,
        view_start: int,
        view_end: int,
        score: float,
        evidence: tuple[ProposalEvidence, ...] = (),
    ) -> "SpanProposal":
        view = context.view_for(view_name)
        if not 0 <= view_start < view_end <= len(view.text):
            raise ValueError("proposal span must be a non-empty interval in its text view")
        evidence = tuple(evidence)
        return cls(
            make_proposal_id(
                context,
                source,
                producer_version,
                view_name,
                view_start,
                view_end,
                evidence,
            ),
            source,
            producer_version,
            view_name,
            view_start,
            view_end,
            view.text[view_start:view_end],
            score,
            evidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": [item.to_dict() for item in self.evidence],
            "producer_version": self.producer_version,
            "proposal_id": self.proposal_id,
            "proposed_text": self.proposed_text,
            "score": self.score,
            "source": self.source.value,
            "view_end": self.view_end,
            "view_name": self.view_name,
            "view_start": self.view_start,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@runtime_checkable
class SpanProposer(Protocol):
    """Plugin boundary for rules and future model-based span proposal."""

    name: str
    source: ProposalSource
    version: str

    def propose(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        """Return proposals only; do not ground, type, link, or globally filter them."""


@dataclass(frozen=True, slots=True)
class MockSpanProposer:
    """Deterministic configured proposer for integration tests."""

    name: str
    source: ProposalSource
    version: str
    proposals: tuple[SpanProposal, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.source, ProposalSource):
            raise TypeError("source must be a ProposalSource")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("version must be a non-empty string")
        object.__setattr__(self, "proposals", tuple(self.proposals))

    def propose(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        for proposal in self.proposals:
            if proposal.source is not self.source:
                raise ValueError("mock proposal source must match proposer source")
            view = context.view_for(proposal.view_name)
            if proposal.proposed_text != view.text[proposal.view_start : proposal.view_end]:
                raise ValueError("mock proposal text must match its text view")
        return self.proposals
