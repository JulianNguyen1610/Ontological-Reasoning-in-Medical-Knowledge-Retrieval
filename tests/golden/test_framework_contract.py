from __future__ import annotations


def test_framework_section_1_2_position_example_is_half_open_python_indexing() -> None:
    mention = "amlodipine 10 mg po daily"
    raw_text = ("x" * 58) + mention + "."

    assert len(mention) == 25
    assert raw_text[58:83] == mention
