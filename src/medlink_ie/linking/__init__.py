"""Model-agnostic dense retrieval and reranking interfaces."""

from .candidate_fusion import (
    CandidateInput,
    CandidateSelection,
    CandidateSetOracleAnalysis,
    CandidateSetOracleObservation,
    FusionConfig,
    StructuredFeatures,
    evaluate_candidate_set_oracle,
)
from .dense import (
    BiEncoder,
    CandidateMetadata,
    CandidateModelAssembly,
    ConceptEncoder,
    CrossEncoderReranker,
    DenseRetrievalRequest,
    DevicePrecisionConfig,
    LinkingModelConfig,
    LinkingModelRegistry,
    LinkingRuntime,
    MentionEncoder,
    VectorIndex,
    assemble_linking_runtime,
)

__all__ = [
    "BiEncoder",
    "CandidateModelAssembly",
    "CandidateMetadata",
    "CandidateInput",
    "CandidateSelection",
    "CandidateSetOracleAnalysis",
    "CandidateSetOracleObservation",
    "ConceptEncoder",
    "CrossEncoderReranker",
    "DenseRetrievalRequest",
    "DevicePrecisionConfig",
    "FusionConfig",
    "LinkingModelConfig",
    "LinkingModelRegistry",
    "LinkingRuntime",
    "MentionEncoder",
    "StructuredFeatures",
    "VectorIndex",
    "assemble_linking_runtime",
    "evaluate_candidate_set_oracle",
]
