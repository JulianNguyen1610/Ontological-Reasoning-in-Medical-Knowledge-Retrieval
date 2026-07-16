"""Immutable, privacy-safe decision tracing for proposal pipeline stages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from medlink_ie.domain import ProposalSource
from medlink_ie.proposals.contract import (
    ProposalEvidence,
    _validate_code,
    _validate_score,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class DecisionTraceEvent:
    """A structured decision event containing only identifiers and safe evidence."""

    event_id: str
    subject_id: str
    stage: str
    action: str
    source: ProposalSource
    producer_version: str
    score: float
    evidence: tuple[ProposalEvidence, ...] = ()
    reason: str = "unspecified"

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id:
            raise ValueError("event_id must be a non-empty string")
        if not isinstance(self.subject_id, str) or not self.subject_id:
            raise ValueError("subject_id must be a non-empty string")
        _validate_code(self.stage, "stage")
        _validate_code(self.action, "action")
        if self.action not in {"kept", "dropped", "proposed"}:
            raise ValueError("action must be proposed, kept, or dropped")
        if not isinstance(self.source, ProposalSource):
            raise TypeError("source must be a ProposalSource")
        if not isinstance(self.producer_version, str) or not self.producer_version:
            raise ValueError("producer_version must be a non-empty string")
        _validate_score(self.score, "score")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if any(not isinstance(item, ProposalEvidence) for item in self.evidence):
            raise TypeError("evidence must contain ProposalEvidence values")
        _validate_code(self.reason, "reason")

    @classmethod
    def create(
        cls,
        subject_id: str,
        stage: str,
        action: str,
        source: ProposalSource,
        producer_version: str,
        score: float,
        evidence: tuple[ProposalEvidence, ...] = (),
        reason: str = "unspecified",
    ) -> "DecisionTraceEvent":
        evidence = tuple(evidence)
        payload = {
            "action": action,
            "evidence": [item.to_dict() for item in evidence],
            "producer_version": producer_version,
            "reason": reason,
            "score": score,
            "source": source.value,
            "stage": stage,
            "subject_id": subject_id,
        }
        event_id = (
            f"event-{hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()[:24]}"
        )
        return cls(
            event_id,
            subject_id,
            stage,
            action,
            source,
            producer_version,
            score,
            evidence,
            reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "event_id": self.event_id,
            "evidence": [item.to_dict() for item in self.evidence],
            "producer_version": self.producer_version,
            "reason": self.reason,
            "score": self.score,
            "source": self.source.value,
            "stage": self.stage,
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """Append-only value object; callers receive a new trace for every event."""

    events: tuple[DecisionTraceEvent, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        if any(not isinstance(event, DecisionTraceEvent) for event in self.events):
            raise TypeError("events must contain DecisionTraceEvent values")

    def record(self, event: DecisionTraceEvent) -> "DecisionTrace":
        if not isinstance(event, DecisionTraceEvent):
            raise TypeError("event must be a DecisionTraceEvent")
        return DecisionTrace(self.events + (event,))

    def to_dict(self) -> dict[str, Any]:
        return {"events": [event.to_dict() for event in self.events]}

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())
