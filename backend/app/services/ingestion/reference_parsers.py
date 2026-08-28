"""
Turning reference documents into addressable chunks.

Different from `chunking_service`, which splits a *lesson* for the chatbot.
A reference chunk needs one thing a lesson chunk does not: an ADDRESS. When
the generator is shown a Psalm it has to be able to say "Tehillim 34:19" and be
right, and the only way to guarantee that is for the address to be attached to
the text before the model ever sees it — never reconstructed afterwards.

So each parser here returns `(ref, heading, text)` triples, and `ref` is
computed from the document's own structure rather than inferred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.ingestion.base import has_hebrew, normalise


@dataclass
class ReferenceChunk:
    ref: str | None
    heading: str | None
    text: str
    metadata: dict = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


# Hebrew word SEPARATORS, plus the exotic spaces this corpus is littered with.
# These become a space. Deleting them instead — as this originally did — welds
# two words into one: "כׇּל־עַצְמוֹתַי" becomes "כלעצמותי", which then matches
# nothing, and a lesson quoting Tehillim 35:10 correctly gets reported as having
# invented it.
HEBREW_SEPARATORS = re.compile(
    "[־׀׃׆  -   　]"
)

# Vowel points, cantillation, rafe, the shin/sin dots, and the geresh and
# gershayim used as abbreviation marks. These are deleted.
#
# Stripped only for MATCHING — the stored text always keeps its pointing.
HEBREW_MARKS = re.compile(
    "[֑-ׇֽֿׁׂׅׄ׳״]"
)


def strip_marks(text: str) -> str:
    """
    Consonantal skeleton, for comparing quotations across editions.

    Must stay byte-identical in behaviour to `hebrew_plain()` in the database
    (migration 0010). One side normalises the stored corpus and the other
    normalises what a lesson said; if the two ever disagree, every comparison
    fails and the grounding check silently reports correct quotations as
    fabricated. There is a test asserting they agree.
    """
    without_marks = HEBREW_MARKS.sub("", HEBREW_SEPARATORS.sub(" ", text))
    return re.sub(r"\s+", " ", without_marks).strip()


# ============================================================== Nishmat ==

# A stanza break in the plain-text Nishmat file. The prayer is stored one
# clause per line with blank lines between stanzas, which is how it is chanted
# and how the lesson series walks through it.
STANZA_BREAK = re.compile(r"\n\s*\n")


def parse_nishmat(text: str, *, variant: str) -> list[ReferenceChunk]:
    """
    Split the prayer into its stanzas.

    One chunk per stanza, not per line. A single line — "וְרוֹפֵא חוֹלִים" — is
    four words with no context; embedded alone it retrieves for anything about
    healing and tells the writer nothing about where in the prayer it sits.
    The stanza is the smallest unit that still means something.

    Every line is ALSO recorded in the chunk's metadata, so a lesson built
    around one phrase can be given that phrase exactly as written without a
    second lookup.
    """
    body = normalise(text).strip()

    # The file opens with a title line; it is not part of the prayer.
    lines = body.splitlines()
    title = lines[0].strip() if lines and not lines[0].startswith(("נִ", "נשמת כל חי –")) else None
    if lines and "–" in lines[0] and len(lines[0].split()) <= 8:
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()

    chunks: list[ReferenceChunk] = []
    for index, stanza in enumerate(STANZA_BREAK.split(body), start=1):
        stanza = stanza.strip()
        if not stanza:
            continue

        stanza_lines = [line.strip() for line in stanza.splitlines() if line.strip()]
        chunks.append(
            ReferenceChunk(
                ref=f"Nishmat {index}",
                heading=f"Nishmat Kol Chai ({variant}) — stanza {index}",
                text=stanza,
                metadata={
                    "variant": variant,
                    "stanza": index,
                    "lines": stanza_lines,
                    "opening": stanza_lines[0] if stanza_lines else None,
                    "document_title": title,
                },
            )
        )

    return chunks


# ============================================================= Tehillim ==

CHAPTER_MARKER = re.compile(r"^\d{1,3}$")

# Long psalms are split so no single chunk swamps a prompt. 119 alone is 176
# verses; sent whole it would be most of the context window and would drown
# every other source in the prompt.
VERSES_PER_CHUNK = 12


def parse_tehillim(paragraphs: list[str]) -> list[ReferenceChunk]:
    """
    Parse the Psalms document into per-passage chunks.

    The document alternates Hebrew verse / English rendering, under bare
    numeric chapter headings. Both are kept: the Hebrew is the citable text,
    and the English lets the retrieval embedding actually find a psalm from an
    English-language topic like "the one who saves the poor from the strong".
    Embedding vocalised Hebrew alone retrieves badly for English queries, which
    is what every query from this admin will be.
    """
    chapters: dict[int, list[tuple[str, str]]] = {}
    current: int | None = None
    pending_hebrew: str | None = None

    for raw in paragraphs:
        line = normalise(raw).strip()
        if not line:
            continue

        if CHAPTER_MARKER.match(line):
            number = int(line)
            if 1 <= number <= 150:
                current = number
                chapters.setdefault(current, [])
                pending_hebrew = None
                continue

        if current is None:
            continue  # the document's own title line

        if has_hebrew(line):
            # Two Hebrew lines in a row means the previous one had no English
            # rendering; keep it rather than silently dropping a verse.
            if pending_hebrew is not None:
                chapters[current].append((pending_hebrew, ""))
            pending_hebrew = line
        elif pending_hebrew is not None:
            chapters[current].append((pending_hebrew, line))
            pending_hebrew = None

    if current is not None and pending_hebrew is not None:
        chapters[current].append((pending_hebrew, ""))

    chunks: list[ReferenceChunk] = []
    for number in sorted(chapters):
        verses = chapters[number]
        if not verses:
            continue

        for start in range(0, len(verses), VERSES_PER_CHUNK):
            window = verses[start : start + VERSES_PER_CHUNK]
            first, last = start + 1, start + len(window)

            ref = f"Tehillim {number}"
            if len(verses) > VERSES_PER_CHUNK:
                ref = f"Tehillim {number}:{first}-{last}"

            lines: list[str] = []
            for offset, (hebrew, english) in enumerate(window, start=first):
                lines.append(f"{offset}. {hebrew}".strip())
                if english:
                    lines.append(f"   {english}")

            chunks.append(
                ReferenceChunk(
                    ref=ref,
                    heading=f"Psalm {number}"
                    + (f", verses {first}–{last}" if len(verses) > VERSES_PER_CHUNK else ""),
                    text="\n".join(lines),
                    metadata={
                        "psalm": number,
                        "verse_from": first,
                        "verse_to": last,
                        "verse_count": len(window),
                        "hebrew": [hebrew for hebrew, _ in window],
                    },
                )
            )

    return chunks


# =========================================================== commentary ==

# A heading in the client's reference documents: short, no terminal full stop.
# Detected structurally rather than from Word styles, because these documents
# are pasted together from several sources and their styling is inconsistent.
MAX_HEADING_WORDS = 14
COMMENTARY_MAX_WORDS = 340


def parse_commentary(paragraphs: list[str], *, title: str) -> list[ReferenceChunk]:
    """
    Split an interpretive document on its own headings.

    Section-by-heading rather than a fixed window: these documents are
    organised as short thematic essays, and cutting one in half mid-argument
    produces a chunk that states a claim without the reasoning that qualifies
    it — the fastest possible route to the model repeating a half-claim as
    fact.
    """
    sections: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    body: list[str] = []

    for raw in paragraphs:
        line = normalise(raw).strip()
        if not line:
            continue

        if _looks_like_heading(line):
            if body:
                sections.append((heading, body))
                body = []
            heading = line
            continue

        body.append(line)

    if body:
        sections.append((heading, body))

    chunks: list[ReferenceChunk] = []
    for heading_text, lines in sections:
        for piece in _window(lines):
            index = len(chunks) + 1
            chunks.append(
                ReferenceChunk(
                    ref=f"{title} §{index}",
                    heading=heading_text,
                    text=(f"{heading_text}\n\n{piece}" if heading_text else piece),
                    metadata={"section": heading_text, "document_title": title},
                )
            )

    return chunks


def _looks_like_heading(line: str) -> bool:
    words = line.split()
    if not (1 <= len(words) <= MAX_HEADING_WORDS):
        return False
    if line.endswith((".", ",", ";", ":", "?", "!")):
        # A colon-terminated line is usually a label introducing a list, which
        # belongs with the text under it rather than above it as a heading.
        return line.endswith(":") and len(words) <= 5
    return True


# The embedding model refuses anything over 8192 tokens, and refuses the whole
# BATCH when one item is too long — so a single oversized chunk does not degrade
# a document, it loses all of it. This is the ceiling every piece is held under,
# with headroom for the title and heading prefixed at embedding time.
MAX_EMBED_TOKENS = 6000

HEBREW_CHAR = re.compile(r"[֐-׿]")


def estimate_tokens(text: str) -> int:
    """
    A deliberately pessimistic token estimate.

    Counting words does not work here. Vocalised Hebrew carries a separate
    codepoint for every vowel point, and tokenisers split it far more finely
    than Latin text — a page of pointed Hebrew can be several times the tokens
    of an English page with the same word count. A word-based budget let a
    2,000-word photographed page through as one chunk, which the embedding API
    then rejected outright, and the whole page went unindexed.

    Overshooting costs a slightly smaller chunk. Undershooting costs the
    document, so this errs high.
    """
    hebrew = len(HEBREW_CHAR.findall(text))
    other = len(text) - hebrew
    return int(hebrew * 1.2 + other * 0.35) + 1


def _window(lines: list[str]) -> list[str]:
    """
    Group a section's paragraphs into pieces small enough to embed.

    Bounded by both a word count — which is about keeping a chunk readable and
    focused — and a token estimate, which is about the hard API limit. Either
    one can close a piece.
    """
    pieces: list[str] = []
    current: list[str] = []
    words = 0
    tokens = 0

    for line in _splittable(lines):
        line_words = len(line.split())
        line_tokens = estimate_tokens(line)

        too_long = words + line_words > COMMENTARY_MAX_WORDS
        too_big = tokens + line_tokens > MAX_EMBED_TOKENS
        if (too_long or too_big) and current:
            pieces.append("\n\n".join(current))
            current, words, tokens = [], 0, 0

        current.append(line)
        words += line_words
        tokens += line_tokens

    if current:
        pieces.append("\n\n".join(current))
    return pieces or [""]


def _splittable(lines: list[str]) -> list[str]:
    """
    Break up any single line already too big to embed on its own.

    `_window` can only split BETWEEN lines, so one enormous line — a whole page
    transcribed without a blank line in it, which is exactly what a photographed
    page produces — would sail past the budget untouched.
    """
    out: list[str] = []

    for line in lines:
        if estimate_tokens(line) <= MAX_EMBED_TOKENS:
            out.append(line)
            continue

        for sentence in _sentences(line):
            if estimate_tokens(sentence) <= MAX_EMBED_TOKENS:
                out.append(sentence)
            else:
                out.extend(_slice(sentence))

    return out


SENTENCE_BREAK = re.compile(r"(?<=[.!?…׃])\s+|\n")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_BREAK.split(text) if part.strip()]


def _slice(text: str) -> list[str]:
    """
    Last resort: cut on whitespace at a width the budget can hold.

    Reached only by text with no sentence punctuation at all — a page the vision
    model transcribed as one unbroken run. A crude cut is the right outcome
    there: the alternative is losing the page entirely.
    """
    # 0.95 for the same reason `_fit_to_budget` uses it: the estimate rounds up,
    # so cutting to exactly the budget lands just over it.
    width = max(
        1, int(len(text) * MAX_EMBED_TOKENS * 0.95 / max(estimate_tokens(text), 1))
    )
    pieces: list[str] = []
    start = 0

    while start < len(text):
        end = min(start + width, len(text))
        if end < len(text):
            space = text.rfind(" ", start + width // 2, end)
            if space > start:
                end = space
        pieces.append(text[start:end].strip())
        start = end

    return [piece for piece in pieces if piece]


# ======================================================= uploaded pages ==

PAGE_MAX_WORDS = 400


def parse_uploaded_page(
    text: str, *, book: str | None, page: str | None, filename: str
) -> list[ReferenceChunk]:
    """
    Chunk a photographed book page that an admin uploaded for one lesson.

    The address is what the admin told us — the book and the page — because
    nothing in the image itself can be trusted to supply it. If they gave us
    neither, the filename is at least honest about where the text came from.
    """
    label = book or filename
    address = f"{label}, p. {page}" if page else label

    body = normalise(text).strip()
    if not body:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    pieces = _window(paragraphs) if paragraphs else [body]

    return [
        ReferenceChunk(
            ref=address if len(pieces) == 1 else f"{address} ({index}/{len(pieces)})",
            heading=label,
            text=piece,
            metadata={
                "book": book,
                "page": page,
                "filename": filename,
                "uploaded_page": True,
            },
        )
        for index, piece in enumerate(pieces, start=1)
    ]
