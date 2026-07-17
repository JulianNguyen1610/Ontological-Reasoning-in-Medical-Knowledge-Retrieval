from pathlib import Path

from medlink_ie.domain import ProposalSource
from medlink_ie.pipeline import MedLinkPipeline, package_output, pre_submit_validate
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
