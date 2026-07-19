"""Optional local Ollama JSON-only span proposer with fail-closed validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from medlink_ie.domain import EntityType, ProposalSource
from medlink_ie.proposals.contract import ProposalContext, ProposalEvidence, SpanProposal
from medlink_ie.proposals.tracing import DecisionTrace, DecisionTraceEvent

_MAX_PARAMETERS = 9_000_000_000
_MODEL_TAG = "qwen3.5:9b"
_PROMPT_PATH = Path("artifacts/prompts/ollama_span_proposer_v1.json")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class OllamaError(RuntimeError):
    """A local runtime failure that must produce no proposal."""


@runtime_checkable
class LocalOllamaGenerator(Protocol):
    """Small local transport boundary; implementations must never download models."""

    def show(self, model: str, timeout_seconds: float) -> Mapping[str, Any]: ...

    def generate(
        self,
        model: str,
        system_prompt: str,
        prompt: str,
        options: Mapping[str, Any],
        timeout_seconds: float,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class OllamaSpanProposerConfig:
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:11434"
    model_tag: str = _MODEL_TAG
    declared_parameter_count: int = _MAX_PARAMETERS
    prompt_path: Path = _PROMPT_PATH
    ablation_artifact_path: Path | None = None
    ablation_artifact_checksum: str | None = None
    max_documents_per_batch: int = 8
    max_input_characters: int = 12_000
    max_output_tokens: int = 512
    timeout_seconds: float = 30.0
    seed: int = 42
    competition_mode: bool = True

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if (parsed.scheme, parsed.hostname, parsed.port, parsed.path) != (
            "http",
            "127.0.0.1",
            11434,
            "",
        ):
            raise ValueError("Ollama endpoint must be http://127.0.0.1:11434")
        if self.model_tag != _MODEL_TAG:
            raise ValueError("only qwen3.5:9b is supported")
        if not 1 <= self.declared_parameter_count <= _MAX_PARAMETERS:
            raise ValueError("declared_parameter_count must be between 1 and 9B")
        if min(self.max_documents_per_batch, self.max_input_characters, self.max_output_tokens) < 1:
            raise ValueError("Ollama limits must be positive")
        if self.timeout_seconds <= 0 or self.seed < 0:
            raise ValueError("timeout_seconds must be positive and seed must be non-negative")
        if self.enabled and (
            self.ablation_artifact_path is None or self.ablation_artifact_checksum is None
        ):
            raise ValueError(
                "enabled Ollama proposer requires a verified positive ablation artifact"
            )
        if self.ablation_artifact_checksum is not None and (
            len(self.ablation_artifact_checksum) != 64
            or any(
                character not in "0123456789abcdefABCDEF"
                for character in self.ablation_artifact_checksum
            )
        ):
            raise ValueError("ablation_artifact_checksum must be a SHA-256 hex digest")
        object.__setattr__(self, "prompt_path", Path(self.prompt_path))
        if self.ablation_artifact_path is not None:
            object.__setattr__(self, "ablation_artifact_path", Path(self.ablation_artifact_path))


class UrllibLocalOllamaGenerator:
    """Minimal urllib client restricted to the loopback Ollama service."""

    def __init__(self, endpoint: str = "http://127.0.0.1:11434") -> None:
        self.endpoint = endpoint.rstrip("/")

    def show(self, model: str, timeout_seconds: float) -> Mapping[str, Any]:
        return self._request("/api/show", {"name": model}, timeout_seconds)

    def generate(
        self,
        model: str,
        system_prompt: str,
        prompt: str,
        options: Mapping[str, Any],
        timeout_seconds: float,
    ) -> str:
        response = self._request(
            "/api/generate",
            {
                "model": model,
                "system": system_prompt,
                "prompt": prompt,
                "stream": False,
                "options": dict(options),
            },
            timeout_seconds,
        )
        value = response.get("response")
        if not isinstance(value, str):
            raise OllamaError("invalid_generate_response")
        return value

    def _request(
        self, path: str, payload: Mapping[str, Any], timeout_seconds: float
    ) -> Mapping[str, Any]:
        request = Request(
            self.endpoint + path,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed loopback endpoint
                value = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise OllamaError("local_ollama_unavailable") from error
        if not isinstance(value, Mapping):
            raise OllamaError("invalid_metadata_response")
        return value


@dataclass(frozen=True, slots=True)
class _PromptArtifact:
    version: str
    checksum: str
    system_prompt: str


@dataclass(frozen=True, slots=True)
class _AblationGate:
    checksum: str
    score_delta: float


class OllamaSpanProposer:
    """Opt-in raw-view proposer; all invalid output is rejected as a whole."""

    name = "ollama-local-span-proposer"
    source = ProposalSource.LLM_PROPOSER
    version = "ollama-span-v1"

    def __init__(
        self,
        config: OllamaSpanProposerConfig = OllamaSpanProposerConfig(),
        generator: LocalOllamaGenerator | None = None,
    ) -> None:
        self.config = config
        self.generator = generator or UrllibLocalOllamaGenerator(config.endpoint)
        self.last_trace = DecisionTrace()

    def propose(self, context: ProposalContext) -> tuple[SpanProposal, ...]:
        return self.propose_batch((context,)).get(context.document.document_id, ())

    def propose_batch(
        self, contexts: tuple[ProposalContext, ...]
    ) -> Mapping[str, tuple[SpanProposal, ...]]:
        ordered = tuple(sorted(contexts, key=lambda item: item.document.document_id))
        results: dict[str, tuple[SpanProposal, ...]] = {}
        if not self.config.enabled:
            for context in ordered:
                results[context.document.document_id] = ()
                self._trace(context, "dropped", "disabled", None)
            return results
        try:
            ablation = self._load_ablation_gate()
            prompt = self._load_prompt()
            metadata = self._validate_model(prompt)
            metadata = {
                **metadata,
                "ablation_checksum": ablation.checksum,
                "ablation_score_delta": ablation.score_delta,
            }
        except OllamaError as error:
            for context in ordered:
                results[context.document.document_id] = ()
                self._trace(context, "dropped", str(error), None)
            return results
        for index, context in enumerate(ordered):
            if index >= self.config.max_documents_per_batch:
                results[context.document.document_id] = ()
                self._trace(context, "dropped", "batch_limit", metadata)
            elif len(context.document.raw_text) > self.config.max_input_characters:
                results[context.document.document_id] = ()
                self._trace(context, "dropped", "input_limit", metadata)
            else:
                results[context.document.document_id] = self._propose_one(context, prompt, metadata)
        return results

    def _propose_one(
        self, context: ProposalContext, prompt: _PromptArtifact, metadata: Mapping[str, Any]
    ) -> tuple[SpanProposal, ...]:
        try:
            completion = self.generator.generate(
                self.config.model_tag,
                prompt.system_prompt,
                context.document.raw_text,
                self._options(),
                self.config.timeout_seconds,
            )
            items = _validate_completion(completion, context.document.raw_text)
        except (OllamaError, TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError):
            self._trace(context, "dropped", "invalid_or_unavailable", metadata)
            return ()
        proposals = [
            SpanProposal.create(
                context,
                self.source,
                self.version,
                "raw",
                start,
                end,
                0.5,
                (
                    ProposalEvidence(
                        "local_model",
                        "ollama",
                        self.version,
                        {
                            **metadata,
                            "evidence_label": label,
                            "provisional_type": provisional_type.value,
                        },
                    ),
                ),
            )
            for text, provisional_type, label in items
            for start, end in _exact_occurrences(context.document.raw_text, text)
        ]
        result = tuple(
            sorted(proposals, key=lambda item: (item.view_start, item.view_end, item.proposal_id))
        )
        self._trace(context, "proposed", "accepted", metadata)
        return result

    def _load_prompt(self) -> _PromptArtifact:
        try:
            raw = self.config.prompt_path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OllamaError("prompt_artifact_unavailable") from error
        if not isinstance(value, Mapping):
            raise OllamaError("invalid_prompt_artifact")
        version, system = value.get("artifact_version"), value.get("system_prompt")
        if not isinstance(version, str) or not isinstance(system, str):
            raise OllamaError("invalid_prompt_artifact")
        return _PromptArtifact(version, hashlib.sha256(raw).hexdigest(), system)

    def _load_ablation_gate(self) -> _AblationGate:
        path, expected = self.config.ablation_artifact_path, self.config.ablation_artifact_checksum
        if path is None or expected is None:
            raise OllamaError("ablation_artifact_unavailable")
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OllamaError("ablation_artifact_unavailable") from error
        checksum = hashlib.sha256(raw).hexdigest()
        if checksum != expected.lower() or not isinstance(value, Mapping):
            raise OllamaError("ablation_artifact_invalid")
        delta = value.get("score_delta")
        if (
            value.get("schema_version") != 1
            or value.get("component") != "ollama_span_proposer"
            or isinstance(delta, bool)
            or not isinstance(delta, (int, float))
            or delta <= 0
        ):
            raise OllamaError("ablation_gate_not_positive")
        return _AblationGate(checksum, float(delta))

    def _validate_model(self, prompt: _PromptArtifact) -> Mapping[str, Any]:
        try:
            response = self.generator.show(self.config.model_tag, self.config.timeout_seconds)
            digest = response.get("digest")
            effective = _effective_parameter_count(response)
        except (OllamaError, ValueError, TypeError):
            raise OllamaError("model_validation_failed") from None
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in digest)
            or effective > _MAX_PARAMETERS
        ):
            raise OllamaError("model_validation_failed")
        return {
            "declared_parameter_count": self.config.declared_parameter_count,
            "effective_parameter_count": effective,
            "endpoint_host": "127.0.0.1",
            "local_metadata_digest": digest.lower(),
            "model_tag": self.config.model_tag,
            "prompt_artifact_checksum": prompt.checksum,
            "prompt_artifact_version": prompt.version,
        }

    def _options(self) -> Mapping[str, Any]:
        options: dict[str, Any] = {"num_predict": self.config.max_output_tokens}
        if self.config.competition_mode:
            options.update({"temperature": 0, "top_p": 1, "seed": self.config.seed})
        return options

    def _trace(
        self, context: ProposalContext, action: str, reason: str, metadata: Mapping[str, Any] | None
    ) -> None:
        evidence = (
            ()
            if metadata is None
            else (ProposalEvidence("local_model", "ollama", self.version, metadata),)
        )
        self.last_trace = self.last_trace.record(
            DecisionTraceEvent.create(
                context.document.document_id,
                "proposal",
                action,
                self.source,
                self.version,
                0.0,
                evidence,
                reason,
            )
        )


def _effective_parameter_count(response: Mapping[str, Any]) -> int:
    model_info = response.get("model_info")
    if isinstance(model_info, Mapping):
        value = model_info.get("general.parameter_count")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    details = response.get("details")
    size = details.get("parameter_size") if isinstance(details, Mapping) else None
    if isinstance(size, str):
        match = re.fullmatch(r"(\d+(?:\.\d+)?)B", size)
        if match:
            return int(float(match.group(1)) * 1_000_000_000)
    raise ValueError("unverifiable_parameter_count")


def _validate_completion(
    completion: str, raw_text: str
) -> tuple[tuple[str, EntityType, str | None], ...]:
    value = json.loads(completion)
    if not isinstance(value, list):
        raise ValueError("completion_must_be_list")
    seen: set[str] = set()
    items: list[tuple[str, EntityType, str | None]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) - {
            "text",
            "provisional_type",
            "evidence_label",
        }:
            raise ValueError("invalid_completion_object")
        if not {"text", "provisional_type"} <= set(item):
            raise ValueError("missing_required_fields")
        text, type_value, label = (
            item.get("text"),
            item.get("provisional_type"),
            item.get("evidence_label"),
        )
        if not isinstance(text, str) or not text or text not in raw_text:
            raise ValueError("non_exact_mention")
        try:
            provisional_type = EntityType(type_value)
        except (TypeError, ValueError) as error:
            raise ValueError("unsupported_provisional_type") from error
        if label is not None and (not isinstance(label, str) or not _LABEL.fullmatch(label)):
            raise ValueError("invalid_evidence_label")
        canonical = json.dumps(
            dict(item), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if canonical in seen:
            raise ValueError("duplicate_proposal_object")
        seen.add(canonical)
        items.append((text, provisional_type, label))
    return tuple(items)


def _exact_occurrences(raw_text: str, text: str) -> tuple[tuple[int, int], ...]:
    return tuple((match.start(), match.end()) for match in re.finditer(re.escape(text), raw_text))
