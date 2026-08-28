"""
Finding the right passages for a question.

Hybrid search — vector similarity fused with Postgres full-text — rather than
vectors alone. That choice is specific to this corpus: the highest-signal words
in a learner's question are usually transliterated Hebrew (*Moshia*, *chesed*,
*hakarat hatov*), and embedding models handle transliteration unevenly. Exact
lexical matching catches what the vectors miss, and the reverse holds for
"what does it mean when I feel like giving up" — a question sharing no words
with the lesson that answers it.

The published-only filter lives inside the SQL function, not here, so no bug in
this file can retrieve a draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import get_settings
from app.db import supabase
from app.llm.provider import get_provider
from app.llm.types import LLMError
from app.logging import get_logger

log = get_logger("services.retrieval")


@dataclass
class Passage:
    chunk_id: str
    lesson_id: str
    lesson_title: str
    lesson_number: int | None
    section_key: str | None
    text: str
    score: float
    """Fused RRF rank — good for ordering, meaningless as an absolute."""
    similarity: float
    """Cosine similarity — an absolute measure, used to decide grounding."""
    metadata: dict

    def citation(self) -> dict:
        return {
            "lesson_id": self.lesson_id,
            "lesson_number": self.lesson_number,
            "title": self.lesson_title,
            "section": self.metadata.get("section") or self.section_key,
        }

    def label(self) -> str:
        if self.lesson_number is not None:
            return f"Lesson #{self.lesson_number} — {self.lesson_title}"
        return self.lesson_title


# Words that carry no retrieval signal. Kept deliberately small — this is a
# search-query filter, not a linguistics exercise, and over-stripping is worse
# than under-stripping.
STOPWORDS = {
    "a", "about", "all", "am", "an", "and", "any", "anything", "are", "as",
    "ask", "at", "be", "been", "but", "can", "could", "did", "do", "does",
    "explain", "for", "from", "get", "give", "had", "has", "have", "how", "i",
    "if", "in", "into", "is", "it", "its", "just", "know", "like", "me",
    "mean", "means", "more", "my", "of", "on", "one", "or", "please", "say",
    "should", "so", "some", "something", "tell", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "to", "us",
    "was", "we", "were", "what", "when", "where", "which", "who", "why",
    "will", "with", "would", "you", "your",
}

# Letters OR digits. The digit half matters: `[^\W\d_]` excluded numbers, so
# "lesson 112" reduced to the single word "lesson" — throwing away the one
# token in the question that identified anything. See `lesson_reference`.
WORD = re.compile(r"[^\W_]+", re.UNICODE)


def build_text_query(question: str) -> str:
    """
    Turn a natural question into a lexical query the text index can use.

    `websearch_to_tsquery` ANDs bare terms, so "What does Moshia mean?" becomes
    `what & does & moshia & mean` — which matches nothing, because no chunk
    contains all four. The text arm then contributes nothing at all, and the one
    chunk in the corpus that actually says "Moshia" never surfaces.

    Dropping stopwords and OR-ing what remains fixes exactly that. It matters
    most for the terms this corpus turns on: transliterated Hebrew appears in a
    handful of chunks, so a single lexical hit is highly informative.
    """
    words = [w.lower() for w in WORD.findall(question or "")]
    terms = [w for w in words if len(w) > 2 and w not in STOPWORDS]

    if not terms:
        # Nothing distinctive to match on — let the vector arm answer alone
        # rather than OR-ing together a pile of stopwords.
        return ""

    # Preserve order, drop duplicates, and keep the query bounded.
    seen: set[str] = set()
    unique = [t for t in terms if not (t in seen or seen.add(t))]
    return " OR ".join(unique[:12])


# "lesson 112", "lesson #112", "shiur 112", "in lesson no. 112".
#
# Deliberately requires the WORD before the number. A bare "112" in a question
# is far more likely to be a Psalm, a year or a page than a lesson number, and
# scoping the whole answer to lesson 112 on that guess would be worse than not
# scoping at all.
LESSON_REFERENCE = re.compile(
    r"\b(?:lesson|shiur|sheur|class|episode)\s*(?:number\s*|no\.?\s*|#\s*)?(\d{1,4})\b",
    re.IGNORECASE,
)


def lesson_reference(question: str) -> int | None:
    """
    The lesson number a question names outright, if it names one.

    Which lesson "lesson 112" means is a FACT, not a similarity judgement —
    the same reasoning as looking a Psalm up by address rather than searching
    for it. Left to the vector index, "what is lesson 112 about" returns
    whichever lessons happen to talk about lessons, scores around 0.4, clears
    the grounding threshold, and the learner is confidently told about a
    different lesson entirely.
    """
    matches = LESSON_REFERENCE.findall(question or "")
    if len(set(matches)) != 1:
        # No reference, or two different ones ("compare lesson 4 and lesson 9"),
        # which is a request scoping cannot serve.
        return None
    return int(matches[0])


async def resolve_lesson_number(number: int) -> tuple[str | None, bool]:
    """
    Map a lesson number to its id.

    Returns `(lesson_id, exists)`. The two differ: a lesson that exists but is
    not published must not be retrievable, and must not be reported as missing
    either — "that lesson isn't published yet" and "there is no such lesson"
    are different things to tell a learner.
    """
    try:
        rows = await supabase.service().select(
            "lessons",
            columns="id, status",
            filters={"lesson_number": f"eq.{number}", "deleted_at": "is.null"},
            limit=1,
        )
    except supabase.SupabaseError as exc:
        log.warning("lesson_number_lookup_failed", number=number, error=str(exc))
        return None, False

    if not rows:
        return None, False

    row = rows[0]
    published = row.get("status") == "published"
    return (row["id"] if published else None), True


async def search(
    question: str,
    *,
    lesson_id: str | None = None,
    limit: int | None = None,
) -> list[Passage]:
    """
    Retrieve passages for a question.

    `lesson_id` scopes the search to one lesson — used when a learner asks from
    inside the reader, where "explain the second idea" means *this* lesson.
    """
    settings = get_settings()
    top_k = limit or settings.rag_top_k

    if not question or not question.strip():
        return []

    provider = get_provider()
    try:
        embeddings = await provider.embed([question], operation="embedding")
        vector = embeddings.vectors[0]
    except LLMError as exc:
        log.warning("query_embedding_failed", error=str(exc))
        return []

    try:
        rows = await supabase.service().rpc(
            "search_published_chunks",
            {
                "query_embedding": vector,
                "query_text": build_text_query(question),
                "match_count": top_k,
                "filter_lesson_id": lesson_id,
            },
        )
    except supabase.SupabaseError as exc:
        log.error("retrieval_failed", error=str(exc))
        return []

    passages = [
        Passage(
            chunk_id=row["chunk_id"],
            lesson_id=row["lesson_id"],
            lesson_title=row.get("lesson_title") or "Untitled lesson",
            lesson_number=row.get("lesson_number"),
            section_key=row.get("section_key"),
            text=row.get("chunk_text") or "",
            score=float(row.get("score") or 0),
            similarity=float(row.get("similarity") or 0),
            metadata=row.get("metadata") or {},
        )
        for row in (rows or [])
    ]

    log.info(
        "retrieved",
        question_words=len(question.split()),
        scoped=bool(lesson_id),
        found=len(passages),
        best_similarity=round(passages[0].similarity, 3) if passages else 0,
    )
    return passages


def is_grounded(passages: list[Passage]) -> bool:
    """
    Is there enough here to answer from?

    Gated on cosine SIMILARITY, not on the fused rank score. Rank tells you
    which passage is best; only similarity tells you whether the best one is
    actually any good. A question the corpus cannot answer still produces a
    rank-1 result — it is just a poor one.

    When nothing clears the bar we skip the model entirely and say so. That is
    cheaper and faster, and it makes "I don't have that in the lessons" a
    deterministic outcome rather than something we hope the model chooses.
    """
    if not passages:
        return False
    return passages[0].similarity >= get_settings().rag_min_score


def build_context(passages: list[Passage], *, max_chars: int = 9000) -> str:
    """Format retrieved passages for the prompt, newest-scoring first."""
    blocks: list[str] = []
    used = 0

    for index, passage in enumerate(passages, start=1):
        section = passage.metadata.get("section")
        heading = f"[{index}] {passage.label()}"
        if section:
            heading += f" — {section}"

        block = f"{heading}\n{passage.text.strip()}"
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)

    return "\n\n---\n\n".join(blocks)
