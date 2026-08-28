"""
Parser for the client's existing lesson corpus.

These 131 documents are the client's *already-published* work, written over
two years, so they are heterogeneous by nature: ~120 are polished lessons with
an emoji header, ~11 are raw transcripts of spoken WhatsApp recordings, and a
couple still contain leftover ChatGPT chatter that was never cleaned out.

Two deliberate choices:

1. **Deterministic, not AI.** Every field here is extracted by rule. Spending
   the client's OpenAI budget to parse documents that regex handles reliably
   would be indefensible, and rules are debuggable in a way a model is not.

2. **Faithful, not reformatted.** These lessons are imported *as they were
   written*, into a light structure. They are NOT forced into the newer
   16-section template — they were not written that way, and pretending
   otherwise would misrepresent the client's work. The admin can reformat any
   of them later through the "Reformat with template" action.

Anything the parser is unsure about is flagged for admin review rather than
guessed at silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .docx_processor import (
    ExtractionResult,
    extract_docx,
    has_hebrew,
    hebrew_ratio,
    logical_lines,
)

DEFAULT_SERIES_TITLE = "Insights into Nishmat Kol Chai"

# --------------------------------------------------------------------------
# Leftover AI-assistant text.
#
# Two of the documents were pasted straight out of ChatGPT with the
# assistant's own commentary still attached. Left in place it would be
# embedded, retrieved, and eventually quoted back to a learner as though the
# teacher had written it.
# --------------------------------------------------------------------------

# Matching one of these truncates the document from that line onward.
TRAILING_CHATTER = re.compile(
    r"^\s*(?:"
    r"this version is\b"
    r"|if you want,?\s+(?:we|i)\s+can\b"
    r"|would you like me to\b"
    r"|let me know if you\b"
    r"|i can also\b"
    r"|shall i\b"
    r")",
    re.IGNORECASE,
)

# Matching one of these drops just that line; the content around it is real.
META_LINE = re.compile(
    r"^\s*(?:"
    r"here(?:'|’)s (?:a|the) (?:revised|polished|updated|cleaned).*"
    r"|(?:revised|polished|final) (?:version|draft)\s*:?\s*"
    r"|speech\s*:\s*"
    r"|[-—–_]{3,}"
    r")\s*$",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# Header / metadata patterns
# --------------------------------------------------------------------------

# "🌸 Insights into Nishmat Kol Chai – Lesson #17", "Nishmat Kol Chai – Lesson 125",
# "Day 33", "INSIGHTS INTO NISHMAT #1 INTRODUCTION"
HEADER_NUMBER = re.compile(
    r"(?:lesson|day)\s*#?\s*(\d{1,3})\b", re.IGNORECASE
)
HEADER_SERIES = re.compile(
    r"^\s*(?:[^\w\s]\s*)?((?:insights into\s+)?nishmat(?:\s+kol\s+chai)?)",
    re.IGNORECASE,
)

# "Nishmat #17.docx", "Nishmat#12.docx", "Nishmat_13.docx", "NIshmat #54.docx"
FILENAME_NUMBER = re.compile(r"nishmat\s*[#_\- ]*(\d{1,3})", re.IGNORECASE)

LABEL_TRANSLITERATION = re.compile(r"^\s*transliteration\s*[:\-–]\s*", re.IGNORECASE)
LABEL_TRANSLATION = re.compile(r"^\s*translation\s*[:\-–]\s*", re.IGNORECASE)

SIGNOFF = re.compile(r"^\s*[—–-]\s*(rivkah|rivky)\s*$", re.IGNORECASE)

SUMMARY_HEADING = re.compile(
    r"^\s*(?:[^\w\s]\s*)?whatsapp\s+summary\s*$", re.IGNORECASE
)

# A heading is short, unpunctuated at the end, and either ends with a colon,
# opens with a decorative emoji, or uses one of the recurring section words.
HEADING_WORDS = re.compile(
    r"^\s*(?:[^\w\s]\s*)?(?:"
    r"introduction|reflection|practical|closing|conclusion|story|"
    r"the power of|a story|blessing|bracha|takeaway|insight|summary|"
    r"this week|final thought"
    r")\b",
    re.IGNORECASE,
)
LEADING_EMOJI = re.compile(r"^\s*[\U0001F300-\U0001FAFF☀-➿]")


@dataclass
class ParsedLesson:
    """One corpus document, parsed and ready to import."""

    source_path: Path
    lesson_number: int | None
    sequence_position: int
    series_title: str
    title: str
    hebrew_phrase: str | None
    transliteration: str | None
    translation: str | None
    summary: str | None
    sections: list[dict] = field(default_factory=list)
    content_text: str = ""
    word_count: int = 0
    captured_words: int = 0
    raw_word_count: int = 0
    is_transcript: bool = False
    review_notes: list[str] = field(default_factory=list)
    removed_text: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.review_notes)

    @property
    def retention(self) -> float:
        """
        Share of the cleaned source text that survived into the sections.

        A parser that silently drops content is the worst failure mode here —
        the lesson still looks fine, it is just quietly missing a paragraph.
        This makes that visible instead.
        """
        if not self.raw_word_count:
            return 1.0
        return (self.captured_words or self.word_count) / self.raw_word_count


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------


def _clean(lines: list[str]) -> tuple[list[str], list[str]]:
    """Strip assistant chatter. Returns (kept_lines, removed_lines)."""
    removed: list[str] = []

    # Only trust a trailing-chatter match in the last third of the document —
    # otherwise a legitimate sentence could truncate a whole lesson.
    cutoff = max(int(len(lines) * 0.66), len(lines) - 12)
    truncate_at: int | None = None
    for i in range(cutoff, len(lines)):
        if TRAILING_CHATTER.match(lines[i]):
            truncate_at = i
            break

    if truncate_at is not None:
        # Walk back over any immediately preceding non-blank lines that are
        # also commentary rather than lesson content.
        start = truncate_at
        while start > 0:
            prev = lines[start - 1].strip()
            if not prev:
                break
            if len(prev) < 120 and not has_hebrew(prev) and prev.endswith("."):
                start -= 1
            else:
                break
        removed.extend(l for l in lines[start:] if l.strip())
        lines = lines[:start]

    kept: list[str] = []
    for line in lines:
        if META_LINE.match(line):
            if line.strip():
                removed.append(line)
            continue
        kept.append(line)

    return kept, removed


# --------------------------------------------------------------------------
# Field extraction
# --------------------------------------------------------------------------


HEBREW_RUN = re.compile(r"[֐-׿][֐-׿\s־׀׃'\"־]*")

SEPARATORS = ("–", "—", "|", " - ", " : ", ":")

# Some lessons label the phrase rather than glossing it: "Words: הַגִּבּוֹר לָנֶצַח".
# The label is not a transliteration and must not become the lesson's title.
GLOSS_LABEL = re.compile(
    r"^(?:the\s+)?(?:words?|phrase|text|pasuk|verse|tefillah|line)\s*$",
    re.IGNORECASE,
)

# "HaGibor laNetzach – The Mighty One forever" on the line after the Hebrew.
LATIN_GLOSS_PAIR = re.compile(r"^([^–—|]{3,60})\s*[–—|]\s*(.{3,120})$")


def _hebrew_candidate(line: str) -> tuple[str, str | None] | None:
    """
    Pull a Hebrew phrase, and any inline gloss, out of one line.

    The corpus writes these several ways:
        "הַלֵּל וְזִמְרָה – Praise and Song"
        "אַתָּה אֵל | Atah Kel"
        "🌸 וְכָל לָשׁוֹן לְךָ תְּשַׁבֵּחַ"
        "🌸 Nishmat Kol Chai – Lesson #128 הַגָּדוֹל – HaGadol Shavua tov, …"

    Crucially the ratio test runs on the *split halves*, not the whole line.
    Measuring the full line fails on the most common shape here, where the
    English gloss is longer than the Hebrew it explains.

    Returns (hebrew, gloss) or None.
    """
    text = LEADING_EMOJI.sub("", line).strip()
    if not has_hebrew(text):
        return None

    for sep in SEPARATORS:
        if sep not in text:
            continue
        left, _, right = text.partition(sep)
        left, right = left.strip(), right.strip()

        if hebrew_ratio(left) > 0.7 and len(left) >= 4:
            return left, (right or None) if not has_hebrew(right) else None
        if hebrew_ratio(right) > 0.7 and len(right) >= 4 and left and not has_hebrew(left):
            return right, left or None

    if hebrew_ratio(text) > 0.7:
        return text, None

    # Mixed line with no clean separator: take the longest contiguous Hebrew
    # run. Messy, but it recovers the phrase from documents like #128 where
    # the header and the phrase were typed into a single paragraph.
    runs = [m.group().strip() for m in HEBREW_RUN.finditer(text)]
    runs = [r for r in runs if len(r) >= 6]
    if runs:
        return max(runs, key=len), None

    return None


def _looks_like_transliteration(text: str) -> bool:
    """
    A transliteration is a romanised Hebrew phrase, not an English sentence:
    few words, often apostrophes, no sentence-ending punctuation.
    """
    words = text.split()
    if not (1 <= len(words) <= 8):
        return False
    if text.endswith((".", "!", "?")) and "’" not in text and "'" not in text:
        return False
    return not text[0].isupper() or "’" in text or "'" in text or len(words) <= 4


def _extract_metadata(lines: list[str]) -> dict:
    """Pull the header block: number, series, Hebrew phrase, gloss lines."""
    found: dict = {
        "lesson_number": None,
        "series_title": None,
        "hebrew_phrase": None,
        "transliteration": None,
        "translation": None,
        "header_index": -1,
        "consumed": set(),
    }

    # Header sits in the first handful of non-blank lines.
    head = [(i, l) for i, l in enumerate(lines[:14]) if l.strip()]

    for i, line in head:
        if found["lesson_number"] is None:
            m = HEADER_NUMBER.search(line)
            if m:
                found["lesson_number"] = int(m.group(1))
                found["header_index"] = i
                # Consume the line ONLY if it is genuinely a header. In the
                # spoken transcripts the number is embedded in real content —
                # "…l'iluy nishmat Rachel bat Rut a"h. This is lesson #35." —
                # and swallowing that line threw away the opening of the lesson.
                if len(line) <= 100:
                    found["consumed"].add(i)
                sm = HEADER_SERIES.match(line)
                if sm:
                    found["series_title"] = _tidy_series(sm.group(1))

        if found["hebrew_phrase"] is None:
            candidate = _hebrew_candidate(line)
            if candidate:
                hebrew, gloss = candidate
                found["hebrew_phrase"] = hebrew
                # Same rule: a Hebrew phrase pulled out of a long mixed line
                # must not take the rest of that line down with it.
                if len(line) <= 140:
                    found["consumed"].add(i)
                if gloss:
                    # Strip any leftover header text from the gloss.
                    gloss = HEADER_NUMBER.sub("", gloss).strip(" -–—|")
                    if not gloss or GLOSS_LABEL.match(gloss):
                        gloss = None
                    elif _looks_like_transliteration(gloss):
                        found["transliteration"] = gloss
                    else:
                        found["translation"] = gloss.strip('"“”')

                # No usable gloss inline? The next line often carries it as
                # "HaGibor laNetzach – The Mighty One forever".
                if not gloss:
                    nxt = next(
                        (l for j, l in head if j > i and l.strip()), None
                    )
                    if nxt and not has_hebrew(nxt):
                        pair = LATIN_GLOSS_PAIR.match(nxt.strip())
                        if pair:
                            left, right = pair.group(1).strip(), pair.group(2).strip()
                            if _looks_like_transliteration(left):
                                found["transliteration"] = left
                                found["translation"] = right.strip('"“”')
                                found["consumed"].add(
                                    next(j for j, l in head if l is nxt)
                                )

        if LABEL_TRANSLITERATION.match(line):
            found["transliteration"] = LABEL_TRANSLITERATION.sub("", line).strip()
            found["consumed"].add(i)
        elif LABEL_TRANSLATION.match(line):
            found["translation"] = (
                LABEL_TRANSLATION.sub("", line).strip().strip('"“”')
            )
            found["consumed"].add(i)

    return found


def _tidy_series(raw: str) -> str:
    cleaned = " ".join(raw.split()).strip()
    if cleaned.lower().startswith("insights into"):
        return "Insights into Nishmat Kol Chai"
    return DEFAULT_SERIES_TITLE


def _is_heading(line: str, next_line: str | None) -> bool:
    text = line.strip()
    if not text or len(text) > 90 or has_hebrew(text):
        return False
    if text.endswith((".", "!", "?", ",", ";")):
        return False
    if not next_line or not next_line.strip():
        # A lone short line followed by nothing is a sign-off or a fragment,
        # not a heading.
        return False
    return bool(
        text.endswith(":") or LEADING_EMOJI.match(text) or HEADING_WORDS.match(text)
    )


def _build_sections(
    lines: list[str], meta: dict, series_title: str, lesson_number: int | None
) -> tuple[list[dict], str | None]:
    """Assemble the ordered section list. Returns (sections, whatsapp_summary)."""
    sections: list[dict] = []
    order = 0

    def add(key: str, body: str, *, title: str | None = None, dir_: str = "ltr"):
        nonlocal order
        if not body or not body.strip():
            return
        order += 1
        sections.append(
            {
                "key": key,
                "title": title,
                "body": body.strip("\n").rstrip(),
                "dir": dir_,
                "order": order,
            }
        )

    add("series_title", series_title)
    if lesson_number is not None:
        add("lesson_number", f"Lesson #{lesson_number}")
    if meta["hebrew_phrase"]:
        add("hebrew_phrase", meta["hebrew_phrase"], dir_="rtl")
    if meta["transliteration"]:
        add("transliteration", meta["transliteration"])
    if meta["translation"]:
        add("translation", meta["translation"])

    # The body is every line that was NOT consumed as header metadata.
    #
    # Not "everything after the header block": in the raw transcripts the
    # speaker opens with her greeting and only quotes the Hebrew phrase a few
    # lines in, so slicing from the last consumed index silently threw away
    # the opening of the lesson.
    consumed: set[int] = meta["consumed"]
    body_lines = [line for i, line in enumerate(lines) if i not in consumed]

    # Sign-off, if the document ends with one.
    signoff: str | None = None
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    if body_lines and SIGNOFF.match(body_lines[-1]):
        signoff = body_lines.pop().strip()

    # Split off a trailing summary block.
    #
    # Some lessons label it "WhatsApp Summary"; most just repeat the lesson
    # header near the end and write the recap under it. Only the explicit
    # label appears in a handful of documents, so the header-repeat case has
    # to be handled too or most summaries end up buried in the body.
    summary_text: str | None = None
    summary_start: int | None = None
    tail_begins = int(len(body_lines) * 0.55)

    for i, line in enumerate(body_lines):
        if SUMMARY_HEADING.match(line):
            summary_start = i + 1
            body_cut = i
            break
        if (
            i > tail_begins
            and HEADER_NUMBER.search(line)
            and HEADER_SERIES.match(line)
            and len(line) < 90
        ):
            # A repeat of the lesson header this far down starts the recap.
            summary_start = i
            body_cut = i
            break
    else:
        body_cut = None

    if summary_start is not None and body_cut is not None:
        summary_text = "\n".join(body_lines[summary_start:]).strip()
        body_lines = body_lines[:body_cut]

    # Group the remaining body under any detected headings.
    current_title: str | None = None
    buffer: list[str] = []
    index = 0

    def flush():
        nonlocal buffer, current_title, index
        text = "\n".join(buffer).strip("\n")
        if text.strip():
            index += 1
            add(f"body_{index}", text, title=current_title)
        buffer = []

    for i, line in enumerate(body_lines):
        nxt = body_lines[i + 1] if i + 1 < len(body_lines) else None
        if _is_heading(line, nxt):
            flush()
            current_title = line.strip().rstrip(":")
            continue
        buffer.append(line)
    flush()

    if summary_text:
        add("whatsapp_summary", summary_text, title="WhatsApp summary")
    if signoff:
        add("signoff", signoff)

    return sections, summary_text


TITLE_MAX = 70


def _tidy_title(text: str) -> str | None:
    """Clean a title candidate, or reject it."""
    text = LEADING_EMOJI.sub("", text).strip().strip("\"“”'’ ,;:-–—")
    if not text or len(text) < 4:
        return None

    # Reject the series header — but only when the candidate IS the header.
    # "Nishmat kol chai" is also the opening phrase of the prayer itself, so
    # a substring match wrongly threw away the correct titles for #1–#3.
    normalised = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if normalised in {
        "insights into nishmat kol chai",
        "insights into nishmat",
        "nishmat kol chai",
        "nishmat",
    }:
        return None
    if len(text) <= TITLE_MAX:
        return text
    cut = text[:TITLE_MAX].rsplit(" ", 1)[0].rstrip(",;:-–—")
    return f"{cut}…"


def _derive_title(meta: dict, sections: list[dict], lesson_number: int | None) -> str:
    """
    The lesson's title is the phrase it teaches.

    Transliteration alone — NOT transliteration plus translation. Joining the
    two produced 90-character titles that were unreadable on a lesson card,
    and the translation is already shown on the card in its own right.
    """
    for candidate in (meta.get("transliteration"), meta.get("translation")):
        if candidate:
            tidy = _tidy_title(candidate)
            if tidy:
                return tidy

    for section in sections:
        if section["key"].startswith("body_") and section.get("title"):
            title = section["title"]
            # "Introduction: Guiding the World with Kindness" -> the useful half
            if ":" in title:
                title = title.split(":", 1)[1].strip() or title
            # A heading that reads as a sentence is not a title.
            if re.match(r"^(someone|this|the lesson|we |it |there )", title, re.I):
                continue
            tidy = _tidy_title(title)
            if tidy:
                return tidy

    if meta.get("hebrew_phrase"):
        tidy = _tidy_title(meta["hebrew_phrase"])
        if tidy:
            return tidy

    return f"Lesson #{lesson_number}" if lesson_number is not None else "Untitled lesson"


def _derive_summary(sections: list[dict]) -> str | None:
    """First substantial body sentence(s), for the lesson card."""
    for section in sections:
        if not section["key"].startswith("body_"):
            continue
        for line in section["body"].split("\n"):
            text = line.strip()
            if len(text) < 60 or has_hebrew(text):
                continue
            # Skip the greeting line — it is the same in most lessons.
            if re.match(r"^(shavua tov|good (morning|evening)|motzaei)", text, re.I):
                continue
            if len(text) <= 190:
                return text
            cut = text[:190].rsplit(" ", 1)[0]
            return cut + "…"
    return None


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def parse_corpus_file(path: Path) -> ParsedLesson:
    extraction: ExtractionResult = extract_docx(path)
    raw_lines = logical_lines(extraction.paragraphs)

    lines, removed = _clean(raw_lines)
    meta = _extract_metadata(lines)

    # Filename number is the fallback, and the cross-check.
    filename_match = FILENAME_NUMBER.search(path.stem)
    filename_number = int(filename_match.group(1)) if filename_match else None

    review: list[str] = []
    header_number = meta["lesson_number"]
    is_introduction = False

    # The FILENAME wins. It is the client's own filing system and is
    # unambiguous; the document body is not. `Nishmat #35.docx` contains a
    # stray "36" mid-text, and trusting the body there collided with the real
    # lesson #36 and silently lost one of the two.
    if filename_number is not None:
        lesson_number = filename_number
        if header_number is not None and header_number != filename_number:
            review.append(
                f"Lesson number mismatch: filename says #{filename_number}, "
                f"the document text says #{header_number}. Using the filename — "
                f"please confirm which is right."
            )
    elif "introduction" in path.stem.lower():
        # The series opener. Number 0 so it sorts before Lesson #1, which is
        # the polished rewrite of this same recording.
        lesson_number = 0
        is_introduction = True
    else:
        lesson_number = header_number

    if lesson_number is None:
        review.append("No lesson number found in the filename or the document.")

    series_title = meta["series_title"] or DEFAULT_SERIES_TITLE
    sections, summary_block = _build_sections(lines, meta, series_title, lesson_number)

    title = (
        "Introduction"
        if is_introduction
        else _derive_title(meta, sections, lesson_number)
    )

    content_text = "\n\n".join(s["body"] for s in sections)
    word_count = len(content_text.split())

    # Retention counts section titles too — a detected heading is still the
    # lesson's words, just promoted out of the body. Excluding them would make
    # the metric flag correct parses.
    captured_words = word_count + sum(
        len(s["title"].split()) for s in sections if s.get("title")
    )
    # Everything the cleaner kept — the yardstick for the retention check.
    raw_word_count = len("\n".join(lines).split())

    # A raw transcript is one of the spoken WhatsApp recordings typed up
    # verbatim: no decorative header, no "Transliteration:" label, and it opens
    # straight into speech ("Shavua tov beautiful neshamot! We are learning…").
    first_lines = [l for l in lines[:4] if l.strip()]
    has_decorated_header = any(LEADING_EMOJI.match(l) for l in first_lines)
    opens_with_speech = bool(
        first_lines
        and re.match(
            r"^\s*(?:day\s+\d+\s+)?(?:shavua tov|good (?:morning|evening)|"
            r"insights into nishmat\b.*introduction|today,|motzaei)",
            first_lines[0],
            re.IGNORECASE,
        )
    )
    is_transcript = (
        not has_decorated_header
        and meta["transliteration"] is None
        and (opens_with_speech or meta["header_index"] != 0)
    )

    # ---- review flags ----
    if removed:
        review.append(
            f"Removed {len(removed)} line(s) of leftover AI-assistant text during import."
        )
    if word_count < 200:
        review.append(f"Very short ({word_count} words) — may be incomplete.")
    if not meta["hebrew_phrase"]:
        review.append("No Hebrew phrase detected.")
    if not meta["transliteration"] and not meta["translation"]:
        review.append("No transliteration or translation detected.")

    # Guard against the parser silently swallowing part of the lesson. The
    # section bodies should account for essentially all of the cleaned text;
    # a shortfall means a rule dropped something it should not have.
    if raw_word_count and captured_words / raw_word_count < 0.92:
        review.append(
            f"Only {captured_words}/{raw_word_count} words were captured "
            f"({captured_words / raw_word_count:.0%}) — the parser may have "
            f"dropped content."
        )

    return ParsedLesson(
        source_path=path,
        lesson_number=lesson_number,
        sequence_position=lesson_number if lesson_number is not None else 999,
        series_title=series_title,
        title=title,
        hebrew_phrase=meta["hebrew_phrase"],
        transliteration=meta["transliteration"],
        translation=meta["translation"],
        summary=_derive_summary(sections),
        sections=sections,
        content_text=content_text,
        word_count=word_count,
        captured_words=captured_words,
        raw_word_count=raw_word_count,
        is_transcript=is_transcript,
        review_notes=review,
        removed_text=removed,
    )


def parse_corpus_directory(directory: Path) -> list[ParsedLesson]:
    """Parse every .docx, skipping Word's `~$` lock files."""
    files = sorted(
        p for p in directory.glob("*.docx") if not p.name.startswith("~$")
    )
    return [parse_corpus_file(p) for p in files]
