"""Parser-slot-aware lexical candidate filtering without changing mention spans."""

from __future__ import annotations

from medlink_ie.parsing.clinical_mentions import MedicationMention, parse_medication_mention
from medlink_ie.terminology.retrieval import (
    LexicalTerminologyIndex,
    RetrievalFilters,
    RetrievalResult,
)


def retrieve_medication_candidates(
    mention: str, index: LexicalTerminologyIndex
) -> tuple[MedicationMention, tuple[RetrievalResult, ...]]:
    """Use only the parsed ingredient surface to form an RxNorm candidate query."""
    parsed = parse_medication_mention(mention)
    ingredient = parsed.slots.ingredient_surface
    if ingredient is None:
        return parsed, ()
    results = index.search(
        ingredient.text,
        RetrievalFilters(entity_types=("medication",)),
    )
    return parsed, results
