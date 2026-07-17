from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import pytest

from medlink_ie.linking.dense import (
    CandidateMetadata,
    CandidateModelAssembly,
    DenseRetrievalRequest,
    DeterministicBiEncoder,
    DeterministicCrossEncoderReranker,
    DevicePrecisionConfig,
    InferenceResourceError,
    InMemoryVectorIndex,
    LinkingModelConfig,
    LinkingModelRegistry,
    LinkingRuntime,
    LoadedOfflineArtifact,
    VectorDocument,
    assemble_linking_runtime,
    dense_retrieve_batch,
    load_offline_artifact,
    rerank_batch,
    safe_dense_retrieve_batch,
)
from medlink_ie.provenance.manifest import ModelArtifact


def _index() -> tuple[DeterministicBiEncoder, InMemoryVectorIndex]:
    encoder = DeterministicBiEncoder(dimension=8)
    candidates = (
        CandidateMetadata("rx:1", "metoprolol", {"system": "RXNORM"}),
        CandidateMetadata("rx:2", "metoprolol succinate", {"system": "RXNORM"}),
        CandidateMetadata("icd:1", "headache", {"system": "ICD-10"}),
    )
    vectors = encoder.encode_concepts(candidates)
    return encoder, InMemoryVectorIndex(
        tuple(VectorDocument(candidate, vector) for candidate, vector in zip(candidates, vectors))
    )


def test_dense_and_reranker_batches_keep_scores_separate_and_stable() -> None:
    encoder, index = _index()
    requests = (
        DenseRetrievalRequest("a", "metoprolol", "current medication"),
        DenseRetrievalRequest("b", "headache", ""),
    )
    first = dense_retrieve_batch(requests, encoder, index, top_k=2)
    second = dense_retrieve_batch(requests, encoder, index, top_k=2)
    assert first == second
    assert len(first) == 2
    assert all(
        result.candidates
        == tuple(sorted(result.candidates, key=lambda c: (-c.raw_score, c.candidate.candidate_id)))
        for result in first
    )

    reranked = rerank_batch(first, requests, DeterministicCrossEncoderReranker())
    assert all(
        candidate.reranker_score is not None
        for result in reranked
        for candidate in result.candidates
    )
    original_scores = {
        (result.request_id, candidate.candidate.candidate_id): candidate.raw_score
        for result in first
        for candidate in result.candidates
    }
    assert all(
        candidate.raw_score
        == original_scores[(result.request_id, candidate.candidate.candidate_id)]
        for result in reranked
        for candidate in result.candidates
    )


def test_offline_artifact_validation_checks_version_checksum_and_parameter_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mock-model.bin"
    path.write_bytes(b"offline-model")
    artifact = ModelArtifact(
        "deterministic-mock",
        8,
        path,
        sha256(path.read_bytes()).hexdigest(),
        {"interface_version": "dense-v1"},
        {},
        "a" * 40,
        1,
    )
    loaded = load_offline_artifact(artifact, "dense-v1")
    assert loaded.path == path

    with pytest.raises(ValueError, match="unsupported artifact interface version"):
        load_offline_artifact(artifact, "dense-v2")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_offline_artifact(
            ModelArtifact(
                artifact.model_name,
                artifact.parameter_count,
                artifact.path,
                "0" * 64,
                artifact.training_config,
                artifact.dataset_versions,
                artifact.code_commit,
                artifact.seed,
            ),
            "dense-v1",
        )


def test_safe_oom_handling_reports_error_without_model_fallback() -> None:
    encoder, index = _index()
    request = DenseRetrievalRequest("a", "metoprolol", "")

    class OOMEncoder(DeterministicBiEncoder):
        def encode_mentions(
            self, requests: tuple[DenseRetrievalRequest, ...]
        ) -> tuple[tuple[float, ...], ...]:
            raise InferenceResourceError("out of memory")

    outcome = safe_dense_retrieve_batch((request,), OOMEncoder(dimension=8), index, top_k=1)
    assert outcome.results == ()
    assert outcome.errors[0].request_id == "a"
    assert outcome.errors[0].stage == "dense_retrieval"


def test_device_precision_configuration_is_explicit() -> None:
    assert DevicePrecisionConfig(device="cpu", precision="float32").device == "cpu"
    with pytest.raises(ValueError, match="float16"):
        DevicePrecisionConfig(device="cpu", precision="float16")


def test_config_switches_registered_models_without_changing_runtime_orchestration(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "model.bin"
    artifact_path.write_bytes(b"offline-model")
    artifact = ModelArtifact(
        "test-model",
        8,
        artifact_path,
        sha256(artifact_path.read_bytes()).hexdigest(),
        {"interface_version": "dense-v1"},
        {},
        "a" * 40,
        1,
    )
    selected: list[str] = []

    def make_encoder(
        name: str,
    ) -> Callable[[LoadedOfflineArtifact, DevicePrecisionConfig], DeterministicBiEncoder]:
        def factory(
            _artifact: LoadedOfflineArtifact, _execution: DevicePrecisionConfig
        ) -> DeterministicBiEncoder:
            selected.append(name)
            return DeterministicBiEncoder(dimension=8)

        return factory

    registry = LinkingModelRegistry(
        bi_encoder_factories={"first": make_encoder("first"), "second": make_encoder("second")},
        reranker_factories={
            "mock": lambda _artifact, _execution: DeterministicCrossEncoderReranker()
        },
    )
    encoder, index = _index()
    del encoder
    request = DenseRetrievalRequest("a", "metoprolol", "current medication")

    for key in ("first", "second"):
        runtime = assemble_linking_runtime(
            LinkingModelConfig(
                bi_encoder=CandidateModelAssembly(key, artifact, "dense-v1"),
                reranker=CandidateModelAssembly("mock", artifact, "dense-v1"),
            ),
            registry,
        )
        assert isinstance(runtime, LinkingRuntime)
        assert runtime.retrieve_and_rerank((request,), index, top_k=1)[0].request_id == "a"

    assert selected == ["first", "second"]
