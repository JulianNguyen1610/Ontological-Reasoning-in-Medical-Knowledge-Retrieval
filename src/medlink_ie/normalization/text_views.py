"""Lossless search and retrieval views derived from immutable raw documents."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

from medlink_ie.domain import SourceDocument, TextView
from medlink_ie.normalization.boundary_map import BoundaryMap

RAW_VIEW = "raw"
NFC_SEARCH_VIEW = "nfc_search"
LOWERCASE_RETRIEVAL_VIEW = "lowercase_retrieval"
ACCENTLESS_RETRIEVAL_VIEW = "accentless_retrieval"
WHITESPACE_NORMALIZED_RETRIEVAL_VIEW = "whitespace_normalized_retrieval"
ACCENT_TRANSLATION: dict[str, str | int | None] = {"Đ": "D", "đ": "d"}


def build_text_views(document: SourceDocument) -> dict[str, TextView]:
    """Build the fixed, boundary-mapped views for one immutable source document."""

    if not isinstance(document, SourceDocument):
        raise TypeError("document must be a SourceDocument")

    raw_text = document.raw_text
    raw_map = BoundaryMap(tuple(range(len(raw_text) + 1)), len(raw_text), len(raw_text))
    raw = raw_map.to_text_view(RAW_VIEW, raw_text)
    nfc = _transform_view(NFC_SEARCH_VIEW, raw, len(raw_text), _nfc)
    lowercase = _transform_view(LOWERCASE_RETRIEVAL_VIEW, nfc, len(raw_text), str.lower)
    accentless = _transform_view(
        ACCENTLESS_RETRIEVAL_VIEW, lowercase, len(raw_text), _remove_accents
    )
    whitespace = _collapse_whitespace(accentless, len(raw_text))
    return {
        RAW_VIEW: raw,
        NFC_SEARCH_VIEW: nfc,
        LOWERCASE_RETRIEVAL_VIEW: lowercase,
        ACCENTLESS_RETRIEVAL_VIEW: accentless,
        WHITESPACE_NORMALIZED_RETRIEVAL_VIEW: whitespace,
    }


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _remove_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    unaccented = "".join(
        character for character in decomposed if not unicodedata.category(character).startswith("M")
    )
    return unaccented.translate(str.maketrans(ACCENT_TRANSLATION))


def _transform_view(
    name: str, source: TextView, raw_length: int, transform: Callable[[str], str]
) -> TextView:
    output: list[str] = []
    boundaries = [source.boundary_to_raw[0]]
    for start, end in _canonical_units(source.text):
        transformed = transform(source.text[start:end])
        raw_start = source.boundary_to_raw[start]
        raw_end = source.boundary_to_raw[end]
        if boundaries[-1] != raw_start:
            boundaries[-1] = raw_start
        if transformed:
            output.append(transformed)
            boundaries.extend(raw_end for _ in transformed)
        else:
            boundaries[-1] = raw_end
    text = "".join(output)
    return BoundaryMap(tuple(boundaries), len(text), raw_length).to_text_view(name, text)


def _collapse_whitespace(source: TextView, raw_length: int) -> TextView:
    output: list[str] = []
    boundaries = [source.boundary_to_raw[0]]
    index = 0
    while index < len(source.text):
        start = index
        whitespace = source.text[index].isspace()
        index += 1
        if whitespace:
            while index < len(source.text) and source.text[index].isspace():
                index += 1
            transformed = " "
        else:
            transformed = source.text[start:index]
        raw_start = source.boundary_to_raw[start]
        raw_end = source.boundary_to_raw[index]
        if boundaries[-1] != raw_start:
            boundaries[-1] = raw_start
        output.append(transformed)
        boundaries.extend(raw_end for _ in transformed)
    text = "".join(output)
    return BoundaryMap(tuple(boundaries), len(text), raw_length).to_text_view(
        WHITESPACE_NORMALIZED_RETRIEVAL_VIEW, text
    )


def _canonical_units(text: str) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = start + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        units.append((start, end))
        start = end
    return units
