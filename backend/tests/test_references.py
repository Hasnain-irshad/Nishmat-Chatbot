"""
The reference pipeline: parsing, briefs, prompt assembly, grounding.

Pure unit tests over the real reference files — no database, no network, no API
key. The parsers are checked against the actual documents rather than against
fixtures, because the failure this guards against is a document arriving in a
slightly different shape and the corpus silently indexing half of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.grounding_service import (
    _check_attributions,
    _check_psalms,
    _hebrew_quotes,
)
from app.services.ingestion.base import normalise
from app.services.ingestion.reference_parsers import (
    parse_commentary,
    parse_nishmat,
    parse_tehillim,
    parse_uploaded_page,
    strip_marks,
)
from app.services.reference_service import (
    LessonBrief,
    ReferenceBundle,
    ReferenceItem,
    _match_stanza,
    _parse_psalm_numbers,
)

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "Reference" / "Nishmat"

NISHMAT_FILE = REFERENCE / "edut_hamizrach" / "nishmat_edut_hamizrach.txt"
TEHILLIM_FILE = REFERENCE / "tehillim" / "tehillim_hebrew_150_psalms.docx"
COMMENTARY_FILE = REFERENCE / "The magnificent Nishmat Kol Chai.docx"

# From the Edot HaMizrach text, exactly as stored.
HEALING_LINE = "וְרוֹפֵא חוֹלִים"
OPENING = "נִשְׁמַת כָּל חַי תְּבָרֵךְ אֶת שִׁמְךָ"


def _paragraphs(path: Path) -> list[str]:
    import docx

    return [p.text for p in docx.Document(str(path)).paragraphs]


@pytest.fixture(scope="module")
def nishmat():
    if not NISHMAT_FILE.exists():
        pytest.skip("the Nishmat reference file is not present")
    return parse_nishmat(
        NISHMAT_FILE.read_text(encoding="utf-8"), variant="Edot HaMizrach"
    )


@pytest.fixture(scope="module")
def tehillim():
    if not TEHILLIM_FILE.exists():
        pytest.skip("the Tehillim reference file is not present")
    return parse_tehillim(_paragraphs(TEHILLIM_FILE))


# ================================================================ Nishmat ==


def test_nishmat_splits_into_stanzas(nishmat):
    assert len(nishmat) >= 10
    assert nishmat[0].ref == "Nishmat 1"
    assert nishmat[0].text.startswith("נִשְׁמַת כָּל חַי")


def test_nishmat_keeps_every_vowel_point(nishmat):
    """
    The whole point of storing the text is that it can be quoted exactly. A
    parser that dropped a vowel point would make every generated quotation
    subtly wrong and nothing downstream would catch it.

    Compared after NFC, not byte for byte: the source file is not in canonical
    order, and NFC reorders combining marks without adding or removing any.
    That is the one normalisation this codebase does — never NFKD, which would
    decompose the pointing and destroy it.
    """
    original = normalise(NISHMAT_FILE.read_text(encoding="utf-8"))

    for stanza in nishmat:
        for line in stanza.metadata["lines"]:
            assert line in original

    # No mark was lost on the way: same count of Hebrew points in and out.
    marks_in = sum(1 for ch in original if "֑" <= ch <= "ׇ")
    marks_out = sum(
        1 for stanza in nishmat for ch in stanza.text if "֑" <= ch <= "ׇ"
    )
    assert marks_out == marks_in


def test_nishmat_records_every_line(nishmat):
    """Line-level metadata is what lets a lesson be built around one phrase."""
    assert all(chunk.metadata["lines"] for chunk in nishmat)
    all_lines = [line for chunk in nishmat for line in chunk.metadata["lines"]]
    assert any(HEALING_LINE in line for line in all_lines)


def test_title_line_is_not_a_stanza(nishmat):
    assert "נוסח עדות המזרח" not in nishmat[0].text


# =============================================================== Tehillim ==


def test_tehillim_covers_all_150(tehillim):
    psalms = {chunk.metadata["psalm"] for chunk in tehillim}
    assert psalms == set(range(1, 151))


def test_tehillim_verse_count_is_plausible(tehillim):
    """
    2,527 verses in the Masoretic text. An off-by-a-lot here means the
    Hebrew/English pairing has slipped and verses are being dropped.
    """
    total = sum(chunk.metadata["verse_count"] for chunk in tehillim)
    assert 2400 <= total <= 2900


def test_long_psalms_are_split_with_addresses(tehillim):
    psalm_119 = [c for c in tehillim if c.metadata["psalm"] == 119]
    assert len(psalm_119) > 1
    assert psalm_119[0].ref == "Tehillim 119:1-12"
    assert psalm_119[0].metadata["verse_from"] == 1


def test_short_psalms_keep_a_bare_address(tehillim):
    psalm_1 = [c for c in tehillim if c.metadata["psalm"] == 1]
    assert len(psalm_1) == 1
    assert psalm_1[0].ref == "Tehillim 1"


def test_tehillim_chunks_carry_both_languages(tehillim):
    """
    English travels with the Hebrew so an English-language topic can retrieve a
    psalm at all. Embedding vocalised Hebrew alone retrieves badly for exactly
    the queries this admin will type.
    """
    first = [c for c in tehillim if c.metadata["psalm"] == 1][0]
    assert "אַ" in first.text
    assert "Happy is the one" in first.text


def test_nishmat_scriptural_quotes_are_findable_in_tehillim(nishmat, tehillim):
    """
    Nishmat quotes two verses outright. Both must be locatable in the stored
    Psalms by consonantal match — that lookup is how the pipeline learns which
    Psalm a stanza rests on, instead of asking a model to remember.
    """
    # A list, not a dict keyed by psalm: a long psalm is several chunks and
    # collapsing them would silently hide every verse but the last window.
    haystack = [(c.metadata["psalm"], strip_marks(c.text)) for c in tehillim]

    found: set[int] = set()
    for stanza in nishmat:
        for line in stanza.metadata["lines"]:
            needle = strip_marks(line.strip().strip(":,.;"))
            if len(needle.split()) < 3 or len(needle.replace(" ", "")) < 12:
                continue
            for psalm, text in haystack:
                if needle in text:
                    found.add(psalm)
                    break

    # 35:10 ("כל עצמותי תאמרנה") and 33:1 ("רננו צדיקים").
    assert {33, 35} <= found


# ============================================================= commentary ==


def test_commentary_splits_on_its_own_headings():
    if not COMMENTARY_FILE.exists():
        pytest.skip("the client reference document is not present")

    chunks = parse_commentary(
        _paragraphs(COMMENTARY_FILE), title="The Magnificent Nishmat Kol Chai"
    )
    assert len(chunks) > 5
    assert any(chunk.heading for chunk in chunks)
    assert all(chunk.ref for chunk in chunks)


def test_uploaded_page_is_addressed_by_what_the_admin_said():
    chunks = parse_uploaded_page(
        "Some transcribed page text about gratitude.",
        book="ArtScroll Tehillim",
        page="412",
        filename="IMG_2201.jpg",
    )
    assert len(chunks) == 1
    assert chunks[0].ref == "ArtScroll Tehillim, p. 412"
    assert chunks[0].metadata["book"] == "ArtScroll Tehillim"


def test_uploaded_page_without_a_book_falls_back_to_the_filename():
    chunks = parse_uploaded_page(
        "text", book=None, page=None, filename="IMG_2201.jpg"
    )
    assert chunks[0].ref == "IMG_2201.jpg"


def test_empty_page_produces_nothing_rather_than_an_empty_chunk():
    assert parse_uploaded_page("   ", book="X", page=None, filename="f.jpg") == []


# ================================================================== brief ==


def test_brief_round_trips_and_ignores_blanks():
    brief = LessonBrief.from_dict(
        {"phrase": "  וְרוֹפֵא חוֹלִים  ", "theme": "", "psalm": "34:19", "junk": "x"}
    )
    assert brief.phrase == "וְרוֹפֵא חוֹלִים"
    assert brief.theme is None
    assert brief.to_dict() == {"phrase": "וְרוֹפֵא חוֹלִים", "psalm": "34:19"}
    assert not brief.is_empty


def test_empty_brief_is_empty():
    assert LessonBrief.from_dict(None).is_empty
    assert LessonBrief.from_dict({"length": "short"}).is_empty


def test_topic_query_joins_what_was_given():
    brief = LessonBrief(phrase="a", theme="b", seasonal="Elul")
    assert brief.topic_query() == "a. b. Elul"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("34", [34]),
        ("34:19", [34]),
        ("Tehillim 103", [103]),
        ("Psalm 23 and Psalms 121", [23, 121]),
        ("Ps. 150", [150]),
        ("151", []),          # out of range
        ("not a psalm", []),
    ],
)
def test_psalm_reference_parsing(text, expected):
    assert _parse_psalm_numbers(text) == expected


# =============================================================== matching ==


def _stanza(text: str) -> ReferenceItem:
    return ReferenceItem(
        kind="nishmat_text", authority="primary", ref="Nishmat 1",
        heading=None, text=text, title="Nishmat",
    )


def test_phrase_matches_its_stanza_ignoring_pointing(nishmat):
    items = [
        ReferenceItem(
            kind="nishmat_text", authority="primary", ref=c.ref, heading=c.heading,
            text=c.text, title="Nishmat", metadata=c.metadata,
        )
        for c in nishmat
    ]

    # Unpointed, as somebody would type it.
    matched = _match_stanza(items, "ורופא חולים")
    assert matched and HEALING_LINE in matched[0].text

    # Pointed, as pasted from a siddur.
    matched = _match_stanza(items, OPENING)
    assert matched and matched[0].ref == "Nishmat 1"


def test_a_phrase_that_is_not_in_the_prayer_matches_nothing():
    assert _match_stanza([_stanza("נִשְׁמַת כָּל חַי")], "בְּרֵאשִׁית בָּרָא") == []


# ============================================================== grounding ==


def test_hebrew_quotes_ignore_single_terms():
    """A word or two is her own vocabulary, not a quotation to verify."""
    assert _hebrew_quotes("She talks about חֶסֶד all the time.") == []


def test_hebrew_quotes_finds_a_real_line():
    text = f"And then she says:\n{OPENING}\nwhich is where it begins."
    quotes = _hebrew_quotes(text)
    assert len(quotes) == 1
    assert strip_marks(OPENING) == strip_marks(quotes[0])


def test_psalm_citation_outside_the_retrieved_set_is_flagged():
    issues = _check_psalms("As it says in Tehillim 62:2, wait quietly.", {33, 35})
    assert len(issues) == 1
    assert issues[0]["severity"] == "medium"
    assert "62" in issues[0]["message"]


def test_psalm_citation_inside_the_retrieved_set_passes():
    assert _check_psalms("As Tehillim 35 puts it,", {33, 35}) == []


def test_a_psalm_that_does_not_exist_is_a_high_severity_finding():
    issues = _check_psalms("Tehillim 181 teaches", {181})
    assert issues and issues[0]["severity"] == "high"


def test_no_allowed_set_means_no_psalm_findings():
    """
    An empty set means nothing was retrieved — an unloaded corpus, say. Flagging
    every citation then would bury the admin in noise about a configuration
    problem, so the check stands down and only impossible chapters are reported.
    """
    assert _check_psalms("Tehillim 23 says", set()) == []


def test_attribution_absent_from_every_source_is_flagged():
    issues = _check_attributions(
        "The Malbim explains that the soul sings.", ["nothing relevant here"]
    )
    assert len(issues) == 1
    assert "Malbim" in issues[0]["message"]


def test_attribution_present_in_a_source_passes():
    assert (
        _check_attributions(
            "The Malbim explains that the soul sings.",
            ["The Malbim, on this verse, explains that the soul sings."],
        )
        == []
    )


# ======================================================== prompt assembly ==


def test_reference_blocks_label_every_source_class():
    from app.llm import prompt_builder

    bundle = ReferenceBundle(
        primary_text=[
            ReferenceItem("nishmat_text", "primary", "Nishmat 2", None, OPENING, "Nishmat")
        ],
        scripture=[
            ReferenceItem("scripture", "primary", "Tehillim 35", None, "verse", "Tehillim")
        ],
        interpretation=[
            ReferenceItem("commentary", "client_supplied", "Doc §3", None, "essay", "Doc")
        ],
        uploaded_pages=[
            ReferenceItem(
                "commentary", "secondary", "ArtScroll, p. 412", None, "page",
                "ArtScroll", is_lesson_scoped=True,
            )
        ],
    )

    text = "\n".join(prompt_builder.build_reference_blocks(bundle))

    for marker in ("SOURCE A", "SOURCE B", "SOURCE C", "SOURCE F"):
        assert marker in text

    # The distinction that matters: the client's own document must never be
    # presented to the model with the same weight as the prayer text.
    assert "NOT an authority" in text
    assert "Tehillim 35" in text
    assert "ArtScroll, p. 412" in text


def test_no_references_produces_no_blocks():
    from app.llm import prompt_builder

    assert prompt_builder.build_reference_blocks(None) == []
    assert prompt_builder.build_reference_blocks(ReferenceBundle()) == []


def test_analysis_prompt_works_without_a_transcript():
    """
    A lesson asked for by subject has no transcript at all. Before this the
    analysis stage had nothing to read and generation was impossible.
    """
    from app.llm import prompt_builder

    messages = prompt_builder.build_analysis_messages(
        None,
        brief=LessonBrief(phrase=OPENING, theme="gratitude"),
        references=ReferenceBundle(
            primary_text=[
                ReferenceItem(
                    "nishmat_text", "primary", "Nishmat 1", None, OPENING, "Nishmat"
                )
            ]
        ),
    )
    body = messages[-1].content
    assert "no recording or transcript" in body
    assert "SOURCE A" in body
    assert OPENING in body


def test_continuity_block_names_what_was_covered_and_what_is_next():
    from app.llm import prompt_builder
    from app.models.analysis import StructuredAnalysis

    context = prompt_builder.GenerationContext(
        analysis=StructuredAnalysis(
            central_theme="x", emotional_arc="", source_coverage_notes=""
        ),
        template={},
        series=prompt_builder.SeriesContext(
            recent=[
                {"lesson_number": 41, "title": "Healing", "summary": "on refuah"},
                {"lesson_number": 40, "title": "Sleep", "summary": "on lo yanum"},
            ],
            next_lesson={"lesson_number": 43, "title": "The bones"},
        ),
    )
    text = "\n".join(prompt_builder._continuity_blocks(context))

    assert "SOURCE E" in text
    assert "#41" in text and "on refuah" in text
    assert "#43" in text
    assert "Leave that ground for it" in text


# ================================================= normalisation agreement ==

MIGRATION_0010 = (
    Path(__file__).resolve().parents[1] / "migrations" / "0010_hebrew_plain.sql"
)

# Word separators become a space; marks are deleted. Asserted as codepoints
# because both classes are literal invisible characters in the source, and
# reading them is exactly how the maqaf (U+05BE) ended up in the delete set —
# welding "kol-atzmotai" into one word and making Tehillim 35:10, which Nishmat
# quotes verbatim, unverifiable.
EXPECTED_SEPARATORS = {
    0x05BE, 0x05C0, 0x05C3, 0x05C6,
    0x00A0, 0x2000, 0x200A, 0x202F, 0x205F, 0x3000,
}
EXPECTED_MARKS = {
    0x0591, 0x05BD, 0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7,
    0x05F3, 0x05F4,
}


def _class_codepoints(pattern: str) -> set[int]:
    """Codepoints named in a regex character class, range endpoints included."""
    inner = pattern.strip("[]")
    return {ord(ch) for ch in inner if ch != "-"}


def test_separator_and_mark_classes_are_what_we_think_they_are():
    from app.services.ingestion.reference_parsers import (
        HEBREW_MARKS,
        HEBREW_SEPARATORS,
    )

    assert _class_codepoints(HEBREW_SEPARATORS.pattern) == EXPECTED_SEPARATORS
    assert _class_codepoints(HEBREW_MARKS.pattern) == EXPECTED_MARKS

    # The maqaf must never be in the delete set again.
    assert 0x05BE not in _class_codepoints(HEBREW_MARKS.pattern)


def test_sql_normalisation_uses_the_same_character_classes():
    """
    `strip_marks` and the database's `hebrew_plain()` normalise two halves of
    the same comparison — the stored corpus and what a lesson claimed. If they
    ever disagree, nothing matches and every correct quotation is reported as
    invented. This asserts the two definitions have not drifted apart.
    """
    if not MIGRATION_0010.exists():
        pytest.skip("migration 0010 is not present")

    import re

    sql = MIGRATION_0010.read_text(encoding="utf-8")
    classes = [
        _class_codepoints(match)
        for match in re.findall(r"'(\[[^\]]*\])'", sql)
    ]

    assert EXPECTED_SEPARATORS in classes, "separator class missing from the SQL"
    assert EXPECTED_MARKS in classes, "mark class missing from the SQL"


def test_maqaf_becomes_a_space_not_nothing():
    joined = "כׇּל־עַצְמוֹתַי"
    assert strip_marks(joined) == "כל עצמותי"


def test_paseq_and_sof_pasuq_do_not_survive():
    assert strip_marks("תֹּאמַרְנָה ׀ יְהֹוָ֗ה׃") == "תאמרנה יהוה"


# ============================================================ vision input ==

PAGE_IMAGE = REFERENCE / "edut_hamizrach" / "nishmat_edut_hamizrach_original.png"


def test_small_images_are_sent_untouched():
    """Re-encoding a small page costs quality and buys nothing."""
    from app.services.ingestion.image_processor import prepare_for_vision

    tiny = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
    payload, mime = prepare_for_vision(tiny)
    assert payload is tiny
    assert mime == "image/png"


def test_undecodable_bytes_pass_through_rather_than_failing():
    """
    A format we cannot decode here is not necessarily one the model cannot
    read. Refusing it would be a worse outcome than sending it as it came.
    """
    from app.services.ingestion.image_processor import (
        VISION_RECODE_ABOVE_BYTES,
        prepare_for_vision,
    )

    junk = b"\xff\xd8\xff" + b"not an image" * (VISION_RECODE_ABOVE_BYTES // 10)
    payload, mime = prepare_for_vision(junk)
    assert payload is junk
    assert mime == "image/jpeg"


def test_a_large_page_is_downscaled_and_stays_legible():
    """
    The client photographs pages with a phone. An 8 MB photo becomes 11 MB of
    base64 in a JSON body, which is what made a reference upload time out after
    six minutes and three full attempts.
    """
    if not PAGE_IMAGE.exists():
        pytest.skip("no sample page image on disk")

    pytest.importorskip("fitz")
    import fitz

    from app.services.ingestion.image_processor import (
        VISION_MAX_EDGE,
        prepare_for_vision,
    )

    # Blow the real page up well past the cap, the way a phone camera would.
    document = fitz.open(str(PAGE_IMAGE))
    big = document[0].get_pixmap(matrix=fitz.Matrix(8, 8)).tobytes("png")
    assert len(big) > 400_000, "the fixture is not large enough to exercise this"

    payload, mime = prepare_for_vision(big)

    assert mime == "image/jpeg"
    assert len(payload) < len(big)

    shrunk = fitz.Pixmap(payload)
    assert max(shrunk.width, shrunk.height) <= VISION_MAX_EDGE + 2
    # Still a real page, not a thumbnail — the nikud has to survive this.
    assert max(shrunk.width, shrunk.height) >= VISION_MAX_EDGE // 2


# ============================================================ embed budget ==


def test_a_dense_hebrew_page_is_split_small_enough_to_embed():
    """
    A photographed page arrives as one unbroken run of vocalised Hebrew with no
    blank lines in it. A word-based budget let 2,000 such words through as a
    single chunk; the embedding API rejected it, and because a rejection fails
    the whole batch, the page indexed nothing at all while reporting success.
    """
    from app.services.ingestion.reference_parsers import (
        MAX_EMBED_TOKENS,
        estimate_tokens,
    )

    if not NISHMAT_FILE.exists():
        pytest.skip("no Hebrew sample on disk")

    # One paragraph, no sentence punctuation, far over the limit.
    dense = " ".join(NISHMAT_FILE.read_text(encoding="utf-8").split()) * 12

    chunks = parse_uploaded_page(
        dense, book="ArtScroll Tehillim", page="412", filename="page.jpg"
    )

    assert len(chunks) > 1
    assert estimate_tokens(dense) > MAX_EMBED_TOKENS, "the fixture is not dense enough"
    for chunk in chunks:
        assert estimate_tokens(chunk.text) <= MAX_EMBED_TOKENS, chunk.ref

    # Nothing may be dropped on the way.
    rejoined = " ".join(" ".join(c.text.split()) for c in chunks)
    assert len(rejoined) >= len(dense) * 0.98


def test_hebrew_is_estimated_as_more_expensive_than_english():
    """
    The bug this guards: counting words treats a page of pointed Hebrew as the
    same size as a page of English, and it is several times larger in tokens.
    """
    from app.services.ingestion.reference_parsers import estimate_tokens

    hebrew = "נִשְׁמַת כָּל חַי תְּבָרֵךְ אֶת שִׁמְךָ"
    english = "The soul of every living thing shall bless Your name"

    assert len(hebrew.split()) <= len(english.split())
    assert estimate_tokens(hebrew) > estimate_tokens(english)


def test_every_reference_document_chunk_fits_the_embedding_limit():
    """The three corpus documents, checked as they are actually indexed."""
    from app.services.ingestion.reference_parsers import (
        MAX_EMBED_TOKENS,
        estimate_tokens,
    )

    if not (NISHMAT_FILE.exists() and TEHILLIM_FILE.exists()):
        pytest.skip("reference files are not present")

    everything = [
        *parse_nishmat(
            NISHMAT_FILE.read_text(encoding="utf-8"), variant="Edot HaMizrach"
        ),
        *parse_tehillim(_paragraphs(TEHILLIM_FILE)),
    ]
    if COMMENTARY_FILE.exists():
        everything += parse_commentary(
            _paragraphs(COMMENTARY_FILE), title="The Magnificent Nishmat Kol Chai"
        )

    oversized = [c.ref for c in everything if estimate_tokens(c.text) > MAX_EMBED_TOKENS]
    assert not oversized, f"chunks too large to embed: {oversized[:5]}"


def test_truncation_guard_only_trims_what_is_over_budget():
    from app.services.reference_indexing import _fit_to_budget
    from app.services.ingestion.reference_parsers import (
        MAX_EMBED_TOKENS,
        estimate_tokens,
    )

    small = "a short piece of reference text"
    assert _fit_to_budget(small) == small

    huge = "נִשְׁמַת כָּל חַי " * 4000
    trimmed = _fit_to_budget(huge)
    assert len(trimmed) < len(huge)
    assert estimate_tokens(trimmed) <= MAX_EMBED_TOKENS


# ====================================================== lesson references ==
#
# A learner asking "what does lesson 112 say" was answered from whichever
# lessons happened to talk about lessons. They score around 0.4, clear the
# grounding threshold, and the answer named the wrong lesson with complete
# confidence — worse than no answer, because nothing about it looks wrong.


@pytest.mark.parametrize(
    "question,expected",
    [
        ("what is lesson 112", 112),
        ("tell me the important points from lesson 112", 112),
        ("summarise lesson number 90", 90),
        ("lesson no. 44", 44),
        ("shiur #65", 65),
        ("Lesson#7", 7),
        ("what did class 12 cover", 12),
    ],
)
def test_a_named_lesson_is_recognised(question, expected):
    from app.services.retrieval_service import lesson_reference

    assert lesson_reference(question) == expected


@pytest.mark.parametrize(
    "question",
    [
        "what does Moshia mean",
        "psalm 112 is beautiful",          # a Psalm, not a lesson
        "what is 112",                     # a bare number is not a reference
        "compare lesson 4 and lesson 9",   # two lessons: scoping cannot serve it
        "tell me about gratitude",
    ],
)
def test_questions_that_do_not_name_a_lesson(question):
    from app.services.retrieval_service import lesson_reference

    assert lesson_reference(question) is None


def test_the_text_query_keeps_numbers():
    """
    `[^\W\d_]` excluded digits, so "lesson 112" reduced to "lesson" — throwing
    away the one token in the question that identified anything.
    """
    from app.services.retrieval_service import build_text_query

    assert "112" in build_text_query("what is lesson 112")


def test_the_text_query_still_drops_stopwords():
    """The fix must not undo §8.6 — bare terms are ANDed and match nothing."""
    from app.services.retrieval_service import build_text_query

    query = build_text_query("What does Moshia mean?")
    assert query == "moshia"


# ================================================== complete-lesson retrieval ==
#
# "Give me lesson 109 exactly as stored" is a RETRIEVAL, not a question. It was
# being answered by the generative path, which capped the answer at 800 tokens
# and cut lesson #109 off mid-sentence at roughly 71% of its length. 73 of the
# 131 published lessons are longer than that cap.


@pytest.mark.parametrize(
    "question",
    [
        "Retrieve Lesson #109 and return the COMPLETE original transcript exactly as stored.",
        "give me the full text of lesson 63",
        "show me lesson 11 in full",
        "lesson 99 verbatim please",
        "I want the entire lesson 24",
        "print the whole transcript of shiur 56",
        "reproduce lesson 1 word-for-word",
        "the unedited lesson 88",
    ],
)
def test_a_request_for_the_stored_lesson_is_recognised(question):
    from app.services.retrieval_service import verbatim_request

    assert verbatim_request(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "what is lesson 109 about",
        "summarise lesson 63",
        "tell me the important points from lesson 112",
        "what does Moshia mean",
        # "complete" without asking for the lesson itself — still a question.
        "give me a complete picture of what lesson 4 teaches",
        "how complete is the series",
    ],
)
def test_ordinary_questions_are_not_treated_as_verbatim_requests(question):
    """
    Both halves must be present. Treating "a complete picture of lesson 4" as a
    dump request would replace a thoughtful answer with 700 words of raw text.
    """
    from app.services.retrieval_service import verbatim_request

    assert verbatim_request(question) is False


def test_verbatim_and_lesson_number_detection_compose():
    """The two signals are independent: the request needs both to fire."""
    from app.services.retrieval_service import lesson_reference, verbatim_request

    q = "Retrieve Lesson #109 and return the COMPLETE original transcript exactly as stored."
    assert lesson_reference(q) == 109
    assert verbatim_request(q) is True


def test_the_verbatim_answer_contains_the_stored_text_byte_for_byte():
    """
    The header may be added above it; the lesson itself must not be touched.
    Anything that reflows, trims or re-wraps the body destroys the line breaks
    this author uses as punctuation.
    """
    from app.services.chat_service import _verbatim_answer

    stored = "Line one.\n\nLine two.\nStill line two's stanza.\n\n  trailing spaces  "
    full = {
        "lesson_id": "abc",
        "lesson_number": 109,
        "title": "V'HaKadosh",
        "transliteration": "V'HaKadosh",
        "word_count": 9,
        "content_text": stored,
    }

    answer = _verbatim_answer(full, 0.0)

    assert stored in answer.content, "the stored text was altered"
    assert answer.content.endswith(stored), "something was appended after the lesson"
    assert answer.grounded is True
    assert answer.citations[0]["lesson_number"] == 109
    # No model was involved, so nothing was spent beyond what was passed in.
    assert answer.cost_usd == 0.0
