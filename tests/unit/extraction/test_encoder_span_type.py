from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from medlink_ie.annotation.gold import AdjudicationStatus, GoldEntity, GoldSample
from medlink_ie.dataset import DatasetRecord, SplitConfig, create_grouped_splits
from medlink_ie.domain import EntityType
from medlink_ie.extraction.encoder_span_type import (
    EncoderModelRegistry,
    EncoderSpanTypeConfig,
    FoldSeedBenchmark,
    GroundedMention,
    SpanTypeInput,
    SubwordToken,
    aggregate_fold_seed_benchmarks,
    build_grouped_training_data,
    evaluate_span_type,
    sample_hard_negatives,
    write_span_type_report,
)
from medlink_ie.extraction.huggingface_token_classifier import (
    HuggingFaceOffsetTokenizer,
    HuggingFaceTokenClassifierBackbone,
)
from medlink_ie.provenance.manifest import ModelArtifact


@dataclass(frozen=True, slots=True)
class _MockTokenizer:
    def tokenize(self, text: str) -> tuple[SubwordToken, ...]:
        return (SubwordToken("đau", 0, 3), SubwordToken("##ngực", 4, 8))


@dataclass(frozen=True, slots=True)
class _MockBackbone:
    parameter_count: int = 7

    def predict_span_candidates(
        self, tokens: tuple[SubwordToken, ...], raw_text: str
    ) -> tuple[tuple[int, int, float], ...]:
        raw_text = raw_text.encode("utf-8").decode("latin1").replace("\x91", "\u2018")
        assert raw_text == "Ä‘au ngá»±c"
        return ((0, 8, 1.5),)

    def predict_logits(
        self, tokens: tuple[SubwordToken, ...], mention: GroundedMention, context: str
    ) -> dict[EntityType, float]:
        assert tokens[0].start == 0 and tokens[-1].end == 8
        assert mention.text == "đau ngực"
        assert context == "current_exam"
        return {EntityType.SYMPTOM: 2.0, EntityType.DIAGNOSIS: -1.0}


def _config(tmp_path: Path) -> EncoderSpanTypeConfig:
    model = tmp_path / "model.bin"
    tokenizer = tmp_path / "tokenizer.json"
    model.write_bytes(b"model")
    tokenizer.write_bytes(b"tokenizer")
    return EncoderSpanTypeConfig(
        implementation_key="mock",
        model_artifact=ModelArtifact(
            "tiny-encoder",
            7,
            model,
            sha256(model.read_bytes()).hexdigest(),
            {"interface_version": "encoder-span-type-v1"},
            {"train": "t", "dev": "d", "test": "e"},
            "abc123",
            3,
        ),
        tokenizer_path=tokenizer,
        tokenizer_checksum_sha256=sha256(tokenizer.read_bytes()).hexdigest(),
    )


def test_config_selected_encoder_outputs_unthresholded_candidates_and_logits(
    tmp_path: Path,
) -> None:
    model = EncoderModelRegistry(
        {"mock": lambda _config: (_MockTokenizer(), _MockBackbone())}
    ).build(_config(tmp_path))
    output = model.predict_batch(
        (
            SpanTypeInput(
                "s1",
                "đau ngực",
                (GroundedMention("g1", 0, 8, "đau ngực"),),
                "current_exam",
            ),
        )
    )

    assert output.candidates[0].start == 0
    assert output.candidates[0].end == 8
    assert output.candidates[0].text == "đau ngực"
    assert output.candidates[0].raw_span_logit == 1.5
    assert output.raw_logits["s1"]["encoder:0:8"][EntityType.SYMPTOM] == 2.0


def test_grouped_training_data_is_train_only_and_checks_exact_annotation_boundaries() -> None:
    split = create_grouped_splits(
        (
            DatasetRecord("train", "đau ngực", {"scenario_id": "a"}),
            DatasetRecord("dev", "sốt", {"scenario_id": "b"}),
            DatasetRecord("test", "ho", {"scenario_id": "c"}),
        ),
        SplitConfig(seed=1, proportions=(0.34, 0.33, 0.33), group_fields=("scenario_id",)),
    )
    annotations = {
        record_id: GoldSample(
            record_id,
            text,
            None,
            (
                GoldEntity(
                    text,
                    0,
                    len(text),
                    EntityType.SYMPTOM,
                    adjudication_status=AdjudicationStatus.CONFIRMED,
                ),
            ),
            AdjudicationStatus.CONFIRMED,
        )
        for record_id, text in (("train", "đau ngực"), ("dev", "sốt"), ("test", "ho"))
    }

    training = build_grouped_training_data(split, annotations)

    assert {example.sample_id for example in training.examples} == set(
        split.manifest.split_record_ids["train"]
    )
    assert training.dataset_manifest.split_checksums == split.manifest.split_checksums


