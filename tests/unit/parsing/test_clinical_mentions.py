from __future__ import annotations

from medlink_ie.parsing.clinical_mentions import parse_laboratory_mention, parse_medication_mention


def test_medication_slots_preserve_official_style_example_and_strength_identity() -> None:
    parsed = parse_medication_mention("amlodipine 10 mg po daily")

    assert parsed.mention == "amlodipine 10 mg po daily"
    assert parsed.slots.ingredient_surface is not None
    assert parsed.slots.ingredient_surface.text == "amlodipine"
    assert parsed.slots.strength_value is not None
    assert parsed.slots.strength_value.value == "10"
    assert parsed.slots.strength_unit is not None
    assert parsed.slots.strength_unit.value == "mg"
    assert parsed.slots.route is not None and parsed.slots.route.value == "oral"
    assert parsed.slots.frequency is not None and parsed.slots.frequency.value == "daily"
    assert parsed.confidence > 0
    assert parsed.evidence

    low = parse_medication_mention("amlodipine 5 mg")
    high = parse_medication_mention("amlodipine 10 mg")
    assert low.slots.strength_value != high.slots.strength_value


def test_medication_combination_release_decimal_comma_and_ambiguous_tokens() -> None:
    parsed = parse_medication_mention("amoxicillin 500 mg + clavulanate 125 mg XL prn")
    assert [slot.text for slot in parsed.slots.combination_components] == [
        "amoxicillin",
        "clavulanate",
    ]
    assert parsed.slots.release_modifier is not None
    assert parsed.slots.release_modifier.value == "xl"
    assert parsed.slots.prn is not None

    comma = parse_medication_mention("clonazepam 0,5 mg SR")
    assert comma.slots.strength_value is not None
    assert comma.slots.strength_value.value == "0.5"
    assert comma.slots.release_modifier is not None
    assert comma.slots.release_modifier.value == "sr"

    ambiguous = parse_medication_mention("XR 500 mg")
    assert ambiguous.slots.ingredient_surface is None
    assert ambiguous.slots.dose_form is None


def test_laboratory_numeric_qualitative_ranges_and_missing_units() -> None:
    numeric = parse_laboratory_mention("Glucose >= 5,6 mmol/L (3.9-5.6) H")
    assert numeric.slots.test_name_surface is not None
    assert numeric.slots.test_name_surface.text == "Glucose"
    assert numeric.slots.result is not None and numeric.slots.result.value == "5.6"
    assert numeric.slots.comparator is not None and numeric.slots.comparator.value == ">="
    assert numeric.slots.unit is not None and numeric.slots.unit.value == "mmol/l"
    assert numeric.slots.reference_range is not None
    assert numeric.slots.reference_range.value == "3.9-5.6"
    assert numeric.slots.abnormal_flag is not None and numeric.slots.abnormal_flag.value == "high"

    qualitative = parse_laboratory_mention("SARS-CoV-2: dương tính")
    assert qualitative.slots.test_name_surface is not None
    assert qualitative.slots.result is not None
    assert qualitative.slots.result.value == "positive"

    missing_unit = parse_laboratory_mention("Creatinine 1.2")
    assert missing_unit.slots.result is not None
    assert missing_unit.slots.unit is None


def test_laboratory_ambiguous_flag_is_not_guessed() -> None:
    parsed = parse_laboratory_mention("H 12")
    assert parsed.slots.test_name_surface is not None
    assert parsed.slots.test_name_surface.text == "H"
    assert parsed.slots.abnormal_flag is None
