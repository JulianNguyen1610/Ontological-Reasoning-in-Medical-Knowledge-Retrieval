"""Source-preserving medication and laboratory mention feature parsers.

These parsers do not assign an entity type, terminology concept, or clinical
interpretation.  Every returned slot carries a span into the original mention.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

_STRENGTH = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)(?:\s*(?P<range>[-–])\s*(?P<range_value>\d+(?:[.,]\d+)?))?"
    r"\s*(?P<unit>mcg|μg|ug|mg|g|ml|mL|%)\b",
    re.IGNORECASE,
)
_FORM = re.compile(
    r"\b(?:enteric-coated\s+tablet|tablet|tab|capsule|cap|viên|ống|gói|syrup|"
    r"solution|suspension|cream|gel|drops?)\b",
    re.IGNORECASE,
)
_ROUTE = re.compile(r"\b(?:po|iv|im|sc|oral|uống|tiêm|truyền\s+tĩnh\s+mạch)\b", re.IGNORECASE)
_RELEASE = re.compile(r"\b(?:XR|XL|SR|CR|ER)\b", re.IGNORECASE)
_FREQUENCY = re.compile(
    r"\b(?:qd|bid|tid|qhs|qam|q\d+h|daily|mỗi\s+(?:\d+\s+giờ|ngày))\b|"
    r"\b\d+\s*(?:lần|x)\s*/\s*(?:ngày|day)\b",
    re.IGNORECASE,
)
_PRN = re.compile(r"(?::\s*prn\b|\bprn\b|\bkhi\s+sốt\b)", re.IGNORECASE)
_CONNECTOR = re.compile(r"\s*(?:\+|/|\bvà\b|\band\b)\s*", re.IGNORECASE)
_NUMERIC_RESULT = re.compile(
    r"(?P<comparator><=|>=|<|>|≤|≥)?\s*(?P<value>\d+(?:[.,]\d+)?"
    r"(?:\s*[-–]\s*\d+(?:[.,]\d+)?)?)\s*(?P<unit>%|mmol/l|mmol/L|mg/dl|"
    r"mg/dL|g/l|g/L|10\^?\d+/l|U/L|IU/L)?",
    re.IGNORECASE,
)
_REFERENCE_RANGE = re.compile(r"\(\s*(?P<value>\d+(?:[.,]\d+)?\s*[-–]\s*\d+(?:[.,]\d+)?)\s*\)")
_QUALITATIVE = re.compile(
    r"\b(?P<value>dương\s+tính|âm\s+tính|không\s+phát\s+hiện|positive|negative|"
    r"increased|decreased|tăng|giảm|cao|thấp)\b",
    re.IGNORECASE,
)
_FLAG = re.compile(r"\b(?P<flag>H|L)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ClinicalSlot:
    """One raw mention span and its parser-local normalized feature value."""

    start: int
    end: int
    text: str
    value: str


@dataclass(frozen=True, slots=True)
class MedicationSlots:
    ingredient_surface: ClinicalSlot | None
    strength_value: ClinicalSlot | None
    strength_unit: ClinicalSlot | None
    strength_range: ClinicalSlot | None
    dose_form: ClinicalSlot | None
    route: ClinicalSlot | None
    release_modifier: ClinicalSlot | None
    frequency: ClinicalSlot | None
    prn: ClinicalSlot | None
    combination_components: tuple[ClinicalSlot, ...]


@dataclass(frozen=True, slots=True)
class LaboratorySlots:
    test_name_surface: ClinicalSlot | None
    result: ClinicalSlot | None
    comparator: ClinicalSlot | None
    unit: ClinicalSlot | None
    reference_range: ClinicalSlot | None
    abnormal_flag: ClinicalSlot | None


@dataclass(frozen=True, slots=True)
class MedicationMention:
    mention: str
    slots: MedicationSlots
    confidence: float
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LaboratoryMention:
    mention: str
    slots: LaboratorySlots
    confidence: float
    evidence: tuple[str, ...]


def parse_medication_mention(mention: str) -> MedicationMention:
    """Extract source-level medication features without terminology or type inference."""
    _validate_mention(mention)
    strength = _STRENGTH.search(mention)
    form = _first_slot(mention, _FORM, _normalize_lower)
    route = _first_slot(mention, _ROUTE, _normalize_route)
    release = _first_slot(mention, _RELEASE, _normalize_lower)
    frequency = _first_slot(mention, _FREQUENCY, _normalize_frequency)
    prn = _first_slot(mention, _PRN, lambda _: "prn")
    signal_starts = [
        match.start()
        for match in (
            strength,
            _FORM.search(mention),
            _ROUTE.search(mention),
            _RELEASE.search(mention),
            _FREQUENCY.search(mention),
            _PRN.search(mention),
            _CONNECTOR.search(mention),
        )
        if match is not None
    ]
    first_end = min(signal_starts) if signal_starts else len(mention)
    first_component = _ingredient_slot(mention, 0, first_end)
    components = _combination_components(mention, first_component)
    value = unit = strength_range = None
    evidence: list[str] = []
    if first_component is not None:
        evidence.append("medication.ingredient_surface")
    if strength is not None:
        value = _slot(mention, *strength.span("value"), _normalize_decimal(strength.group("value")))
        unit = _slot(mention, *strength.span("unit"), _normalize_unit(strength.group("unit")))
        if strength.group("range") is not None:
            range_start = strength.start("value")
            range_end = strength.end("range_value")
            strength_range = _slot(
                mention,
                range_start,
                range_end,
                _normalize_decimal(strength.group("value"))
                + "-"
                + _normalize_decimal(strength.group("range_value")),
            )
        evidence.append("medication.strength")
    for name, slot in (
        ("dose_form", form),
        ("route", route),
        ("release", release),
        ("frequency", frequency),
        ("prn", prn),
    ):
        if slot is not None:
            evidence.append("medication." + name)
    if len(components) > 1:
        evidence.append("medication.combination")
    slots = MedicationSlots(
        first_component,
        value,
        unit,
        strength_range,
        form,
        route,
        release,
        frequency,
        prn,
        components,
    )
    return MedicationMention(mention, slots, _confidence(evidence, 6), tuple(evidence))


def parse_laboratory_mention(mention: str) -> LaboratoryMention:
    """Extract source-level laboratory features without coding or final type assignment."""
    _validate_mention(mention)
    reference_match = _REFERENCE_RANGE.search(mention)
    reference = (
        _slot(
            mention,
            *reference_match.span("value"),
            _normalize_range(reference_match.group("value")),
        )
        if reference_match is not None
        else None
    )
    qualitative = _QUALITATIVE.search(mention)
    numeric = _first_non_reference_numeric(mention, reference_match)
    result_match = qualitative if qualitative is not None else numeric
    result = comparator = unit = None
    evidence: list[str] = []
    if qualitative is not None:
        result = _slot(
            mention,
            qualitative.start("value"),
            qualitative.end("value"),
            _normalize_qualitative(qualitative.group("value")),
        )
        evidence.append("laboratory.qualitative_result")
    elif numeric is not None:
        result = _slot(
            mention,
            numeric.start("value"),
            numeric.end("value"),
            _normalize_range(numeric.group("value")),
        )
        if numeric.group("comparator") is not None:
            comparator = _slot(
                mention,
                *numeric.span("comparator"),
                _normalize_comparator(numeric.group("comparator")),
            )
        if numeric.group("unit") is not None:
            unit = _slot(mention, *numeric.span("unit"), _normalize_unit(numeric.group("unit")))
        evidence.append("laboratory.numeric_result")
    test = _test_surface(
        mention, result_match.start() if result_match is not None else len(mention)
    )
    if test is not None:
        evidence.append("laboratory.test_surface")
    flag_start = max(
        result.end if result is not None else 0,
        reference_match.end() if reference_match is not None else 0,
    )
    flag = _abnormal_flag(mention, flag_start)
    if reference is not None:
        evidence.append("laboratory.reference_range")
    if flag is not None:
        evidence.append("laboratory.abnormal_flag")
    slots = LaboratorySlots(test, result, comparator, unit, reference, flag)
    return LaboratoryMention(mention, slots, _confidence(evidence, 4), tuple(evidence))


def _combination_components(
    mention: str, first_component: ClinicalSlot | None
) -> tuple[ClinicalSlot, ...]:
    components = [first_component] if first_component is not None else []
    for connector in _CONNECTOR.finditer(mention):
        next_signal = _next_signal_start(mention, connector.end())
        component = _ingredient_slot(mention, connector.end(), next_signal)
        if component is not None:
            components.append(component)
    return tuple(components)


def _next_signal_start(mention: str, start: int) -> int:
    matches = [
        match.start()
        for pattern in (_STRENGTH, _FORM, _ROUTE, _RELEASE, _FREQUENCY, _PRN, _CONNECTOR)
        if (match := pattern.search(mention, start)) is not None
    ]
    return min(matches) if matches else len(mention)


def _ingredient_slot(mention: str, start: int, end: int) -> ClinicalSlot | None:
    raw_start, raw_end = _trim_bounds(mention, start, end)
    if raw_start == raw_end:
        return None
    candidate = mention[raw_start:raw_end]
    if _RELEASE.fullmatch(candidate) or _ROUTE.fullmatch(candidate) or _FORM.fullmatch(candidate):
        return None
    return _slot(mention, raw_start, raw_end, " ".join(candidate.casefold().split()))


def _test_surface(mention: str, end: int) -> ClinicalSlot | None:
    start, end = _trim_bounds(mention, 0, end)
    while end > start and mention[end - 1] in ":=,":
        end -= 1
        start, end = _trim_bounds(mention, start, end)
    return (
        _slot(mention, start, end, " ".join(mention[start:end].casefold().split()))
        if start != end
        else None
    )


def _first_non_reference_numeric(
    mention: str, reference: re.Match[str] | None
) -> re.Match[str] | None:
    for match in _NUMERIC_RESULT.finditer(mention):
        if reference is None or not (
            reference.start() <= match.start() and match.end() <= reference.end()
        ):
            return match
    return None


def _abnormal_flag(mention: str, after: int) -> ClinicalSlot | None:
    match = _FLAG.search(mention, after)
    return (
        _slot(mention, *match.span("flag"), "high" if match.group("flag").upper() == "H" else "low")
        if match
        else None
    )


def _first_slot(
    mention: str, pattern: re.Pattern[str], normalize: Callable[[str], str]
) -> ClinicalSlot | None:
    match = pattern.search(mention)
    return _slot(mention, match.start(), match.end(), normalize(match.group())) if match else None


def _slot(mention: str, start: int, end: int, value: str) -> ClinicalSlot:
    return ClinicalSlot(start, end, mention[start:end], value)


def _trim_bounds(mention: str, start: int, end: int) -> tuple[int, int]:
    while start < end and mention[start].isspace():
        start += 1
    while end > start and (mention[end - 1].isspace() or mention[end - 1] in "+/"):
        end -= 1
    return start, end


def _normalize_decimal(value: str) -> str:
    return value.replace(",", ".")


def _normalize_range(value: str) -> str:
    return re.sub(r"\s*[-–]\s*", "-", _normalize_decimal(value))


def _normalize_unit(value: str) -> str:
    return value.casefold().replace("μ", "u").replace("ug", "mcg").replace(" ", "")


def _normalize_lower(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_route(value: str) -> str:
    aliases = {
        "po": "oral",
        "oral": "oral",
        "uống": "oral",
        "iv": "intravenous",
        "im": "intramuscular",
        "sc": "subcutaneous",
    }
    return aliases.get(_normalize_lower(value), _normalize_lower(value))


def _normalize_frequency(value: str) -> str:
    return _normalize_lower(value)


def _normalize_comparator(value: str) -> str:
    return {"≤": "<=", "≥": ">="}.get(value, value)


def _normalize_qualitative(value: str) -> str:
    normalized = _normalize_lower(value)
    return {
        "dương tính": "positive",
        "âm tính": "negative",
        "không phát hiện": "not_detected",
        "tăng": "increased",
        "giảm": "decreased",
        "cao": "high",
        "thấp": "low",
    }.get(normalized, normalized)


def _confidence(evidence: list[str], denominator: int) -> float:
    return round(min(1.0, len(evidence) / denominator), 3)


def _validate_mention(mention: str) -> None:
    if not isinstance(mention, str):
        raise TypeError("mention must be a string")
