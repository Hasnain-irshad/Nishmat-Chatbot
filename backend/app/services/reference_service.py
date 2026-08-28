"""
Deciding what the writer needs to see, and finding it.

The premise of this module is that the sources are NOT interchangeable. A
stanza of the prayer, a Psalm it quotes, an essay about the prayer, and a
photographed page of a commentary are four different kinds of thing, and a
single ranked list over all of them is the wrong answer to every question:

  * the essay always outranks the verse it discusses, because it shares more
    vocabulary with an English query than vocalised Hebrew does;
  * "which Psalm does this line come from" has one correct answer, and
    similarity search will happily return a near miss;
  * a page from a book the client owns is not a search result at all — the
    admin deliberately sent it for this lesson, and it should simply be there.

So each source class is retrieved its own way and returned in its own slot,
and the prompt keeps them apart all the way to the model.

Retrieval order also matters: the Nishmat stanza is found FIRST, and the
Psalms are then found from the stanza's own text rather than from the admin's
topic. When the prayer quotes Tehillim 35:10, that is a fact about the text,
not a guess to be made from a similarity score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.db import supabase
from app.llm.provider import get_provider
from app.llm.types import LLMError
from app.logging import get_logger
from app.services.ingestion.base import has_hebrew
from app.services.ingestion.reference_parsers import strip_marks

log = get_logger("services.reference")

# The nusach the client davens. Everything else is a different text, and
# teaching a phrase this siddur does not contain would be a real error.
DEFAULT_NUSACH = "Edot HaMizrach"


# ================================================================= brief ==


@dataclass
class LessonBrief:
    """
    What the admin asked for.

    Every field is optional and any one of them is enough to generate from.
    The client's lessons are built around all of these in practice — sometimes
    a phrase, sometimes a single word, sometimes "something for Elul".
    """

    phrase: str | None = None
    """A Nishmat phrase, in Hebrew or transliterated."""
    hebrew_word: str | None = None
    theme: str | None = None
    psalm: str | None = None
    """A Psalm reference: "34", "34:19", "Tehillim 34"."""
    commentator: str | None = None
    seasonal: str | None = None
    objective: str | None = None
    length: str | None = None
    """short | standard | long — a steer, not a quota."""
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "LessonBrief":
        data = data or {}
        return cls(
            **{
                field_name: _clean(data.get(field_name))
                for field_name in (
                    "phrase", "hebrew_word", "theme", "psalm", "commentator",
                    "seasonal", "objective", "length", "notes",
                )
            }
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}

    @property
    def is_empty(self) -> bool:
        return not any(
            (self.phrase, self.hebrew_word, self.theme, self.psalm,
             self.commentator, self.objective, self.notes)
        )

    def topic_query(self) -> str:
        """One string describing the lesson, for embedding."""
        parts = [
            self.phrase, self.hebrew_word, self.theme, self.objective,
            self.commentator, self.seasonal, self.notes,
        ]
        return ". ".join(p for p in parts if p).strip()

    def describe(self) -> list[str]:
        """Human-readable lines for the prompt and for the admin."""
        labels = {
            "phrase": "Nishmat phrase",
            "hebrew_word": "Hebrew word",
            "theme": "Theme",
            "psalm": "Psalm",
            "commentator": "Commentator or source",
            "seasonal": "Time of year",
            "objective": "What this lesson should do",
            "notes": "Additional instructions",
        }
        return [f"{label}: {getattr(self, key)}" for key, label in labels.items()
                if getattr(self, key)]


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# ================================================================ result ==


@dataclass
class ReferenceItem:
    kind: str
    authority: str
    ref: str | None
    heading: str | None
    text: str
    title: str
    attribution: str | None = None
    variant: str | None = None
    similarity: float = 0.0
    is_lesson_scoped: bool = False
    metadata: dict = field(default_factory=dict)

    def citation(self) -> str:
        parts = [p for p in (self.ref, self.attribution) if p]
        return " — ".join(parts) if parts else self.title


@dataclass
class ReferenceBundle:
    """The four reference slots, kept apart deliberately."""

    primary_text: list[ReferenceItem] = field(default_factory=list)
    scripture: list[ReferenceItem] = field(default_factory=list)
    interpretation: list[ReferenceItem] = field(default_factory=list)
    uploaded_pages: list[ReferenceItem] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)
    """What retrieval could and could not find — shown to the admin."""

    @property
    def is_empty(self) -> bool:
        return not (
            self.primary_text or self.scripture
            or self.interpretation or self.uploaded_pages
        )

    def all_items(self) -> list[ReferenceItem]:
        return [
            *self.primary_text, *self.scripture,
            *self.interpretation, *self.uploaded_pages,
        ]

    def summary(self) -> dict:
        return {
            "primary_text": [i.ref for i in self.primary_text],
            "scripture": [i.ref for i in self.scripture],
            "interpretation": [i.ref for i in self.interpretation],
            "uploaded_pages": [i.ref for i in self.uploaded_pages],
            "notes": self.notes,
        }


# ============================================================= retrieval ==


async def retrieve(
    brief: LessonBrief,
    *,
    lesson_id: str | None = None,
    source_text: str | None = None,
) -> ReferenceBundle:
    """
    Assemble the reference bundle for one generation.

    `source_text` is the lesson's own transcript when there is one. It is used
    to steer retrieval — a recording that dwells on healing should pull the
    healing stanza — but is never itself a reference; it is the lesson.
    """
    bundle = ReferenceBundle()

    # ---- SOURCE F: what the admin deliberately attached ------------------
    #
    # Fetched first and unconditionally. An admin who photographed three pages
    # of ArtScroll for this lesson has already made the relevance judgement,
    # and re-litigating it with a similarity score would be a way of ignoring
    # them.
    if lesson_id:
        bundle.uploaded_pages = await _lesson_pages(lesson_id)

    query = brief.topic_query()
    if not query and source_text:
        # No brief — steer from the opening of the transcript, which is where
        # this teacher states the phrase she is teaching.
        query = " ".join(source_text.split()[:250])

    # ---- SOURCE A: the prayer itself -------------------------------------
    bundle.primary_text = await _nishmat_passages(brief, query)
    if not bundle.primary_text:
        bundle.notes.append(
            "No Nishmat passage matched this lesson. The prayer text may not be "
            "indexed yet."
        )

    # ---- SOURCE B: the Psalms --------------------------------------------
    bundle.scripture = await _tehillim_passages(brief, query, bundle.primary_text)

    # ---- SOURCE C: interpretive material ---------------------------------
    bundle.interpretation = await _interpretation(brief, query)

    log.info(
        "references_retrieved",
        lesson_id=lesson_id,
        primary=len(bundle.primary_text),
        scripture=len(bundle.scripture),
        interpretation=len(bundle.interpretation),
        uploaded=len(bundle.uploaded_pages),
    )
    return bundle


# ---------------------------------------------------------------- Nishmat --


async def _nishmat_passages(brief: LessonBrief, query: str) -> list[ReferenceItem]:
    """
    The stanza this lesson is about.

    An exact Hebrew match is tried first. When the admin pastes a phrase from
    the siddur, the correct stanza is a fact, and answering a fact with a
    similarity score is how a lesson ends up teaching the wrong line.
    """
    stanzas = await _load_nishmat()
    if not stanzas:
        return []

    needle = brief.phrase or brief.hebrew_word
    if needle and has_hebrew(needle):
        matched = _match_stanza(stanzas, needle)
        if matched:
            return matched

    if not query:
        return []

    hits = await _vector_search(query, kinds=["nishmat_text"], count=2)
    return hits


def _match_stanza(stanzas: list[ReferenceItem], needle: str) -> list[ReferenceItem]:
    """
    Find the stanza containing a phrase, ignoring vowel points.

    Ignoring them is not sloppiness: the admin will paste from a website, from
    the client's own document, or type it, and those three sources point Hebrew
    differently. The consonants are what is actually fixed.
    """
    target = strip_marks(needle)
    if len(target) < 3:
        return []

    for stanza in stanzas:
        if target in strip_marks(stanza.text):
            return [stanza]

    # Fall back to the longest run of words that does match — a phrase spanning
    # a stanza break, or one typed with a word slightly off, should still land
    # somewhere sensible rather than nowhere.
    words = target.split()
    for size in range(len(words) - 1, 2, -1):
        for start in range(0, len(words) - size + 1):
            fragment = " ".join(words[start : start + size])
            for stanza in stanzas:
                if fragment in strip_marks(stanza.text):
                    return [stanza]
    return []


async def _load_nishmat(variant: str = DEFAULT_NUSACH) -> list[ReferenceItem]:
    """
    The whole prayer, every stanza.

    Loaded in full rather than searched: it is roughly a dozen short stanzas.
    Paying for an embedding round trip to narrow down twelve rows would cost
    more than reading all twelve.
    """
    try:
        rows = await supabase.service().rpc(
            "lookup_reference_chunks",
            {
                "p_kind": "nishmat_text",
                "p_variant": variant,
                "p_refs": None,
                "p_limit": 60,
            },
        )
    except supabase.SupabaseError as exc:
        log.warning("nishmat_load_failed", error=str(exc))
        return []

    return [_item(row) for row in (rows or [])]


# --------------------------------------------------------------- Tehillim --


PSALM_REF = re.compile(
    r"(?:tehill?im|tehilim|psalms?|ps\.?)\s*(\d{1,3})(?::(\d{1,3}))?", re.IGNORECASE
)
BARE_PSALM = re.compile(r"^\s*(\d{1,3})(?::(\d{1,3}))?\s*$")


async def _tehillim_passages(
    brief: LessonBrief, query: str, nishmat: list[ReferenceItem]
) -> list[ReferenceItem]:
    """
    The Psalms this lesson needs.

    Three routes, in descending order of certainty:

      1. the admin named one — an address, so look it up by address;
      2. the Nishmat stanza QUOTES one — verified against the stored text, so
         we learn it from the corpus instead of guessing;
      3. nothing explicit — fall back to similarity on the topic.
    """
    wanted: list[int] = []

    if brief.psalm:
        wanted.extend(_parse_psalm_numbers(brief.psalm))

    for item in nishmat:
        wanted.extend(await _psalms_quoted_in(item))

    items: list[ReferenceItem] = []
    seen_refs: set[str] = set()

    for number in _dedupe(wanted)[:4]:
        for item in await _load_psalm(number):
            if item.ref and item.ref not in seen_refs:
                seen_refs.add(item.ref)
                items.append(item)

    if items:
        return items[:6]

    if not query:
        return []

    hits = await _vector_search(query, kinds=["scripture"], count=3)
    return hits


def _parse_psalm_numbers(text: str) -> list[int]:
    numbers = [int(m.group(1)) for m in PSALM_REF.finditer(text)]
    if not numbers:
        bare = BARE_PSALM.match(text)
        if bare:
            numbers = [int(bare.group(1))]
    return [n for n in numbers if 1 <= n <= 150]


async def _psalms_quoted_in(stanza: ReferenceItem) -> list[int]:
    """
    Which Psalms a Nishmat stanza actually quotes.

    Asked of the database, not of a model. Each line of the stanza is checked
    for a literal (unpointed) occurrence in the stored Tehillim; a hit is
    proof, and a miss costs nothing. This is the whole reason the Psalms are
    stored rather than recalled: "וְכָתוּב: רַנְּנוּ צַדִּיקִים בַּיהוָה" is
    Tehillim 33:1 whether or not a model remembers that it is.
    """
    lines = stanza.metadata.get("lines") or stanza.text.splitlines()
    found: list[int] = []
    db = supabase.service()

    for line in lines[:16]:
        line = line.strip().strip(":,.;")
        # Three words, not four. The two verses Nishmat actually quotes are
        # "רַנְּנוּ צַדִּיקִים בַּיהוָה" (Tehillim 33:1) and the opening of
        # Tehillim 35:10, and this file breaks them across lines of three words
        # — at a four-word floor the prayer's own citations go undetected,
        # which is the one case this exists for. The letter count keeps a short
        # line from matching half the psalter.
        if len(line.split()) < 3 or len(line.replace(" ", "")) < 12:
            continue
        if not has_hebrew(line):
            continue
        try:
            rows = await db.rpc(
                "verify_hebrew_quote", {"p_quote": line, "p_kinds": ["scripture"]}
            )
        except supabase.SupabaseError as exc:
            log.warning("quote_lookup_failed", error=str(exc))
            return found

        for row in rows or []:
            numbers = _parse_psalm_numbers(row.get("ref") or "")
            found.extend(numbers)

    return found


async def _load_psalm(number: int) -> list[ReferenceItem]:
    """
    Every chunk of one psalm, in order.

    Filtered on the psalm number in the chunk's metadata rather than on its
    `ref` string: a short psalm is stored as "Tehillim 34" and a long one as
    "Tehillim 119:1-12", so matching the address would mean reconstructing the
    exact window boundaries the indexer happened to choose.

    Capped at three chunks — the opening of Psalm 119 is enough to teach from,
    and all 176 verses would crowd every other source out of the prompt.
    """
    try:
        rows = await supabase.service().select(
            "reference_chunks",
            columns=(
                "ref, heading, chunk_text, kind, authority, metadata, "
                "reference_documents(title, attribution, variant)"
            ),
            filters={
                "kind": "eq.scripture",
                "lesson_id": "is.null",
                "metadata->>psalm": f"eq.{number}",
            },
            order="chunk_index.asc",
            limit=3,
        )
    except supabase.SupabaseError as exc:
        log.warning("psalm_load_failed", psalm=number, error=str(exc))
        return []

    return [_nested_item(row) for row in rows or []]


# ----------------------------------------------------------- commentary --


async def _interpretation(brief: LessonBrief, query: str) -> list[ReferenceItem]:
    """
    Interpretive material from the permanent corpus.

    Excludes lesson-scoped uploads, which have their own slot: mixing them
    would let a ranked list drop a page the admin explicitly sent in favour of
    a paragraph of an essay.
    """
    terms = " ".join(p for p in (brief.commentator, brief.theme, query) if p)
    if not terms:
        return []
    return await _vector_search(terms, kinds=["commentary", "transcript", "translation"], count=4)


async def _lesson_pages(lesson_id: str) -> list[ReferenceItem]:
    """
    Everything uploaded for this lesson.

    Not a search. The admin chose these pages; the system's job is to put them
    in front of the writer, in the order they were sent.
    """
    try:
        rows = await supabase.service().select(
            "reference_chunks",
            columns=(
                "ref, heading, chunk_text, kind, authority, metadata, "
                "reference_documents(title, attribution, variant)"
            ),
            filters={"lesson_id": f"eq.{lesson_id}"},
            order="chunk_index.asc",
            limit=24,
        )
    except supabase.SupabaseError as exc:
        log.warning("lesson_pages_failed", lesson_id=lesson_id, error=str(exc))
        return []

    return [_nested_item(row, lesson_scoped=True) for row in rows or []]


# ------------------------------------------------------------------ shared --


async def _vector_search(
    query: str, *, kinds: list[str], count: int, lesson_id: str | None = None
) -> list[ReferenceItem]:
    from app.services.retrieval_service import build_text_query

    try:
        provider = get_provider()
        embeddings = await provider.embed([query[:4000]], operation="embedding")
        vector = embeddings.vectors[0]
    except LLMError as exc:
        log.warning("reference_embed_failed", error=str(exc))
        return []

    try:
        rows = await supabase.service().rpc(
            "match_reference_chunks",
            {
                "query_embedding": vector,
                "query_text": build_text_query(query),
                "match_count": count,
                "filter_kinds": kinds,
                "filter_lesson_id": lesson_id,
                "include_global": True,
            },
        )
    except supabase.SupabaseError as exc:
        log.warning("reference_search_failed", kinds=kinds, error=str(exc))
        return []

    return [_item(row) for row in (rows or [])]


def _item(row: dict) -> ReferenceItem:
    return ReferenceItem(
        kind=row.get("kind") or "other",
        authority=row.get("authority") or "client_supplied",
        ref=row.get("ref"),
        heading=row.get("heading"),
        text=row.get("chunk_text") or "",
        title=row.get("title") or "Reference",
        attribution=row.get("attribution"),
        variant=row.get("variant"),
        similarity=float(row.get("similarity") or 0),
        is_lesson_scoped=bool(row.get("is_lesson_scoped")),
        metadata=row.get("metadata") or {},
    )


def _nested_item(row: dict, *, lesson_scoped: bool = False) -> ReferenceItem:
    """Build an item from a PostgREST row that embedded its parent document."""
    parent = row.get("reference_documents") or {}
    if isinstance(parent, list):
        parent = parent[0] if parent else {}

    return ReferenceItem(
        kind=row.get("kind") or "other",
        authority=row.get("authority") or "client_supplied",
        ref=row.get("ref"),
        heading=row.get("heading"),
        text=row.get("chunk_text") or "",
        title=parent.get("title") or "Reference",
        attribution=parent.get("attribution"),
        variant=parent.get("variant"),
        is_lesson_scoped=lesson_scoped,
        metadata=row.get("metadata") or {},
    )


def _dedupe(values: list[int]) -> list[int]:
    seen: set[int] = set()
    return [v for v in values if not (v in seen or seen.add(v))]


# ========================================================== availability ==


async def corpus_status() -> list[dict]:
    """
    What is actually in the corpus right now.

    Surfaced to the admin because "the system does not have an English Nishmat"
    is something they need to know before wondering why a lesson has no English
    quotations, and because a silent empty corpus looks identical to a working
    one until a lesson comes out wrong.
    """
    try:
        rows = await supabase.service().select(
            "reference_documents",
            columns="id, title, kind, authority, variant, language, attribution, "
                    "notes, is_active, metadata, updated_at",
            filters={"lesson_id": "is.null"},
            order="kind.asc",
        )
    except supabase.SupabaseError as exc:
        log.warning("corpus_status_failed", error=str(exc))
        return []

    return [
        {
            "id": row["id"],
            "title": row["title"],
            "kind": row["kind"],
            "authority": row["authority"],
            "variant": row.get("variant"),
            "language": row.get("language"),
            "attribution": row.get("attribution"),
            "chunks": (row.get("metadata") or {}).get("chunk_count"),
            "is_active": row.get("is_active", True),
            "updated_at": row.get("updated_at"),
        }
        for row in rows or []
    ]
