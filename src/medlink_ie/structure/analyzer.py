"""Deterministic raw-text structural analysis for clinical documents."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from medlink_ie.domain import SourceDocument


@dataclass(frozen=True, slots=True)
class SectionHeadingRule:
    rule_id: str
    label: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClauseCueRule:
    rule_id: str
    cue: str


@dataclass(frozen=True, slots=True)
class StructuralAnalyzerConfig:
    section_heading_rules: tuple[SectionHeadingRule, ...] = (
        SectionHeadingRule(
            "section.history.medical", "medical_history", ("tiền sử bệnh", "past medical history")
        ),
        SectionHeadingRule(
            "section.history.family", "family_history", ("tiền sử gia đình", "family history")
        ),
        SectionHeadingRule(
            "section.medication.history",
            "medication_history",
            (
                "thuốc trước nhập viện",
                "medications",
                "current medications",
                "medication history",
                "home medications",
            ),
        ),
        SectionHeadingRule(
            "section.exam.current",
            "current_exam",
            ("khám hiện tại", "physical examination", "history of present illness"),
        ),
        SectionHeadingRule(
            "section.laboratory",
            "laboratory",
            ("cận lâm sàng", "laboratory results", "lab results"),
        ),
        SectionHeadingRule(
            "section.diagnosis", "diagnosis", ("chẩn đoán", "diagnosis", "assessment")
        ),
        SectionHeadingRule("section.conclusion", "conclusion", ("kết luận", "conclusion")),
        SectionHeadingRule("section.plan", "plan", ("kế hoạch", "plan")),
    )
    numbered_list_rule_id: str = "list.numbered"
    bullet_list_rule_id: str = "list.bullet"
    medication_lines_rule_id: str = "list.medication_lines"
    medical_abbreviations: tuple[str, ...] = (
        "bs",
        "dr",
        "mr",
        "mrs",
        "ms",
        "vs",
        "p",
        "ts",
        "mg",
        "ml",
        "mcg",
        "hr",
        "min",
        "eg",
        "ie",
    )
    clause_cue_rules: tuple[ClauseCueRule, ...] = (
        ClauseCueRule("clause.contrast.nhung", "nhưng"),
        ClauseCueRule("clause.contrast.tuy_nhien", "tuy nhiên"),
        ClauseCueRule("clause.contrast.con", "còn"),
        ClauseCueRule("clause.contrast.but", "but"),
        ClauseCueRule("clause.contrast.however", "however"),
        ClauseCueRule("clause.coordination.va", "và"),
        ClauseCueRule("clause.coordination.hoac", "hoặc"),
        ClauseCueRule("clause.coordination.and", "and"),
        ClauseCueRule("clause.coordination.or", "or"),
    )


@dataclass(frozen=True, slots=True)
class StructuralUnit:
    unit_id: str
    start: int
    end: int
    text: str
    rule_ids: tuple[str, ...]

    def validate(self, raw_text: str) -> None:
        if not self.unit_id:
            raise ValueError("structural unit_id must be non-empty")
        if not 0 <= self.start <= self.end <= len(raw_text):
            raise ValueError("structural unit boundaries must be within raw_text")
        if raw_text[self.start : self.end] != self.text:
            raise ValueError("structural unit text must equal raw_text[start:end]")
        if any(not rule_id for rule_id in self.rule_ids):
            raise ValueError("structural unit rule_ids must be non-empty strings")


@dataclass(frozen=True, slots=True)
class Section(StructuralUnit):
    label: str
    heading_start: int
    heading_end: int

    def validate(self, raw_text: str) -> None:
        StructuralUnit.validate(self, raw_text)
        if not self.label or not self.start <= self.heading_start <= self.heading_end <= self.end:
            raise ValueError("section heading must be within the section boundary")


@dataclass(frozen=True, slots=True)
class ListBlock(StructuralUnit):
    parent_section_id: str | None
    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListItem(StructuralUnit):
    parent_list_id: str
    parent_section_id: str | None
    content_start: int
    content_end: int

    def validate(self, raw_text: str) -> None:
        StructuralUnit.validate(self, raw_text)
        if (
            not self.parent_list_id
            or not self.start <= self.content_start <= self.content_end <= self.end
        ):
            raise ValueError("list item content boundaries must be within the item boundary")


@dataclass(frozen=True, slots=True)
class Sentence(StructuralUnit):
    parent_section_id: str | None
    parent_list_item_id: str | None


@dataclass(frozen=True, slots=True)
class Clause(StructuralUnit):
    parent_sentence_id: str
    cue: str | None

    def validate(self, raw_text: str) -> None:
        StructuralUnit.validate(self, raw_text)
        if not self.parent_sentence_id:
            raise ValueError("clause parent_sentence_id must be non-empty")


@dataclass(frozen=True, slots=True)
class DocumentStructure:
    sections: tuple[Section, ...]
    list_blocks: tuple[ListBlock, ...]
    list_items: tuple[ListItem, ...]
    sentences: tuple[Sentence, ...]
    clauses: tuple[Clause, ...]

    def validate(self, raw_text: str) -> None:
        for unit in (
            *self.sections,
            *self.list_blocks,
            *self.list_items,
            *self.sentences,
            *self.clauses,
        ):
            unit.validate(raw_text)
        section_ids = {section.unit_id for section in self.sections}
        block_ids = {block.unit_id for block in self.list_blocks}
        item_ids = {item.unit_id for item in self.list_items}
        sentence_ids = {sentence.unit_id for sentence in self.sentences}
        if any(
            block.parent_section_id is not None and block.parent_section_id not in section_ids
            for block in self.list_blocks
        ):
            raise ValueError("list block parent_section_id must identify a section")
        if any(item.parent_list_id not in block_ids for item in self.list_items):
            raise ValueError("list item parent_list_id must identify a list block")
        if any(
            item.parent_section_id is not None and item.parent_section_id not in section_ids
            for item in self.list_items
        ):
            raise ValueError("list item parent_section_id must identify a section")
        if any(
            sentence.parent_section_id is not None and sentence.parent_section_id not in section_ids
            for sentence in self.sentences
        ):
            raise ValueError("sentence parent_section_id must identify a section")
        if any(
            sentence.parent_list_item_id is not None
            and sentence.parent_list_item_id not in item_ids
            for sentence in self.sentences
        ):
            raise ValueError("sentence parent_list_item_id must identify a list item")
        if any(clause.parent_sentence_id not in sentence_ids for clause in self.clauses):
            raise ValueError("clause parent_sentence_id must identify a sentence")

    def to_dict(self) -> dict[str, list[dict[str, object]]]:
        return {
            "sections": [asdict(unit) for unit in self.sections],
            "list_blocks": [asdict(unit) for unit in self.list_blocks],
            "list_items": [asdict(unit) for unit in self.list_items],
            "sentences": [asdict(unit) for unit in self.sentences],
            "clauses": [asdict(unit) for unit in self.clauses],
        }


@dataclass(frozen=True, slots=True)
class _Line:
    start: int
    content_end: int
    end: int


class StructuralAnalyzer:
    """Rule-configured structural analysis with only raw-text offsets."""

    def __init__(self, config: StructuralAnalyzerConfig | None = None) -> None:
        self._config = config or StructuralAnalyzerConfig()

    def analyze(self, document: SourceDocument) -> DocumentStructure:
        if not isinstance(document, SourceDocument):
            raise TypeError("document must be a SourceDocument")
        raw_text = document.raw_text
        lines = _line_ranges(raw_text)
        sections = self._find_sections(raw_text, lines)
        list_blocks, list_items = self._find_lists(raw_text, lines, sections)
        sentences = self._find_sentences(raw_text, sections, list_items)
        clauses = self._find_clauses(raw_text, sentences)
        structure = DocumentStructure(sections, list_blocks, list_items, sentences, clauses)
        structure.validate(raw_text)
        return structure

    def _find_sections(self, text: str, lines: tuple[_Line, ...]) -> tuple[Section, ...]:
        headings: list[tuple[_Line, SectionHeadingRule]] = []
        for line in lines:
            rule = self._match_heading(text[line.start : line.content_end])
            if rule is not None:
                headings.append((line, rule))
        sections: list[Section] = []
        for index, (line, rule) in enumerate(headings):
            end = headings[index + 1][0].start if index + 1 < len(headings) else len(text)
            sections.append(
                Section(
                    f"section:{index}",
                    line.start,
                    end,
                    text[line.start : end],
                    (rule.rule_id,),
                    rule.label,
                    line.start,
                    line.content_end,
                )
            )
        return tuple(sections)

    def _find_lists(
        self, text: str, lines: tuple[_Line, ...], sections: tuple[Section, ...]
    ) -> tuple[tuple[ListBlock, ...], tuple[ListItem, ...]]:
        heading_starts = {section.heading_start for section in sections}
        marked = [
            line
            for line in lines
            if line.start not in heading_starts
            and _list_marker(text[line.start : line.content_end])
        ]
        groups = _contiguous_groups(marked)
        item_specs: list[tuple[tuple[_Line, ...], str]] = []
        for group in groups:
            first_marker = _list_marker(text[group[0].start : group[0].content_end])
            assert first_marker is not None
            rule_id = (
                self._config.numbered_list_rule_id
                if first_marker.group("number")
                else self._config.bullet_list_rule_id
            )
            item_specs.append((group, rule_id))

        marked_starts = {line.start for line in marked}
        for section in sections:
            if section.label != "medication_history":
                continue
            candidates = tuple(
                line
                for line in lines
                if section.heading_end < line.start < section.end
                and line.start not in marked_starts
                and text[line.start : line.content_end].strip()
            )
            for group in _contiguous_groups(candidates):
                if len(group) >= 2:
                    item_specs.append((group, self._config.medication_lines_rule_id))

        item_specs.sort(key=lambda item_spec: item_spec[0][0].start)
        blocks: list[ListBlock] = []
        items: list[ListItem] = []
        for block_index, (group, rule_id) in enumerate(item_specs):
            block_id = f"list:{block_index}"
            parent_section = _containing_section(group[0].start, sections)
            block_items: list[ListItem] = []
            for line in group:
                line_text = text[line.start : line.content_end]
                marker = _list_marker(line_text)
                content_start = line.start + (marker.end() if marker else 0)
                item_id = f"list_item:{len(items) + len(block_items)}"
                block_items.append(
                    ListItem(
                        item_id,
                        line.start,
                        line.content_end,
                        line_text,
                        (rule_id,),
                        block_id,
                        parent_section.unit_id if parent_section else None,
                        content_start,
                        line.content_end,
                    )
                )
            items.extend(block_items)
            blocks.append(
                ListBlock(
                    block_id,
                    group[0].start,
                    group[-1].content_end,
                    text[group[0].start : group[-1].content_end],
                    (rule_id,),
                    parent_section.unit_id if parent_section else None,
                    tuple(item.unit_id for item in block_items),
                )
            )
        return tuple(blocks), tuple(items)

    def _find_sentences(
        self, text: str, sections: tuple[Section, ...], items: tuple[ListItem, ...]
    ) -> tuple[Sentence, ...]:
        sentences: list[Sentence] = []
        for start, end, rule_id in _sentence_ranges(text, self._config.medical_abbreviations):
            section = _containing_section(start, sections)
            item = next((item for item in items if item.start <= start and end <= item.end), None)
            sentences.append(
                Sentence(
                    f"sentence:{len(sentences)}",
                    start,
                    end,
                    text[start:end],
                    (rule_id,),
                    section.unit_id if section else None,
                    item.unit_id if item else None,
                )
            )
        return tuple(sentences)

    def _find_clauses(self, text: str, sentences: tuple[Sentence, ...]) -> tuple[Clause, ...]:
        clauses: list[Clause] = []
        for sentence in sentences:
            matches = _cue_matches(
                text, sentence.start, sentence.end, self._config.clause_cue_rules
            )
            starts = [sentence.start, *(match.start for match in matches)]
            ends = [*(match.start for match in matches), sentence.end]
            for index, (start, end) in enumerate(zip(starts, ends, strict=True)):
                if start == end:
                    continue
                cue_rule = matches[index - 1].rule if index else None
                clauses.append(
                    Clause(
                        f"clause:{len(clauses)}",
                        start,
                        end,
                        text[start:end],
                        (cue_rule.rule_id,) if cue_rule else ("clause.unsplit",),
                        sentence.unit_id,
                        cue_rule.cue if cue_rule else None,
                    )
                )
        return tuple(clauses)

    def _match_heading(self, line: str) -> SectionHeadingRule | None:
        candidate = re.sub(r"^\s*(?:\d+[.)]\s*)?", "", line).strip().rstrip(":").casefold()
        for rule in self._config.section_heading_rules:
            if candidate in (alias.casefold() for alias in rule.aliases):
                return rule
        return None


@dataclass(frozen=True, slots=True)
class _CueMatch:
    start: int
    rule: ClauseCueRule


_LIST_MARKER = re.compile(r"^\s*(?:(?P<number>\d+[.)])|(?P<bullet>[-*•–]))\s+")


def _list_marker(line: str) -> re.Match[str] | None:
    return _LIST_MARKER.match(line)


def _line_ranges(text: str) -> tuple[_Line, ...]:
    lines: list[_Line] = []
    start = 0
    while start < len(text):
        content_end = start
        while content_end < len(text) and text[content_end] not in "\r\n":
            content_end += 1
        if content_end == len(text):
            lines.append(_Line(start, len(text), len(text)))
            break
        newline_end = content_end + 1
        if text[content_end] == "\r" and newline_end < len(text) and text[newline_end] == "\n":
            newline_end += 1
        lines.append(_Line(start, content_end, newline_end))
        start = newline_end
    return tuple(lines)


def _contiguous_groups(lines: list[_Line] | tuple[_Line, ...]) -> list[tuple[_Line, ...]]:
    groups: list[list[_Line]] = []
    for line in lines:
        if not groups or line.start != groups[-1][-1].end:
            groups.append([line])
        else:
            groups[-1].append(line)
    return [tuple(group) for group in groups]


def _containing_section(position: int, sections: tuple[Section, ...]) -> Section | None:
    return next((section for section in sections if section.start <= position < section.end), None)


def _sentence_ranges(text: str, abbreviations: tuple[str, ...]) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    start = 0
    index = 0
    while index < len(text):
        character = text[index]
        separator_length = 0
        rule_id: str | None = None
        if character in "!?;":
            separator_length, rule_id = 1, "sentence.punctuation"
        elif (
            character == "."
            and not _is_decimal(text, index)
            and not _is_abbreviation(text, index, abbreviations)
        ):
            separator_length, rule_id = 1, "sentence.period"
        elif character in "\r\n":
            separator_length, rule_id = 1, "sentence.newline"
            if character == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                separator_length = 2
        elif character == ":" and (index + 1 == len(text) or text[index + 1] in "\r\n"):
            separator_length, rule_id = 1, "sentence.heading_colon"
        if rule_id is None:
            index += 1
            continue
        span_start, span_end = _trim_span(text, start, index + separator_length)
        if span_start < span_end:
            ranges.append((span_start, span_end, rule_id))
        start = index + separator_length
        index = start
    span_start, span_end = _trim_span(text, start, len(text))
    if span_start < span_end:
        ranges.append((span_start, span_end, "sentence.eof"))
    return ranges


def _is_decimal(text: str, index: int) -> bool:
    return 0 < index < len(text) - 1 and text[index - 1].isdigit() and text[index + 1].isdigit()


def _is_abbreviation(text: str, index: int, abbreviations: tuple[str, ...]) -> bool:
    start = index
    while start > 0 and text[start - 1].isalpha():
        start -= 1
    return text[start:index].casefold() in abbreviations


def _trim_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _cue_matches(
    text: str, start: int, end: int, rules: tuple[ClauseCueRule, ...]
) -> list[_CueMatch]:
    matches: list[_CueMatch] = []
    for rule in rules:
        for match in re.finditer(
            r"(?<!\w)" + re.escape(rule.cue) + r"(?!\w)", text[start:end], re.IGNORECASE
        ):
            matches.append(_CueMatch(start + match.start(), rule))
    return sorted(matches, key=lambda match: match.start)
