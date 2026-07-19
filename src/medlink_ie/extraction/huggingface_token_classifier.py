"""Local Hugging Face token-classifier adapter for encoder span/type benchmarks.

The adapter accepts only an already-fine-tuned local checkpoint with BIO labels.
It never downloads model files and exposes raw logits for the generic extraction
layer to calibrate and fuse later.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from medlink_ie.domain import EntityType
from medlink_ie.extraction.encoder_span_type import (
    EncoderBackbone,
    EncoderSpanTypeConfig,
    GroundedMention,
    OffsetTokenizer,
    SubwordToken,
)

_OUTSIDE_LABEL = "O"
_CONTEXT_SEPARATOR = "\n[STRUCTURAL_CONTEXT]\n"


@dataclass(frozen=True, slots=True)
class HuggingFaceOffsetTokenizer(OffsetTokenizer):
    """Wrap a local fast tokenizer and retain untouched raw-text offsets."""

    tokenizer: Any

    def tokenize(self, text: str) -> tuple[SubwordToken, ...]:
        encoded = self.tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        offsets = encoded["offset_mapping"]
        input_ids = encoded["input_ids"]
        pieces = self.tokenizer.convert_ids_to_tokens(input_ids)
        tokens: list[SubwordToken] = []
        for piece, offset in zip(pieces, offsets, strict=True):
            start, end = _offset_pair(offset)
            if start == end:
                continue
            if not 0 <= start < end <= len(text) or not text[start:end]:
                raise ValueError("tokenizer emitted an invalid raw-text offset")
            tokens.append(SubwordToken(str(piece), start, end))
        return tuple(tokens)


class HuggingFaceTokenClassifierBackbone(EncoderBackbone):
    """Decode BIO spans and type logits from a local token-classifier checkpoint."""

    def __init__(self, tokenizer: Any, model: Any, max_subwords: int) -> None:
        if max_subwords < 1:
            raise ValueError("max_subwords must be positive")
        self._tokenizer = tokenizer
        self._model = model
        self._max_subwords = max_subwords
        self._id_to_label = _bio_labels(model)
        self.parameter_count = sum(int(parameter.numel()) for parameter in model.parameters())
        if self.parameter_count < 1:
            raise ValueError("token-classifier model must contain parameters")
        self._model.eval()

    def predict_span_candidates(
        self, tokens: tuple[SubwordToken, ...], raw_text: str
    ) -> tuple[tuple[int, int, float], ...]:
        del tokens
        offsets, logits = self._infer(raw_text)
        labels = _best_labels(logits, self._id_to_label)
        spans: list[tuple[int, int, float]] = []
        active_type: EntityType | None = None
        active_start = 0
        active_end = 0
        active_scores: list[float] = []
        for (start, end), (prefix, entity_type, score) in zip(offsets, labels, strict=True):
            if entity_type is None:
                if active_type is not None:
                    spans.append(
                        (active_start, active_end, sum(active_scores) / len(active_scores))
                    )
                    active_type = None
                    active_scores = []
                continue
            if prefix == "I" and entity_type is active_type:
                active_end = end
                active_scores.append(score)
                continue
            if active_type is not None:
                spans.append((active_start, active_end, sum(active_scores) / len(active_scores)))
            active_type = entity_type
            active_start = start
            active_end = end
            active_scores = [score]
        if active_type is not None:
            spans.append((active_start, active_end, sum(active_scores) / len(active_scores)))
        return tuple(spans)

    def predict_logits(
        self, tokens: tuple[SubwordToken, ...], mention: GroundedMention, context: str
    ) -> Mapping[EntityType, float]:
        del tokens
        offsets, logits = self._infer(mention.text, context)
        local_logits = [
            values
            for (start, end), values in zip(offsets, logits, strict=True)
            if start < len(mention.text) and end <= len(mention.text)
        ]
        if not local_logits:
            raise ValueError("token classifier produced no logits for grounded mention")
        return {
            entity_type: max(
                row[index]
                for row in local_logits
                for index, label in self._id_to_label.items()
                if _parse_bio_label(label)[1] is entity_type
            )
            for entity_type in EntityType
        }

    def _infer(
        self, text: str, context: str | None = None
    ) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[float, ...], ...]]:
        source = text if context is None else text + _CONTEXT_SEPARATOR + context
        encoded = self._tokenizer(
            source,
            return_offsets_mapping=True,
            return_tensors="pt",
            truncation=True,
            max_length=self._max_subwords,
        )
        offsets = tuple(
            _offset_pair(offset) for offset in encoded.pop("offset_mapping")[0].tolist()
        )
        torch = _require_torch()
        with torch.no_grad():
            output = self._model(**encoded)
        rows = tuple(tuple(float(value) for value in row) for row in output.logits[0].tolist())
        filtered = tuple(
            (offset, row)
            for offset, row in zip(offsets, rows, strict=True)
            if offset[0] < offset[1] and offset[1] <= len(text)
        )
        if not filtered:
            raise ValueError("token classifier produced no raw-text token offsets")
        return tuple(item[0] for item in filtered), tuple(item[1] for item in filtered)


def build_huggingface_token_classifier(
    config: EncoderSpanTypeConfig,
) -> tuple[OffsetTokenizer, EncoderBackbone]:
    """Build a local-only BIO token classifier selected through the model registry."""
    auto_model, auto_tokenizer = _require_transformers()
    model_dir = Path(config.model_artifact.path).parent
    tokenizer = auto_tokenizer.from_pretrained(model_dir, local_files_only=True, use_fast=True)
    model = auto_model.from_pretrained(model_dir, local_files_only=True)
    offset_tokenizer = HuggingFaceOffsetTokenizer(tokenizer)
    return offset_tokenizer, HuggingFaceTokenClassifierBackbone(
        tokenizer, model, config.max_subwords
    )


def _bio_labels(model: Any) -> Mapping[int, str]:
    raw = getattr(getattr(model, "config", None), "id2label", None)
    if not isinstance(raw, Mapping) or not raw:
        raise ValueError("token-classifier checkpoint must provide id2label BIO metadata")
    labels = {int(index): str(label) for index, label in raw.items()}
    if _OUTSIDE_LABEL not in labels.values():
        raise ValueError("token-classifier checkpoint must provide an O label")
    parsed = tuple(_parse_bio_label(label) for label in labels.values())
    if not any(entity_type is not None for _, entity_type in parsed):
        raise ValueError("token-classifier checkpoint must provide BIO entity labels")
    return labels


def _best_labels(
    logits: tuple[tuple[float, ...], ...], labels: Mapping[int, str]
) -> tuple[tuple[str, EntityType | None, float], ...]:
    expected = set(labels)
    if expected != set(range(len(labels))):
        raise ValueError("token-classifier label IDs must be consecutive from zero")
    result: list[tuple[str, EntityType | None, float]] = []
    for row in logits:
        if len(row) != len(labels) or any(not isfinite(value) for value in row):
            raise ValueError("token-classifier logits must be finite and match label metadata")
        index = max(range(len(row)), key=lambda value: (row[value], -value))
        prefix, entity_type = _parse_bio_label(labels[index])
        result.append((prefix, entity_type, row[index]))
    return tuple(result)


def _parse_bio_label(label: str) -> tuple[str, EntityType | None]:
    if label == _OUTSIDE_LABEL:
        return _OUTSIDE_LABEL, None
    prefix, separator, value = label.partition("-")
    if separator != "-" or prefix not in {"B", "I"}:
        raise ValueError("token-classifier labels must use O, B-<type>, or I-<type>")
    try:
        entity_type = EntityType(value)
    except ValueError:
        try:
            entity_type = EntityType[value]
        except KeyError as error:
            raise ValueError(f"unknown BIO entity type: {value}") from error
    return prefix, entity_type


def _offset_pair(value: Any) -> tuple[int, int]:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise TypeError("tokenizer offset mapping must contain pairs")
    start, end = value
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
    ):
        raise TypeError("tokenizer offsets must be integers")
    return start, end


def _require_torch() -> Any:
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("PyTorch is required for the Hugging Face encoder adapter") from error
    return torch


def _require_transformers() -> tuple[Any, Any]:
    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer
    except ImportError as error:
        raise RuntimeError(
            "transformers is required for the Hugging Face encoder adapter"
        ) from error
    return AutoModelForTokenClassification, AutoTokenizer
