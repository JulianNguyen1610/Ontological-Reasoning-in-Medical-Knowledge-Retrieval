from __future__ import annotations

from pathlib import Path

import pytest

from medlink_ie.io.raw_loader import (
    BomPolicy,
    BomPolicyError,
    DocumentDecodeError,
    RawLoaderConfig,
    load_bytes,
    load_path,
)

UTF8_BOM = b"\xef\xbb\xbf"


@pytest.mark.parametrize(
    ("policy", "expected_text"),
    [
        (BomPolicy.PRESERVE, "\ufeffkhám"),
        (BomPolicy.STRIP, "khám"),
    ],
)
def test_utf8_bom_is_handled_by_the_explicit_policy(policy: BomPolicy, expected_text: str) -> None:
    raw_bytes = UTF8_BOM + "khám".encode("utf-8")

    document = load_bytes(raw_bytes, "bom-note", RawLoaderConfig(bom_policy=policy))

    assert document.raw_bytes == raw_bytes
    assert document.raw_text == expected_text
    assert document.had_bom is True


def test_utf8_bom_can_be_rejected_without_exposing_document_text() -> None:
    with pytest.raises(BomPolicyError) as error:
        load_bytes(
            UTF8_BOM + b"private clinical text",
            "bom-note",
            RawLoaderConfig(bom_policy=BomPolicy.REJECT),
        )

    assert error.value.document_id == "bom-note"
    assert error.value.byte_length == len(UTF8_BOM + b"private clinical text")
    assert "private clinical text" not in str(error.value)


@pytest.mark.parametrize(
    ("raw_text", "newline_style"),
    [
        ("a\r\nb\r\n", "crlf"),
        ("a\nb\n", "lf"),
        ("a\r\nb\nc\rd", "mixed"),
    ],
)
def test_newline_bytes_are_preserved(raw_text: str, newline_style: str) -> None:
    document = load_bytes(raw_text.encode("utf-8"), "newlines")

    assert document.raw_text == raw_text
    assert document.newline_style == newline_style


@pytest.mark.parametrize(
    "raw_text", ["café", "cafe\u0301", "a  b", "  padded  ", "final\n", "final"]
)
def test_text_is_not_normalized_or_trimmed(raw_text: str) -> None:
    document = load_bytes(raw_text.encode("utf-8"), "exact-text")

    assert document.raw_text == raw_text


def test_tabs_blank_lines_null_and_non_bmp_characters_round_trip() -> None:
    raw_text = "\tfirst\n\nsecond\x00 😀\n"
    document = load_bytes(raw_text.encode("utf-8"), "special-characters")

    assert document.raw_text == raw_text
    assert document.raw_bytes == raw_text.encode("utf-8")


def test_empty_file_is_a_valid_document() -> None:
    document = load_bytes(b"", "empty")

    assert document.raw_bytes == b""
    assert document.raw_text == ""
    assert document.newline_style == "none"


def test_invalid_utf8_raises_typed_error_with_safe_metadata() -> None:
    raw_bytes = b"\xffprivate clinical text"

    with pytest.raises(DocumentDecodeError) as error:
        load_bytes(raw_bytes, "invalid-note")

    assert error.value.document_id == "invalid-note"
    assert error.value.encoding == "utf-8"
    assert error.value.byte_start == 0
    assert error.value.byte_end == 1
    assert error.value.byte_length == len(raw_bytes)
    assert "private clinical text" not in str(error.value)


def test_repeated_loads_are_deterministic() -> None:
    raw_bytes = UTF8_BOM + "  café\r\n".encode("utf-8")
    config = RawLoaderConfig(bom_policy=BomPolicy.STRIP)

    assert (
        load_bytes(raw_bytes, "repeat", config).to_json()
        == load_bytes(raw_bytes, "repeat", config).to_json()
    )


def test_load_path_retains_binary_identity(tmp_path: Path) -> None:
    raw_bytes = UTF8_BOM + b"\tline\r\n\x00"
    source_path = tmp_path / "note.txt"
    source_path.write_bytes(raw_bytes)

    document = load_path(source_path, RawLoaderConfig(bom_policy=BomPolicy.PRESERVE))

    assert document.document_id == "note"
    assert document.raw_bytes == raw_bytes
    assert document.raw_text.encode("utf-8") == raw_bytes
