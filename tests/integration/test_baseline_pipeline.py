import json
import zipfile
from pathlib import Path

import pytest

from medlink_ie.domain import EntityType, ProposalSource
from medlink_ie.pipeline import (
    BatchConfig,
    MedLinkPipeline,
    ResumePolicy,
    atomic_write_json,
    package_output,
    pre_submit_validate,
)
from medlink_ie.proposals import ProposalEvidence, SpanProposal


class _Proposer:
    name = "fixture"
    source = ProposalSource.CONCEPT_RULES
    version = "1"

    def propose(self, context):
        if "ho" not in context.document.raw_text:
            return ()
        return tuple(
            SpanProposal.create(
                context,
                self.source,
                self.version,
                "raw",
                start,
                start + 2,
                0.9,
                (
                    ProposalEvidence(
                        "rule_match",
                        "fixture",
                        "1",
                        {"provisional_type_distribution": {"symptom": 0.9}},
                    ),
                ),
            )
            for start in range(len(context.document.raw_text))
            if context.document.raw_text.startswith("ho", start)
        )


class _BadSampleProposer(_Proposer):
    def propose(self, context):
        if context.document.document_id == "2":
            raise ValueError("fixture failure")
        return super().propose(context)


def test_three_sample_batch_package_and_reopen_validation(tmp_path: Path):
    inputs = tmp_path / "input"
    outputs = tmp_path / "output"
    traces = tmp_path / "traces"
    inputs.mkdir()
    (inputs / "10.txt").write_text("ho và ho", encoding="utf-8")
    (inputs / "2.txt").write_text("", encoding="utf-8")
    (inputs / "3.txt").write_text("không có", encoding="utf-8")
    report = MedLinkPipeline((_Proposer(),)).predict_directory(inputs, outputs, traces)
    assert report.processed == ("2.txt", "3.txt", "10.txt")
    archive = tmp_path / "output.zip"
    package_output(outputs, archive)
    pre_submit_validate(archive, inputs)


def test_batch_isolates_bad_sample_and_writes_safe_observability_artifacts(tmp_path: Path) -> None:
    inputs, outputs, traces = tmp_path / "input", tmp_path / "output", tmp_path / "traces"
    inputs.mkdir()
    (inputs / "10.txt").write_text("ho", encoding="utf-8")
    (inputs / "2.txt").write_text("bad clinical text", encoding="utf-8")
    (inputs / "3.txt").write_text("ho", encoding="utf-8")

    report = MedLinkPipeline((_BadSampleProposer(),)).predict_directory(
        inputs, outputs, traces, BatchConfig(batch_size=2)
    )

    assert report.processed == ("3.txt", "10.txt")
    assert report.failures == ({"category": "prediction", "file": "2.txt"},)
    manifest = json.loads((traces / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "finalized"
    assert manifest["counts"]["failed"] == 1
    trace = (traces / "3.trace.json").read_text(encoding="utf-8")
    assert "bad clinical text" not in trace
    assert "per_entity_decisions" in trace


def test_resume_reuses_only_completed_checksum_valid_sample_outputs(tmp_path: Path) -> None:
    inputs, outputs, traces = tmp_path / "input", tmp_path / "output", tmp_path / "traces"
    inputs.mkdir()
    (inputs / "2.txt").write_text("ho", encoding="utf-8")
    pipeline = MedLinkPipeline((_Proposer(),))
    first = pipeline.predict_directory(inputs, outputs, traces)
    assert first.processed == ("2.txt",)

    resumed = pipeline.predict_directory(
        inputs, outputs, traces, BatchConfig(resume_policy=ResumePolicy.REUSE_VALID)
    )

    assert resumed.resumed == ("2.txt",)
    assert resumed.processed == ()
    assert (
        json.loads((traces / "run_manifest.json").read_text(encoding="utf-8"))["counts"]["resumed"]
        == 1
    )


def test_atomic_write_failure_leaves_no_successful_or_partial_target(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "output.json"

    def interrupted_replace(source: str | Path, destination: str | Path) -> None:
        raise OSError("interrupted")

    monkeypatch.setattr("medlink_ie.pipeline.baseline.os.replace", interrupted_replace)

    try:
        atomic_write_json(target, [])
    except OSError:
        pass
    else:
        raise AssertionError("expected interrupted atomic write")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_deterministic_rerun_has_stable_outputs_and_order(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "10.txt").write_text("ho", encoding="utf-8")
    (inputs / "2.txt").write_text("ho", encoding="utf-8")
    first_output, first_trace = tmp_path / "first-output", tmp_path / "first-trace"
    second_output, second_trace = tmp_path / "second-output", tmp_path / "second-trace"

    first = MedLinkPipeline((_Proposer(),)).predict_directory(inputs, first_output, first_trace)
    second = MedLinkPipeline((_Proposer(),)).predict_directory(inputs, second_output, second_trace)

    assert first.processed == second.processed == ("2.txt", "10.txt")
    assert (first_output / "2.json").read_bytes() == (second_output / "2.json").read_bytes()


def test_package_uses_reproducible_zip_metadata(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "2.json").write_text("[]", encoding="utf-8")
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    package_output(output, first)
    package_output(output, second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("payload", [b"[NaN]", b"\xff", b'{"not":"an array"}'])
def test_pre_submit_rejects_invalid_json_encodings_and_constants(
    tmp_path: Path, payload: bytes
) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "1.txt").write_text("ho", encoding="utf-8")
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("output/1.json", payload)
    with pytest.raises(ValueError):
        pre_submit_validate(archive, inputs)


def test_pre_submit_rejects_duplicate_or_unknown_candidate_codes(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "1.txt").write_text("ho", encoding="utf-8")
    payload = [
        {
            "text": "ho",
            "type": EntityType.DIAGNOSIS.value,
            "position": [0, 2],
            "assertions": [],
            "candidates": ["A", "A"],
        }
    ]
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("output/1.json", json.dumps(payload, ensure_ascii=False))
    with pytest.raises(ValueError, match="duplicate candidate"):
        pre_submit_validate(archive, inputs, {EntityType.DIAGNOSIS: frozenset({"A"})})
    payload[0]["candidates"] = ["B"]
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("output/1.json", json.dumps(payload, ensure_ascii=False))
    with pytest.raises(ValueError, match="frozen terminology"):
        pre_submit_validate(archive, inputs, {EntityType.DIAGNOSIS: frozenset({"A"})})
