"""Config-selected, local-only encoder interfaces for span/type benchmarking.

This module emits exact span candidates and uncalibrated type logits. Thresholds,
calibration, and final entity construction intentionally belong to later stages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, runtime_checkable

from medlink_ie.annotation.gold import GoldEntity, GoldSample, validate_gold_sample
from medlink_ie.dataset import SplitResult
from medlink_ie.domain import EntityType
from medlink_ie.provenance.manifest import ModelArtifact
from medlink_ie.training import DatasetManifest, TrainingArtifact, TrainingConfig

_INTERFACE_VERSION = "encoder-span-type-v1"
_CONFUSIONS = (
    (EntityType.SYMPTOM, EntityType.DIAGNOSIS),
    (EntityType.TEST_NAME, EntityType.TEST_RESULT),
    (EntityType.MEDICATION, EntityType.DIAGNOSIS),
)


@dataclass(frozen=True, slots=True)
class SubwordToken:
    """One tokenizer piece with an explicit interval in untouched raw text."""

    piece: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.piece or not 0 <= self.start < self.end:
            raise ValueError("subword token requires a non-empty ordered raw-text interval")


@runtime_checkable
class OffsetTokenizer(Protocol):
    """Local tokenizer contract; every Vietnamese subword must retain raw offsets."""

    def tokenize(self, text: str) -> tuple[SubwordToken, ...]: ...


@dataclass(frozen=True, slots=True)
class GroundedMention:
    """A mention supplied by the upstream grounding stage before type scoring."""

    mention_id: str
    start: int
    end: int
    text: str

    def validate(self, raw_text: str) -> None:
        if not self.mention_id or not 0 <= self.start < self.end <= len(raw_text):
            raise ValueError("grounded mention has invalid raw-text boundaries")
        if raw_text[self.start : self.end] != self.text:
            raise ValueError("grounded mention text must equal raw_text[start:end]")


@dataclass(frozen=True, slots=True)
class SpanTypeInput:
    sample_id: str
    raw_text: str
    grounded_mentions: tuple[GroundedMention, ...]
    local_structural_context: str

    def __post_init__(self) -> None:
        if not self.sample_id or not self.local_structural_context:
            raise ValueError("sample_id and local_structural_context must be non-empty")
        mentions = tuple(self.grounded_mentions)
        if len({mention.mention_id for mention in mentions}) != len(mentions):
            raise ValueError("grounded mention IDs must be unique per input")
        for mention in mentions:
            mention.validate(self.raw_text)
        object.__setattr__(self, "grounded_mentions", mentions)


@dataclass(frozen=True, slots=True)
class SpanCandidate:
    sample_id: str
    mention_id: str
    start: int
    end: int
    text: str
    raw_span_logit: float


@dataclass(frozen=True, slots=True)
class EncoderRawOutput:
    """Batch output before calibration, thresholding, fusion, or entity decisions."""

    candidates: tuple[SpanCandidate, ...]
    raw_logits: Mapping[str, Mapping[str, Mapping[EntityType, float]]]

    def __post_init__(self) -> None:
        logits = {
            sample_id: MappingProxyType(
                {
                    mention_id: MappingProxyType(dict(values))
                    for mention_id, values in mentions.items()
                }
            )
            for sample_id, mentions in self.raw_logits.items()
        }
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            for mentions in logits.values()
            for values in mentions.values()
            for value in values.values()
        ):
            raise TypeError("raw logits must be numeric")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "raw_logits", MappingProxyType(logits))


@runtime_checkable
class EncoderBackbone(Protocol):
    """Inference-only adapter kept separate from training-framework dependencies."""

    parameter_count: int

    def predict_span_candidates(
        self, tokens: tuple[SubwordToken, ...], raw_text: str
    ) -> tuple[tuple[int, int, float], ...]: ...

    def predict_logits(
        self, tokens: tuple[SubwordToken, ...], mention: GroundedMention, context: str
    ) -> Mapping[EntityType, float]: ...


@dataclass(frozen=True, slots=True)
class EncoderSpanTypeConfig:
    implementation_key: str
    model_artifact: ModelArtifact
    tokenizer_path: Path
    tokenizer_checksum_sha256: str
    max_subwords: int = 512

    def __post_init__(self) -> None:
        if not self.implementation_key:
            raise ValueError("implementation_key must be non-empty")
        if not 1 <= self.max_subwords:
            raise ValueError("max_subwords must be positive")
        if len(self.tokenizer_checksum_sha256) != 64:
            raise ValueError("tokenizer checksum must be a SHA-256 hex digest")
        object.__setattr__(self, "tokenizer_path", Path(self.tokenizer_path))


class EncoderSpanTypeModel:
    def __init__(
        self, config: EncoderSpanTypeConfig, tokenizer: OffsetTokenizer, backbone: EncoderBackbone
    ) -> None:
        self.config = config
        self.tokenizer = tokenizer
        self.backbone = backbone

    def predict_batch(self, batch: tuple[SpanTypeInput, ...]) -> EncoderRawOutput:
        """Emit backbone span candidates and type logits without thresholding."""
        candidates: list[SpanCandidate] = []
        logits: dict[str, dict[str, Mapping[EntityType, float]]] = {}
        for item in sorted(batch, key=lambda value: value.sample_id):
            tokens = self.tokenizer.tokenize(item.raw_text)
            _validate_token_alignment(item.raw_text, tokens, self.config.max_subwords)
            per_mention: dict[str, Mapping[EntityType, float]] = {}
            spans = self.backbone.predict_span_candidates(tokens, item.raw_text)
            for start, end, span_logit in sorted(spans, key=lambda value: (value[0], value[1])):
                if not 0 <= start < end <= len(item.raw_text):
                    raise ValueError("backbone emitted invalid raw span boundaries")
                mention = GroundedMention(
                    f"encoder:{start}:{end}", start, end, item.raw_text[start:end]
                )
                candidates.append(
                    SpanCandidate(
                        item.sample_id,
                        mention.mention_id,
                        mention.start,
                        mention.end,
                        mention.text,
                        span_logit,
                    )
                )
                per_mention[mention.mention_id] = self.backbone.predict_logits(
                    tokens, mention, item.local_structural_context
                )
            logits[item.sample_id] = per_mention
        return EncoderRawOutput(tuple(candidates), logits)


EncoderFactory = Callable[[EncoderSpanTypeConfig], tuple[OffsetTokenizer, EncoderBackbone]]


@runtime_checkable
class EncoderTrainer(Protocol):
    """Optional training adapter; inference remains free of trainer dependencies."""

    def train(self, config: TrainingConfig, dataset: "GroupedTrainingData") -> TrainingArtifact: ...


EncoderTrainerFactory = Callable[[EncoderSpanTypeConfig], EncoderTrainer]


@dataclass(frozen=True, slots=True)
class EncoderModelRegistry:
    factories: Mapping[str, EncoderFactory]

    def __post_init__(self) -> None:
        if not self.factories:
            raise ValueError("encoder registry must not be empty")
        object.__setattr__(self, "factories", MappingProxyType(dict(self.factories)))

    def build(self, config: EncoderSpanTypeConfig) -> EncoderSpanTypeModel:
        if config.implementation_key not in self.factories:
            raise ValueError(f"unknown encoder implementation: {config.implementation_key}")
        if not config.tokenizer_path.is_file():
            raise FileNotFoundError("local tokenizer is required; automatic download is disabled")
        if _checksum(config.tokenizer_path) != config.tokenizer_checksum_sha256:
            raise ValueError("tokenizer checksum verification failed")
        config.model_artifact.validate(verify_path=True)
        if config.model_artifact.training_config.get("interface_version") != _INTERFACE_VERSION:
            raise ValueError("unsupported encoder model interface version")
        tokenizer, backbone = self.factories[config.implementation_key](config)
        if backbone.parameter_count != config.model_artifact.parameter_count:
            raise ValueError("backbone parameter_count differs from model artifact")
        return EncoderSpanTypeModel(config, tokenizer, backbone)


@dataclass(frozen=True, slots=True)
class EncoderTrainingRegistry:
    """Configuration-driven training selection; no model implementation is hard-coded."""

    factories: Mapping[str, EncoderTrainerFactory]

    def train(
        self,
        model_config: EncoderSpanTypeConfig,
        training_config: TrainingConfig,
        dataset: "GroupedTrainingData",
    ) -> TrainingArtifact:
        factory = self.factories.get(model_config.implementation_key)
        if factory is None:
            raise ValueError(
                f"unknown encoder training implementation: {model_config.implementation_key}"
            )
        artifact = factory(model_config).train(training_config, dataset)
        if artifact.dataset_manifest != dataset.dataset_manifest:
            raise ValueError(
                "encoder trainer returned an artifact for a different dataset manifest"
            )
        return artifact


@dataclass(frozen=True, slots=True)
class TrainingExample:
    sample_id: str
    raw_text: str
    entities: tuple[GoldEntity, ...]


@dataclass(frozen=True, slots=True)
class GroupedTrainingData:
    examples: tuple[TrainingExample, ...]
    dataset_manifest: DatasetManifest


def build_grouped_training_data(
    split_result: SplitResult, annotations: Mapping[str, GoldSample]
) -> GroupedTrainingData:
    """Build training inputs exclusively from a verified grouped train split."""
    if split_result.leakage_report.group_leaks or split_result.leakage_report.exact_duplicates:
        raise ValueError("grouped split contains leakage and cannot be used for training")
    train_records = split_result.splits["train"]
    examples: list[TrainingExample] = []
    for record in train_records:
        sample = annotations.get(record.record_id)
        if sample is None or sample.raw_text != record.text:
            raise ValueError(
                f"missing or mismatched annotation for train record {record.record_id}"
            )
        validation = validate_gold_sample(sample)
        if not validation.is_valid:
            raise ValueError(
                f"invalid annotation for {record.record_id}: {validation.errors[0].message}"
            )
        examples.append(TrainingExample(record.record_id, record.text, sample.entities))
    manifest = DatasetManifest(
        split_checksums=split_result.manifest.split_checksums,
        split_record_ids=split_result.manifest.split_record_ids,
    )
    return GroupedTrainingData(tuple(sorted(examples, key=lambda value: value.sample_id)), manifest)


@dataclass(frozen=True, slots=True)
class HardNegative:
    source_type: EntityType
    negative_type: EntityType
    source_start: int
    negative_start: int


def sample_hard_negatives(entities: tuple[GoldEntity, ...], seed: int) -> tuple[HardNegative, ...]:
    """Deterministically pair required cross-type confusions without test data."""
    del seed
    negatives: list[HardNegative] = []
    for source, negative in _CONFUSIONS:
        source_entities = [entity for entity in entities if entity.type is source]
        negative_entities = [entity for entity in entities if entity.type is negative]
        for left, right in zip(source_entities, negative_entities, strict=False):
            negatives.append(HardNegative(source, negative, left.start, right.start))
    return tuple(
        sorted(
            negatives,
            key=lambda value: (value.source_type.value, value.source_start, value.negative_start),
        )
    )


@dataclass(frozen=True, slots=True)
class SpanTypeMetrics:
    exact_span_precision: float
    exact_span_recall: float
    exact_span_f1: float
    type_f1: float
    true_positive: int
    false_positive: int
    false_negative: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class FoldSeedBenchmark:
    fold_id: str
    seed: int
    encoder: SpanTypeMetrics
    baseline: SpanTypeMetrics


@dataclass(frozen=True, slots=True)
class BenchmarkDeltaReport:
    run_count: int
    mean_encoder_exact_span_f1: float
    mean_baseline_exact_span_f1: float
    mean_delta_exact_span_f1: float


def aggregate_fold_seed_benchmarks(runs: tuple[FoldSeedBenchmark, ...]) -> BenchmarkDeltaReport:
    """Aggregate fixed fold/seed benchmark results without tuning or refitting."""
    if not runs or len({(run.fold_id, run.seed) for run in runs}) != len(runs):
        raise ValueError("benchmarks require unique non-empty fold/seed runs")
    if any(not run.fold_id or run.seed < 0 for run in runs):
        raise ValueError("benchmarks require non-empty folds and non-negative seeds")
    encoder = sum(run.encoder.exact_span_f1 for run in runs) / len(runs)
    baseline = sum(run.baseline.exact_span_f1 for run in runs) / len(runs)
    return BenchmarkDeltaReport(len(runs), encoder, baseline, encoder - baseline)


def write_span_type_report(path: Path, metrics: SpanTypeMetrics) -> Path:
    """Persist a deterministic local benchmark report without overwriting prior results."""
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing metrics report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(metrics.to_json() + "\n", encoding="utf-8")
    return path


def evaluate_span_type(
    gold: Mapping[str, tuple[GoldEntity, ...]], predicted: Mapping[str, tuple[GoldEntity, ...]]
) -> SpanTypeMetrics:
    """Deterministic exact-boundary/type evaluation for pre-threshold benchmark outputs."""
    if set(gold) != set(predicted):
        raise ValueError("gold and prediction sample IDs must match")
    gold_spans = {
        (sample_id, item.start, item.end) for sample_id, items in gold.items() for item in items
    }
    predicted_spans = {
        (sample_id, item.start, item.end)
        for sample_id, items in predicted.items()
        for item in items
    }
    typed_gold = {
        (sample_id, item.start, item.end, item.type)
        for sample_id, items in gold.items()
        for item in items
    }
    typed_predicted = {
        (sample_id, item.start, item.end, item.type)
        for sample_id, items in predicted.items()
        for item in items
    }
    precision = _ratio(len(predicted_spans & gold_spans), len(predicted_spans))
    recall = _ratio(len(predicted_spans & gold_spans), len(gold_spans))
    return SpanTypeMetrics(
        precision,
        recall,
        _f1(precision, recall),
        _f1(
            _ratio(len(typed_predicted & typed_gold), len(typed_predicted)),
            _ratio(len(typed_predicted & typed_gold), len(typed_gold)),
        ),
        len(typed_predicted & typed_gold),
        len(typed_predicted - typed_gold),
        len(typed_gold - typed_predicted),
    )


def _validate_token_alignment(
    raw_text: str, tokens: tuple[SubwordToken, ...], max_subwords: int
) -> None:
    if len(tokens) > max_subwords:
        raise ValueError("tokenized input exceeds configured max_subwords")
    previous_end = 0
    for token in tokens:
        if token.end > len(raw_text) or token.start < previous_end:
            raise ValueError("tokenizer offsets must be ordered raw-text intervals")
        previous_end = token.end


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else numerator / denominator


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
