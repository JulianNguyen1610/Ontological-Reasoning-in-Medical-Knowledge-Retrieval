"""Offline, model-agnostic dense retrieval and cross-encoder reranking contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import sqrt
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from medlink_ie.provenance.manifest import ModelArtifact


@dataclass(frozen=True, slots=True)
class DevicePrecisionConfig:
    """Explicit execution settings; callers must not silently change these."""

    device: str = "cpu"
    precision: str = "float32"

    def __post_init__(self) -> None:
        if not self.device or not isinstance(self.device, str):
            raise ValueError("device must be a non-empty string")
        if self.precision not in {"float32", "float16", "bfloat16"}:
            raise ValueError("unsupported precision")
        if self.device == "cpu" and self.precision != "float32":
            raise ValueError("float16 and bfloat16 are not supported on cpu")


@dataclass(frozen=True, slots=True)
class CandidateMetadata:
    """Candidate identity and local metadata; no code is synthesized here."""

    candidate_id: str
    display_text: str
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.display_text:
            raise ValueError("candidate_id and display_text must be non-empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class DenseRetrievalRequest:
    request_id: str
    mention: str
    local_context: str
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must be non-empty")
        if not isinstance(self.mention, str) or not isinstance(self.local_context, str):
            raise TypeError("mention and local_context must be strings")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


Vector = tuple[float, ...]


@runtime_checkable
class MentionEncoder(Protocol):
    """Encode mention plus local context without retrieval orchestration knowledge."""

    def encode_mentions(self, requests: tuple[DenseRetrievalRequest, ...]) -> tuple[Vector, ...]:
        """Return one vector per request in input order."""


@runtime_checkable
class ConceptEncoder(Protocol):
    """Encode source-backed candidate metadata into dense vectors."""

    def encode_concepts(self, candidates: tuple[CandidateMetadata, ...]) -> tuple[Vector, ...]:
        """Return one vector per candidate in input order."""


@runtime_checkable
class BiEncoder(MentionEncoder, ConceptEncoder, Protocol):
    """A replaceable paired mention/concept encoder implementation."""


@runtime_checkable
class VectorIndex(Protocol):
    """Search an already-built local vector index."""

    def search(
        self, vectors: tuple[Vector, ...], top_k: int
    ) -> tuple[tuple["DenseCandidate", ...], ...]:
        """Return stable raw-score candidates for every input vector."""


@runtime_checkable
class CrossEncoderReranker(Protocol):
    """Score mention/context and candidate metadata pairs in batches."""

    def score(
        self,
        pairs: tuple[tuple[DenseRetrievalRequest, CandidateMetadata], ...],
    ) -> tuple[float, ...]:
        """Return one reranker score per input pair in input order."""


@dataclass(frozen=True, slots=True)
class DenseCandidate:
    candidate: CandidateMetadata
    raw_score: float
    reranker_score: float | None = None


@dataclass(frozen=True, slots=True)
class DenseRetrievalResult:
    request_id: str
    candidates: tuple[DenseCandidate, ...]


@dataclass(frozen=True, slots=True)
class BatchInferenceError:
    request_id: str
    stage: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class DenseBatchOutcome:
    results: tuple[DenseRetrievalResult, ...]
    errors: tuple[BatchInferenceError, ...]


@dataclass(frozen=True, slots=True)
class LoadedOfflineArtifact:
    model_name: str
    path: Path
    checksum_sha256: str
    interface_version: str
    parameter_count: int | None
    execution: DevicePrecisionConfig


BiEncoderFactory = Callable[[LoadedOfflineArtifact, DevicePrecisionConfig], BiEncoder]
RerankerFactory = Callable[[LoadedOfflineArtifact, DevicePrecisionConfig], CrossEncoderReranker]


@dataclass(frozen=True, slots=True)
class CandidateModelAssembly:
    """Configurable, verified model selection for one linking stage."""

    implementation_key: str
    artifact: ModelArtifact
    interface_version: str
    execution: DevicePrecisionConfig = DevicePrecisionConfig()

    def __post_init__(self) -> None:
        if not self.implementation_key:
            raise ValueError("implementation_key must be non-empty")
        if not self.interface_version:
            raise ValueError("interface_version must be non-empty")


@dataclass(frozen=True, slots=True)
class LinkingModelConfig:
    """All model-specific choices consumed at the linking composition boundary."""

    bi_encoder: CandidateModelAssembly
    reranker: CandidateModelAssembly


@dataclass(frozen=True, slots=True)
class LinkingModelRegistry:
    """Explicit local implementations available to configuration-driven assembly."""

    bi_encoder_factories: Mapping[str, BiEncoderFactory]
    reranker_factories: Mapping[str, RerankerFactory]

    def __post_init__(self) -> None:
        if not self.bi_encoder_factories or not self.reranker_factories:
            raise ValueError("both model factory registries must be non-empty")
        object.__setattr__(
            self, "bi_encoder_factories", MappingProxyType(dict(self.bi_encoder_factories))
        )
        object.__setattr__(
            self, "reranker_factories", MappingProxyType(dict(self.reranker_factories))
        )


@dataclass(frozen=True, slots=True)
class LinkingRuntime:
    """Model-independent linking orchestration assembled from verified config."""

    bi_encoder: BiEncoder
    reranker: CrossEncoderReranker

    def retrieve_and_rerank(
        self,
        requests: tuple[DenseRetrievalRequest, ...],
        index: VectorIndex,
        *,
        top_k: int,
    ) -> tuple[DenseRetrievalResult, ...]:
        """Run the stable dense-to-rerank path without implementation knowledge."""
        retrieved = dense_retrieve_batch(requests, self.bi_encoder, index, top_k=top_k)
        return rerank_batch(retrieved, requests, self.reranker)


class InferenceResourceError(RuntimeError):
    """Raised by an implementation when its configured resources are insufficient."""


@dataclass(frozen=True, slots=True)
class VectorDocument:
    candidate: CandidateMetadata
    vector: Vector

    def __post_init__(self) -> None:
        _validate_vector(self.vector)


class InMemoryVectorIndex:
    """Deterministic local dot-product index for integration tests and small fixtures."""

    def __init__(self, documents: tuple[VectorDocument, ...]) -> None:
        if not documents:
            raise ValueError("documents must not be empty")
        dimension = len(documents[0].vector)
        if any(len(document.vector) != dimension for document in documents):
            raise ValueError("all vectors must have the same dimension")
        if len({document.candidate.candidate_id for document in documents}) != len(documents):
            raise ValueError("candidate ids must be unique")
        self._documents = tuple(sorted(documents, key=lambda item: item.candidate.candidate_id))
        self._dimension = dimension

    def search(
        self, vectors: tuple[Vector, ...], top_k: int
    ) -> tuple[tuple[DenseCandidate, ...], ...]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        for vector in vectors:
            _validate_vector(vector)
            if len(vector) != self._dimension:
                raise ValueError("query vector dimension does not match index")
        return tuple(
            tuple(
                DenseCandidate(document.candidate, _dot(vector, document.vector))
                for document in sorted(
                    self._documents,
                    key=lambda item: (-_dot(vector, item.vector), item.candidate.candidate_id),
                )[:top_k]
            )
            for vector in vectors
        )


class DeterministicBiEncoder:
    """Hash-based test double implementing both encoder protocols without model I/O."""

    def __init__(
        self, dimension: int = 16, config: DevicePrecisionConfig = DevicePrecisionConfig()
    ) -> None:
        if dimension < 1:
            raise ValueError("dimension must be positive")
        self.dimension = dimension
        self.config = config

    def encode_mentions(self, requests: tuple[DenseRetrievalRequest, ...]) -> tuple[Vector, ...]:
        return tuple(
            _hashed_vector(request.mention + "\n" + request.local_context, self.dimension)
            for request in requests
        )

    def encode_concepts(self, candidates: tuple[CandidateMetadata, ...]) -> tuple[Vector, ...]:
        return tuple(
            _hashed_vector(
                candidate.display_text + "\n" + _metadata_text(candidate.metadata), self.dimension
            )
            for candidate in candidates
        )


class DeterministicCrossEncoderReranker:
    """Token-overlap test double retaining raw retrieval scores externally."""

    def __init__(self, config: DevicePrecisionConfig = DevicePrecisionConfig()) -> None:
        self.config = config

    def score(
        self,
        pairs: tuple[tuple[DenseRetrievalRequest, CandidateMetadata], ...],
    ) -> tuple[float, ...]:
        return tuple(
            _token_overlap(request.mention + " " + request.local_context, candidate.display_text)
            for request, candidate in pairs
        )


def load_offline_artifact(
    artifact: ModelArtifact,
    required_interface_version: str,
    execution: DevicePrecisionConfig = DevicePrecisionConfig(),
) -> LoadedOfflineArtifact:
    """Validate a local artifact before implementation-specific loading occurs."""
    if not required_interface_version:
        raise ValueError("required_interface_version must be non-empty")
    artifact.validate(verify_path=True)
    version = artifact.training_config.get("interface_version")
    if version != required_interface_version:
        raise ValueError(f"unsupported artifact interface version: {version}")
    return LoadedOfflineArtifact(
        artifact.model_name,
        artifact.path,
        artifact.checksum_sha256,
        required_interface_version,
        artifact.parameter_count,
        execution,
    )


def assemble_linking_runtime(
    config: LinkingModelConfig,
    registry: LinkingModelRegistry,
) -> LinkingRuntime:
    """Construct configured local linking models without exposing them to orchestration."""
    bi_encoder = _build_bi_encoder(config.bi_encoder, registry)
    reranker = _build_reranker(config.reranker, registry)
    return LinkingRuntime(bi_encoder, reranker)


def dense_retrieve_batch(
    requests: tuple[DenseRetrievalRequest, ...],
    encoder: MentionEncoder,
    index: VectorIndex,
    *,
    top_k: int,
) -> tuple[DenseRetrievalResult, ...]:
    """Run model-agnostic dense retrieval while preserving raw vector scores."""
    if top_k < 1:
        raise ValueError("top_k must be positive")
    vectors = encoder.encode_mentions(requests)
    if len(vectors) != len(requests):
        raise ValueError("mention encoder returned an unexpected vector count")
    candidates = index.search(vectors, top_k)
    if len(candidates) != len(requests):
        raise ValueError("vector index returned an unexpected result count")
    return tuple(
        DenseRetrievalResult(request.request_id, _sorted_raw(result))
        for request, result in zip(requests, candidates)
    )


def safe_dense_retrieve_batch(
    requests: tuple[DenseRetrievalRequest, ...],
    encoder: MentionEncoder,
    index: VectorIndex,
    *,
    top_k: int,
) -> DenseBatchOutcome:
    """Return an explicit resource error; never change device, precision, or model."""
    try:
        return DenseBatchOutcome(dense_retrieve_batch(requests, encoder, index, top_k=top_k), ())
    except (InferenceResourceError, MemoryError) as error:
        return DenseBatchOutcome(
            (),
            tuple(
                BatchInferenceError(
                    request.request_id,
                    "dense_retrieval",
                    type(error).__name__,
                    str(error),
                )
                for request in requests
            ),
        )


def rerank_batch(
    retrieval: tuple[DenseRetrievalResult, ...],
    requests: tuple[DenseRetrievalRequest, ...],
    reranker: CrossEncoderReranker,
) -> tuple[DenseRetrievalResult, ...]:
    """Attach separate reranker scores to existing dense candidates in stable order."""
    request_by_id = {request.request_id: request for request in requests}
    if len(request_by_id) != len(requests):
        raise ValueError("request ids must be unique")
    pairs = tuple(
        (request_by_id[result.request_id], candidate.candidate)
        for result in retrieval
        for candidate in result.candidates
        if result.request_id in request_by_id
    )
    if any(result.request_id not in request_by_id for result in retrieval):
        raise ValueError("retrieval contains an unknown request id")
    scores = reranker.score(pairs)
    if len(scores) != len(pairs):
        raise ValueError("reranker returned an unexpected score count")
    iterator = iter(scores)
    reranked = []
    for result in retrieval:
        candidates = tuple(
            DenseCandidate(candidate.candidate, candidate.raw_score, next(iterator))
            for candidate in result.candidates
        )
        reranked.append(DenseRetrievalResult(result.request_id, _sorted_reranked(candidates)))
    return tuple(reranked)


def _sorted_raw(candidates: Sequence[DenseCandidate]) -> tuple[DenseCandidate, ...]:
    return tuple(
        sorted(candidates, key=lambda item: (-item.raw_score, item.candidate.candidate_id))
    )


def _build_bi_encoder(
    selection: CandidateModelAssembly,
    registry: LinkingModelRegistry,
) -> BiEncoder:
    artifact = load_offline_artifact(
        selection.artifact, selection.interface_version, selection.execution
    )
    try:
        factory = registry.bi_encoder_factories[selection.implementation_key]
    except KeyError as error:
        raise ValueError(
            f"unknown bi-encoder implementation: {selection.implementation_key}"
        ) from error
    implementation = factory(artifact, selection.execution)
    if not isinstance(implementation, BiEncoder):
        raise TypeError("bi-encoder factory returned an invalid implementation")
    return implementation


def _build_reranker(
    selection: CandidateModelAssembly,
    registry: LinkingModelRegistry,
) -> CrossEncoderReranker:
    artifact = load_offline_artifact(
        selection.artifact, selection.interface_version, selection.execution
    )
    try:
        factory = registry.reranker_factories[selection.implementation_key]
    except KeyError as error:
        raise ValueError(
            f"unknown reranker implementation: {selection.implementation_key}"
        ) from error
    implementation = factory(artifact, selection.execution)
    if not isinstance(implementation, CrossEncoderReranker):
        raise TypeError("reranker factory returned an invalid implementation")
    return implementation


def _sorted_reranked(candidates: Sequence[DenseCandidate]) -> tuple[DenseCandidate, ...]:
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                -(item.reranker_score if item.reranker_score is not None else float("-inf")),
                -item.raw_score,
                item.candidate.candidate_id,
            ),
        )
    )


def _hashed_vector(text: str, dimension: int) -> Vector:
    values = []
    for index in range(dimension):
        digest = sha256(f"{index}:{text}".encode("utf-8")).digest()
        values.append((int.from_bytes(digest[:8], "big") / 2**63) - 1.0)
    norm = sqrt(sum(value * value for value in values))
    return tuple(value / norm for value in values)


def _metadata_text(metadata: Mapping[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in sorted(metadata.items()))


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.casefold().split())
    right_tokens = set(right.casefold().split())
    return (
        len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
        if left_tokens or right_tokens
        else 0.0
    )


def _dot(left: Vector, right: Vector) -> float:
    return sum(a * b for a, b in zip(left, right))


def _validate_vector(vector: Vector) -> None:
    if not vector or any(not isinstance(value, float) for value in vector):
        raise ValueError("vectors must contain at least one float")
