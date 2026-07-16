"""Validation and use of boundary maps from transformed text to raw text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from medlink_ie.domain import TextView


@dataclass(frozen=True, slots=True)
class BoundaryMap:
    """A monotonic mapping of every view boundary onto a raw-text boundary."""

    boundaries: tuple[int, ...]
    view_length: int
    raw_length: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "boundaries", tuple(self.boundaries))
        if self.view_length < 0 or self.raw_length < 0:
            raise ValueError("view_length and raw_length must be non-negative")
        if len(self.boundaries) != self.view_length + 1:
            raise ValueError("boundary map must contain one boundary per view boundary")
        previous = -1
        for boundary in self.boundaries:
            if isinstance(boundary, bool) or not isinstance(boundary, int):
                raise TypeError("boundary map values must be integers")
            if not 0 <= boundary <= self.raw_length:
                raise ValueError("boundary map values must be within the raw-text range")
            if boundary < previous:
                raise ValueError("boundary map values must be monotonic")
            previous = boundary

    def to_text_view(self, name: str, text: str) -> TextView:
        """Create a validated domain view from this map and its matching text."""

        if len(text) != self.view_length:
            raise ValueError("text length does not match boundary map view_length")
        return TextView(name, text, self.boundaries)

    def map_span(self, start: int, end: int) -> tuple[int, int]:
        """Map a half-open view interval onto its corresponding raw interval."""

        _validate_view_interval(start, end, self.view_length)
        return self.boundaries[start], self.boundaries[end]


def map_view_span(view: TextView, start: int, end: int) -> tuple[int, int]:
    """Map a half-open span in *view* to the raw boundaries it records."""

    _validate_view_interval(start, end, len(view.text))
    return view.boundary_to_raw[start], view.boundary_to_raw[end]


def validate_boundaries(
    boundaries: Sequence[int], view_length: int, raw_length: int
) -> tuple[int, ...]:
    """Return an immutable, validated sequence of view-to-raw boundaries."""

    return BoundaryMap(tuple(boundaries), view_length, raw_length).boundaries


def _validate_view_interval(start: int, end: int, view_length: int) -> None:
    if isinstance(start, bool) or isinstance(end, bool):
        raise TypeError("view span boundaries must be integers")
    if not isinstance(start, int) or not isinstance(end, int):
        raise TypeError("view span boundaries must be integers")
    if not 0 <= start <= end <= view_length:
        raise ValueError("view span must be within the view's half-open boundaries")
