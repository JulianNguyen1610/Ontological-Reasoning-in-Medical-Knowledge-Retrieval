from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from medlink_ie.domain import ProposalSource, SourceDocument
from medlink_ie.grounding import ground_proposal
from medlink_ie.normalization.text_views import build_text_views
from medlink_ie.proposals import ProposalContext
from medlink_ie.proposals.ollama import OllamaSpanProposer, OllamaSpanProposerConfig


@dataclass
class _Generator:
    completion: str = "[]"
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: {
            "digest": "a" * 64,
            "model_info": {"general.parameter_count": 9_000_000_000},
        }
    )
    fail_generate: bool = False
    show_calls: int = 0
    generate_calls: int = 0
    options: Mapping[str, Any] | None = None

    def show(self, model: str, timeout_seconds: float) -> Mapping[str, Any]:
        assert model == "qwen3.5:9b" and timeout_seconds > 0
        self.show_calls += 1
        return self.metadata

    def generate(
        self,
        model: str,
        system_prompt: str,
        prompt: str,
        options: Mapping[str, Any],
        timeout_seconds: float,
    ) -> str:
        assert model == "qwen3.5:9b" and "Copy mention text exactly" in system_prompt
        assert timeout_seconds > 0
        self.generate_calls += 1
        self.options = dict(options)
        if self.fail_generate:
            raise TimeoutError("timeout")
        return self.completion


def _context(text: str, identifier: str = "d1") -> ProposalContext:
    document = SourceDocument(identifier, text.encode(), text, "utf-8", False, "none")
    return ProposalContext(document, build_text_views(document))


def _proposer(generator: _Generator, **config: Any) -> OllamaSpanProposer:
    if config.get("enabled"):
        artifact = Path(tempfile.gettempdir()) / "medlink-ollama-ablation-test.json"
        raw = json.dumps(
            {"schema_version": 1, "component": "ollama_span_proposer", "score_delta": 0.01}
        ).encode("utf-8")
        artifact.write_bytes(raw)
        config.setdefault("ablation_artifact_path", artifact)
        config.setdefault("ablation_artifact_checksum", sha256(raw).hexdigest())
    return OllamaSpanProposer(OllamaSpanProposerConfig(**config), generator)


def test_feature_off_never_invokes_ollama() -> None:
    generator = _Generator()
    proposer = _proposer(generator, enabled=False)

    assert proposer.propose(_context("đau ngực")) == ()
    assert generator.show_calls == generator.generate_calls == 0


def test_enabled_feature_requires_positive_checksum_verified_ablation() -> None:
    artifact = Path(tempfile.gettempdir()) / "medlink-ollama-negative-ablation.json"
    raw = b'{"schema_version":1,"component":"ollama_span_proposer","score_delta":0}'
    artifact.write_bytes(raw)
    config = OllamaSpanProposerConfig(
        enabled=True,
        ablation_artifact_path=artifact,
        ablation_artifact_checksum=sha256(raw).hexdigest(),
    )
    generator = _Generator()
    assert OllamaSpanProposer(config, generator).propose(_context("x")) == ()
    assert generator.show_calls == generator.generate_calls == 0


def test_missing_or_oversized_model_fails_closed() -> None:
    missing = _Generator(metadata={})
    assert _proposer(missing, enabled=True).propose(_context("đau")) == ()
    oversized = _Generator(
        metadata={"digest": "a" * 64, "model_info": {"general.parameter_count": 9_000_000_001}}
    )
    assert _proposer(oversized, enabled=True).propose(_context("đau")) == ()


def test_valid_json_expands_repeated_exact_mentions_and_preserves_grounding_boundary() -> None:
    generator = _Generator('[{"text":"đau","provisional_type":"TRIỆU_CHỨNG"}]')
    context = _context("đau và đau")
    proposer = _proposer(generator, enabled=True)

    proposals = proposer.propose(context)

    assert [(item.view_start, item.view_end) for item in proposals] == [(0, 3), (7, 10)]
    assert all(item.source is ProposalSource.LLM_PROPOSER for item in proposals)
    assert ground_proposal(proposals[0], context) is not None
    assert generator.options == {"num_predict": 512, "temperature": 0, "top_p": 1, "seed": 42}


def test_invalid_outputs_timeout_and_over_limit_document_yield_no_proposals() -> None:
    cases = (
        "not-json",
        '{"text":"đau","provisional_type":"TRIỆU_CHỨNG"}',
        '[{"text":"không có","provisional_type":"TRIỆU_CHỨNG"}]',
        '[{"text":"đau","provisional_type":"NOPE"}]',
        '[{"text":"đau","provisional_type":"TRIỆU_CHỨNG","code":"A00"}]',
        '[{"text":"đau","provisional_type":"TRIỆU_CHỨNG","confidence":0.9}]',
        '[{"text":"đau","provisional_type":"TRIỆU_CHỨNG","explanation":"x"}]',
        '[{"text":"đau","provisional_type":"TRIỆU_CHỨNG"},{"text":"đau","provisional_type":"TRIỆU_CHỨNG"}]',
    )
    for completion in cases:
        assert _proposer(_Generator(completion), enabled=True).propose(_context("đau")) == ()
    assert _proposer(_Generator(fail_generate=True), enabled=True).propose(_context("đau")) == ()
    assert (
        _proposer(_Generator(), enabled=True, max_input_characters=2).propose(_context("đau")) == ()
    )


def test_batch_continues_after_timeout_and_trace_records_only_safe_metadata() -> None:
    generator = _Generator('[{"text":"đau","provisional_type":"TRIỆU_CHỨNG"}]')
    proposer = _proposer(generator, enabled=True, max_documents_per_batch=2)
    result = proposer.propose_batch(
        (_context("đau", "b"), _context("đau", "a"), _context("đau", "c"))
    )

    assert [item.view_start for item in result["a"]] == [0]
    assert result["c"] == ()
    trace = proposer.last_trace.to_dict()
    metadata = trace["events"][0]["evidence"][0]["metadata"]
    assert metadata["prompt_artifact_version"] == "ollama-span-proposer-v1"
    assert len(metadata["prompt_artifact_checksum"]) == 64
    assert "đau" not in str(trace)