def test_hard_negatives_cover_required_confusions_and_metrics_are_deterministic(
    tmp_path: Path,
) -> None:
    entities = (
        GoldEntity("đau", 0, 3, EntityType.SYMPTOM),
        GoldEntity("viêm", 4, 8, EntityType.DIAGNOSIS),
        GoldEntity("AST", 9, 12, EntityType.TEST_NAME),
        GoldEntity("cao", 13, 16, EntityType.TEST_RESULT),
        GoldEntity("aspirin", 17, 24, EntityType.MEDICATION),
    )
    negatives = sample_hard_negatives(entities, seed=9)
    pairs = {(item.source_type, item.negative_type) for item in negatives}
    assert (EntityType.SYMPTOM, EntityType.DIAGNOSIS) in pairs
    assert (EntityType.TEST_NAME, EntityType.TEST_RESULT) in pairs
    assert (EntityType.MEDICATION, EntityType.DIAGNOSIS) in pairs

    report = evaluate_span_type({"s": entities}, {"s": entities})
    assert report.exact_span_f1 == 1.0
    assert report.type_f1 == 1.0
    assert write_span_type_report(tmp_path / "metrics.json", report).is_file()
    aggregate = aggregate_fold_seed_benchmarks(
        (
            FoldSeedBenchmark("fold-1", 7, report, report),
            FoldSeedBenchmark("fold-2", 8, report, report),
        )
    )
    assert aggregate.run_count == 2 and aggregate.mean_delta_exact_span_f1 == 0.0


def test_config_rejects_tampered_local_tokenizer(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.tokenizer_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="tokenizer checksum"):
        EncoderModelRegistry({"mock": lambda _config: (_MockTokenizer(), _MockBackbone())}).build(
            config
        )


class _FakeHuggingFaceTokenizer:
    def __call__(self, text: str, **kwargs: object) -> dict[str, object]:
        del text
        if kwargs.get("return_tensors") == "pt":
            return {
                "input_ids": torch.tensor([[1, 2, 3]]),
                "attention_mask": torch.tensor([[1, 1, 1]]),
                "offset_mapping": torch.tensor([[[0, 3], [4, 8], [0, 0]]]),
            }
        return {"input_ids": [1, 2], "offset_mapping": [(0, 3), (4, 8)]}

    def convert_ids_to_tokens(self, input_ids: list[int]) -> list[str]:
        assert input_ids == [1, 2]
        return ["\u0111au", "ng\u1ef1c"]


class _FakeTokenClassifier(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.weight = torch.nn.Parameter(torch.ones(1))
        self.config = SimpleNamespace(
            id2label={
                0: "O",
                1: f"B-{EntityType.SYMPTOM.value}",
                2: f"I-{EntityType.SYMPTOM.value}",
                3: f"B-{EntityType.TEST_NAME.value}",
                4: f"B-{EntityType.TEST_RESULT.value}",
                5: f"B-{EntityType.DIAGNOSIS.value}",
                6: f"B-{EntityType.MEDICATION.value}",
            }
        )

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> SimpleNamespace:
        del input_ids, attention_mask
        return SimpleNamespace(
            logits=torch.tensor(
                [
                    [
                        [-3.0, 5.0, -3.0, -3.0, -3.0, -3.0, -3.0],
                        [-3.0, -3.0, 4.0, -3.0, -3.0, -3.0, -3.0],
                        [2.0, -3.0, -3.0, -3.0, -3.0, -3.0, -3.0],
                    ]
                ]
            )
        )


def test_local_huggingface_adapter_decodes_bio_spans_with_raw_offsets() -> None:
    tokenizer = _FakeHuggingFaceTokenizer()
    offset_tokenizer = HuggingFaceOffsetTokenizer(tokenizer)
    backbone = HuggingFaceTokenClassifierBackbone(tokenizer, _FakeTokenClassifier(), 32)
    text = "\u0111au ng\u1ef1c"
    tokens = offset_tokenizer.tokenize(text)

    spans = backbone.predict_span_candidates(tokens, text)
    logits = backbone.predict_logits(tokens, GroundedMention("m1", 0, 8, text), "exam")

    assert spans == ((0, 8, 4.5),)
    assert text[spans[0][0] : spans[0][1]] == text
    assert logits[EntityType.SYMPTOM] == 5.0
