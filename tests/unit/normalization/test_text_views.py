from __future__ import annotations

import pytest

from medlink_ie.domain import SourceDocument
from medlink_ie.normalization.boundary_map import map_view_span
from medlink_ie.normalization.text_views import build_text_views


def _document(raw_text: str) -> SourceDocument:
    return SourceDocument("note", raw_text.encode("utf-8"), raw_text, "utf-8", False, "none")


def _assert_contract(raw_text: str) -> None:
    for view in build_text_views(_document(raw_text)).values():
        assert len(view.boundary_to_raw) == len(view.text) + 1
        assert tuple(sorted(view.boundary_to_raw)) == view.boundary_to_raw
        assert all(0 <= boundary <= len(raw_text) for boundary in view.boundary_to_raw)


def test_raw_identity_view_maps_every_boundary_to_itself() -> None:
    raw_text = "A😀\r\nB"
    view = build_text_views(_document(raw_text))["raw"]

    assert view.text == raw_text
    assert view.boundary_to_raw == tuple(range(len(raw_text) + 1))
    assert map_view_span(view, 1, 3) == (1, 3)


def test_nfc_view_maps_decomposed_accent_to_its_full_raw_range() -> None:
    raw_text = "cafe\u0301"
    view = build_text_views(_document(raw_text))["nfc_search"]

    assert view.text == "café"
    assert map_view_span(view, 3, 4) == (3, 5)


@pytest.mark.parametrize("raw_text", ["café", "cafe\u0301", "a\u0308\u0323"])
def test_nfc_and_combining_mark_views_obey_boundary_contract(raw_text: str) -> None:
    _assert_contract(raw_text)


def test_vietnamese_lowercase_and_accentless_views_preserve_raw_boundaries() -> None:
    raw_text = "TIẾNG Việt Đ"
    views = build_text_views(_document(raw_text))

    assert views["lowercase_retrieval"].text == "tiếng việt đ"
    accentless = views["accentless_retrieval"]
    assert accentless.text == "tieng viet d"
    assert map_view_span(accentless, 0, 5) == (0, 5)
    assert map_view_span(accentless, 11, 12) == (11, 12)


def test_lowercase_expansion_keeps_monotonic_boundary_mapping() -> None:
    raw_text = "İ"
    view = build_text_views(_document(raw_text))["lowercase_retrieval"]

    assert view.text == "i\u0307"
    assert view.boundary_to_raw == (0, 1, 1)
    assert map_view_span(view, 0, 2) == (0, 1)


def test_whitespace_normalization_collapses_full_raw_ranges_without_trimming() -> None:
    raw_text = "  a   b  "
    view = build_text_views(_document(raw_text))["whitespace_normalized_retrieval"]

    assert view.text == " a b "
    assert map_view_span(view, 0, 1) == (0, 2)
    assert map_view_span(view, 2, 3) == (3, 6)
    assert map_view_span(view, 4, 5) == (7, 9)


def test_crlf_tabs_and_non_bmp_characters_map_to_raw_ranges() -> None:
    raw_text = "A\r\n\t😀  B"
    view = build_text_views(_document(raw_text))["whitespace_normalized_retrieval"]

    assert view.text == "a 😀 b"
    assert map_view_span(view, 1, 2) == (1, 4)
    assert map_view_span(view, 2, 3) == (4, 5)
    _assert_contract(raw_text)


def test_empty_text_has_one_boundary_in_every_view() -> None:
    for view in build_text_views(_document("")).values():
        assert view.text == ""
        assert view.boundary_to_raw == (0,)
        assert map_view_span(view, 0, 0) == (0, 0)


@pytest.mark.parametrize(
    ("raw_text", "view_name", "view_span", "expected_raw_span"),
    [
        ("cafe\u0301 xyz", "nfc_search", (0, 4), (0, 5)),
        ("A   B", "whitespace_normalized_retrieval", (1, 2), (1, 4)),
        ("Đau", "accentless_retrieval", (0, 1), (0, 1)),
        ("😀 test", "lowercase_retrieval", (0, 1), (0, 1)),
    ],
)
def test_arbitrary_view_spans_map_back_to_expected_raw_slices(
    raw_text: str, view_name: str, view_span: tuple[int, int], expected_raw_span: tuple[int, int]
) -> None:
    view = build_text_views(_document(raw_text))[view_name]

    assert map_view_span(view, *view_span) == expected_raw_span
    start, end = expected_raw_span
    assert raw_text[start:end] == raw_text[expected_raw_span[0] : expected_raw_span[1]]
