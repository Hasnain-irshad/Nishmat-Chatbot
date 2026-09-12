"""
The learner chatbot.

    question
       │
       ├─ 1. REWRITE    "the second idea" → a standalone question   (cheap model)
       ├─ 2. RETRIEVE   hybrid search over published lessons only
       ├─ 3. GROUND     weak match? say so, without calling a model
       ├─ 4. ANSWER     from the passages, with citations           (mid model)
       └─ 5. REMEMBER   window + rolling summary, bounded

Two decisions worth naming.

**Query rewriting** is the single most valuable call in this path. Without it,
"can you explain the second idea?" embeds to noise — it shares no meaningful
words with any lesson. Rewriting it against the last few messages costs a
fraction of a cent on the cheapest model and is the difference between a
follow-up question working and not.

**Memory is bounded** — the last N messages verbatim plus a rolling summary of
what came before. Sending an entire conversation back every turn grows cost
without bound and buries the current question in old context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings
from app.db import supabase
from app.llm.provider import get_provider
from app.llm.types import BudgetExceeded, LLMError, Message
from app.logging import get_logger
from app.services import retrieval_service, transcript_search
from app.services.retrieval_service import Passage

log = get_logger("services.chat")


ANSWER_SYSTEM = """You help someone learning from a weekly Torah series.

You answer ONLY from the lesson excerpts you are given. They are the teacher's
own published words, and they are your only source.

- If the excerpts answer the question, answer warmly and directly, the way a
  friend who has studied these lessons would.
- If they only partly answer it, say what the lessons do say, and be plain
  about what they do not.
- If they do not answer it, say so kindly and suggest what the lessons do
  cover. Never fill the gap from your own knowledge — a learner will believe
  the teacher said it.
- Never invent a Torah source, a quotation, or a teaching. If it is not in the
  excerpts, it does not go in your answer.
- Refer to lessons by number when it helps: "Lesson #17 talks about this."
  Use ONLY the numbers in the excerpt headings you were given. Lesson numbers
  sometimes appear inside the body of an excerpt as well — those refer to other
  lessons and are not yours to cite. If you are unsure which lesson a point came
  from, describe it without a number.
- Keep Hebrew exactly as it appears, with its vowel points.
- Do not correct yourself mid-sentence. Decide, then write.

Write conversationally and fairly briefly — a few short paragraphs. You are
answering a question, not writing a lesson. Do not open with "Great question"
or any similar filler.

HOW TO LAY THE ANSWER OUT

The reader sees rendered formatting, so use it — but lightly. A short answer
needs no structure at all; reach for it when the answer genuinely has parts.

- **Bold** a lesson's number and title the first time you name it, like
  **Lesson #109 — V'HaKadosh**. It is the thing the reader scans for.
- Use "## " headings only when the answer covers several distinct topics, and
  put the topic itself in the heading.
- Use "- " for lists. Never number a list — write "- " even for a sequence.
- Use "---" on its own line only to separate major topics, never between every
  paragraph.
- Keep Hebrew on its own line where it stands alone, so it reads right-to-left
  cleanly.

Two habits to avoid, because they read as padding: restating the question back
before answering it, and closing with an offer to help further unless you are
genuinely naming something specific you can do next."""

REWRITE_SYSTEM = """Rewrite the user's latest message as a standalone search query.

Resolve every pronoun and reference against the conversation. "The second idea"
or "explain that more" must become an explicit question naming the actual
subject.

Output ONLY the rewritten query. No preamble, no quotes. If the message is
already standalone, output it unchanged."""

TITLE_SYSTEM = """Give this conversation a short title — three to six words, no
quotes, no trailing punctuation. Describe what is being discussed."""


NOT_FOUND = (
    "I don't have anything in the lessons that answers that yet. "
    "The series works through the words of Nishmat Kol Chai one phrase at a "
    "time — try asking about one of those, or about something a particular "
    "lesson covered."
)


def _no_such_lesson(number: int) -> str:
    return (
        f"There isn't a lesson {number} in the series yet. "
        f"Try another number, or ask about a phrase of Nishmat Kol Chai and "
        f"I'll find the lesson it belongs to."
    )


def _lesson_not_published(number: int) -> str:
    return (
        f"Lesson {number} hasn't been published yet, so I can't teach from it. "
        f"Ask me about any of the published lessons and I'll answer from those."
    )


def _verbatim_answer(full: dict, spent: float) -> "ChatAnswer":
    """
    Hand back the stored lesson itself.

    No model is involved, on purpose. Asked to reproduce 700 words exactly, a
    model paraphrases — and nothing in the output reveals that it did. The
    teacher asking for her own lesson back has no way to spot a sentence that
    drifted, which makes a generated "copy" worse than useless here.

    The header is the only thing added, and it sits above a blank line so the
    lesson below it is byte-identical to what is stored.
    """
    number = full["lesson_number"]
    heading = f"Lesson #{number} — {full['title']}"
    if full.get("transliteration") and full["transliteration"] not in full["title"]:
        heading += f" ({full['transliteration']})"

    # Markdown in the header only. Everything below the blank line is the stored
    # lesson, untouched — the renderer treats single newlines as significant, so
    # her line breaks survive, and no markdown is introduced into her prose.
    header = (
        f"## {heading}\n\n"
        f"*The complete lesson as stored — {full['word_count']} words, "
        f"reproduced exactly, not summarised.*\n\n---"
    )

    return ChatAnswer(
        content=f"{header}\n\n{full['content_text']}",
        citations=[
            {
                "lesson_id": full["lesson_id"],
                "lesson_number": number,
                "title": full["title"],
                "section": None,
            }
        ],
        grounded=True,
        cost_usd=spent,
    )


MAX_LESSONS_LISTED = 40


def _title_case(topic: str) -> str:
    """
    Present a topic as a heading without mangling it.

    `str.title()` is wrong here — it would render "Podeh u'Matzil" as
    "Podeh U'Matzil" and "aseret yemei teshuva" loses nothing by staying as the
    admin typed it. Only a fully lower-case topic is capitalised, and only at
    the front.
    """
    topic = topic.strip()
    if not topic:
        return topic
    return topic[0].upper() + topic[1:] if topic.islower() else topic


async def _survey_answer(question: str, spent: float) -> "ChatAnswer | None":
    """
    "Which lessons did I write about X" — answered from the COMPLETE corpus.

    The chunk index cannot answer this. It returns the six passages closest to
    the question, so a six-topic request came back citing four lessons and
    saying the excerpts did not cover the rest — which was true of the excerpts
    and false of the corpus. `transcript_search` reads every published lesson's
    full text instead, so "not found" means not there.

    Returns the matching lessons, not their transcripts. Fifty complete lessons
    is most of the corpus and unreadable in a chat bubble; each one can then be
    asked for by number and comes back verbatim.
    """
    from app.services import transcript_search

    topics = transcript_search.topics_in(question)
    if not topics:
        return None

    blocks: list[str] = []
    citations: list[dict] = []
    total_found = 0

    for topic in topics:
        matches = await transcript_search.search_topic(topic)
        total_found += len(matches)

        if not matches:
            blocks.append(
                f"## {_title_case(topic)}\n\n"
                f"No lesson mentions this. Searched the complete text of all "
                f"{len(await transcript_search.load_corpus())} published "
                f"lessons, not retrieved excerpts."
            )
            continue

        shown = matches[:MAX_LESSONS_LISTED]
        count = f"{len(matches)} lesson{'' if len(matches) == 1 else 's'}"
        if len(matches) > len(shown):
            count += f", showing the {len(shown)} with the most mentions"

        lines = [f"## {_title_case(topic)}\n", f"*{count}*\n"]
        for match in shown:
            lines.append(
                f"- **#{match.lesson_number} — {match.title}**  \n"
                f"  {match.hits} mention{'' if match.hits == 1 else 's'} · "
                f"{match.word_count} words"
            )
            citations.append(
                {
                    "lesson_id": match.lesson_id,
                    "lesson_number": match.lesson_number,
                    "title": match.title,
                    "section": None,
                }
            )
        blocks.append("\n".join(lines))

    body = "\n\n---\n\n".join(blocks)
    footer = (
        "\n\n---\n\n"
        "*Searched the complete stored text of every published lesson — titles, "
        "Hebrew and transliteration included — not retrieved excerpts.*\n\n"
        "Ask for any of these by number to get the full lesson exactly as "
        'stored, e.g. **"send me the complete transcript of lesson 9"**.'
    )

    log.info("answer_corpus_survey", topics=len(topics), matches=total_found)
    return ChatAnswer(
        content=body + footer,
        citations=citations[:60],
        grounded=True,
        cost_usd=spent,
    )


@dataclass
class ChatAnswer:
    content: str
    citations: list[dict] = field(default_factory=list)
    grounded: bool = True
    passages: list[Passage] = field(default_factory=list)
    cost_usd: float = 0.0


# ============================================================= the answer ==


async def answer(
    *,
    question: str,
    history: list[dict],
    summary: str | None = None,
    lesson_id: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> ChatAnswer:
    settings = get_settings()
    provider = get_provider()
    spent = 0.0

    # ---- 1. make the question standalone -------------------------------
    search_query = question
    if history:
        try:
            rewritten, usage = await _rewrite(provider, question, history)
            spent += usage
            if rewritten:
                search_query = rewritten
        except (LLMError, BudgetExceeded) as exc:
            # Falling back to the raw question degrades follow-ups but still
            # answers; failing the whole turn would be worse.
            log.warning("query_rewrite_failed", error=str(exc))

    # ---- 2. retrieve ----------------------------------------------------
    #
    # A question that NAMES a lesson gets scoped to that lesson.
    #
    # Which lesson "lesson 112" means is a fact, not a similarity judgement.
    # Left to the vector index it was answered from whichever lessons happened
    # to talk about lessons — they score around 0.4, comfortably clear the
    # grounding threshold, and the learner was confidently told about a
    # different lesson entirely. Being told the wrong lesson's content is worse
    # than being told nothing, because nothing about the answer looks wrong.
    # A survey of the corpus — "which lessons cover X" — is answered from every
    # published lesson's COMPLETE text, before any of the chunk-based paths get
    # a look in. Checked on the raw question: the rewrite is tuned to produce a
    # single good search query and collapses a multi-topic request into one.
    if not lesson_id and transcript_search.survey_request(question):
        survey = await _survey_answer(question, spent)
        if survey:
            return survey

    scoped_to = lesson_id
    named_lesson: int | None = None
    if not scoped_to:
        number = retrieval_service.lesson_reference(search_query)
        if number is not None:
            resolved, exists = await retrieval_service.resolve_lesson_number(number)
            if not exists:
                log.info("answer_no_such_lesson", number=number)
                return ChatAnswer(
                    content=_no_such_lesson(number), grounded=False, cost_usd=spent
                )
            if not resolved:
                log.info("answer_lesson_unpublished", number=number)
                return ChatAnswer(
                    content=_lesson_not_published(number),
                    grounded=False,
                    cost_usd=spent,
                )
            # A request for the lesson ITSELF is a retrieval, not a question.
            # It is served from the database and never sees a model: asked to
            # reproduce 700 words exactly, a model paraphrases, and the output
            # gives no sign that it did.
            #
            # Checked against the raw question as well as the rewritten one,
            # because the rewrite is tuned to produce a good *search query* and
            # will happily drop the word "complete" on the way.
            if retrieval_service.verbatim_request(
                question
            ) or retrieval_service.verbatim_request(search_query):
                full = await retrieval_service.load_full_lesson(number)
                if full:
                    log.info(
                        "answer_verbatim_lesson",
                        number=number,
                        chars=len(full["content_text"]),
                        words=full["word_count"],
                    )
                    return _verbatim_answer(full, spent)

            scoped_to = resolved
            named_lesson = number
            log.info("answer_scoped_to_lesson", number=number, lesson_id=resolved)

    passages = await retrieval_service.search(search_query, lesson_id=scoped_to)

    # ---- 3. refuse deterministically if nothing matched ------------------
    #
    # The similarity gate exists to stop us answering from material that has
    # nothing to do with the question. When the learner NAMED the lesson, that
    # judgement is already made — the lesson they asked for is the right
    # material whatever the cosine score says, and a question phrased loosely
    # ("anything interesting in lesson 3?") can score low against a lesson it
    # is unambiguously about. Telling them "I don't have anything in the
    # lessons" about a lesson we just located would be simply wrong.
    grounded = retrieval_service.is_grounded(passages)
    if named_lesson is not None and passages:
        grounded = True

    if not grounded:
        log.info("answer_ungrounded", scoped=bool(scoped_to))
        return ChatAnswer(content=NOT_FOUND, grounded=False, cost_usd=spent)

    # ---- 4. answer -------------------------------------------------------
    context = retrieval_service.build_context(passages)

    messages: list[Message] = [Message(role="system", content=ANSWER_SYSTEM)]

    if summary:
        messages.append(
            Message(
                role="system",
                content=f"Earlier in this conversation: {summary}",
            )
        )

    for entry in history[-settings.chat_history_window :]:
        role = entry.get("role")
        if role in ("user", "assistant") and entry.get("content"):
            messages.append(Message(role=role, content=entry["content"]))

    messages.append(
        Message(
            role="user",
            content=(
                f"Lesson excerpts:\n\n{context}\n\n"
                f"---\n\nThe question: {question}"
            ),
        )
    )

    try:
        completion = await provider.complete(
            messages,
            operation="chat",
            temperature=0.6,
            max_tokens=settings.chat_max_answer_tokens,
        )
        spent += completion.usage.estimated_cost
    except BudgetExceeded:
        raise
    except LLMError as exc:
        log.error("chat_answer_failed", error=str(exc))
        raise

    # Cite only the lessons actually drawn on, deduplicated.
    citations: list[dict] = []
    seen: set[str] = set()
    for passage in passages:
        if passage.lesson_id not in seen:
            seen.add(passage.lesson_id)
            citations.append(passage.citation())

    return ChatAnswer(
        content=completion.text.strip(),
        citations=citations[:4],
        grounded=True,
        passages=passages,
        cost_usd=spent,
    )


async def _rewrite(provider, question: str, history: list[dict]) -> tuple[str, float]:
    recent = history[-4:]
    transcript = "\n".join(
        f"{entry['role']}: {entry['content'][:400]}"
        for entry in recent
        if entry.get("content")
    )

    completion = await provider.complete(
        [
            Message(role="system", content=REWRITE_SYSTEM),
            Message(
                role="user",
                content=f"Conversation so far:\n{transcript}\n\nLatest message: {question}",
            ),
        ],
        operation="utility",
        temperature=0.0,
        max_tokens=120,
    )
    rewritten = completion.text.strip().strip('"')
    # A rewrite that balloons is usually the model answering instead of rewriting.
    if len(rewritten) > 400:
        return question, completion.usage.estimated_cost
    return rewritten, completion.usage.estimated_cost


# ================================================================ memory ==


async def load_history(conversation_id: str) -> tuple[list[dict], str | None]:
    """Recent messages verbatim, plus the rolling summary of what came before."""
    settings = get_settings()
    db = supabase.service()

    conversation = await db.select(
        "conversations",
        columns="id, summary, message_count",
        filters={"id": f"eq.{conversation_id}"},
        single=True,
    )
    if not conversation:
        return [], None

    rows = await db.select(
        "messages",
        columns="role, content, created_at",
        filters={"conversation_id": f"eq.{conversation_id}"},
        order="created_at.desc",
        limit=settings.chat_history_window,
    )
    history = [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows or [])
        if row.get("role") in ("user", "assistant")
    ]
    return history, conversation.get("summary")


async def maybe_summarise(conversation_id: str) -> None:
    """
    Compact older turns once a conversation gets long.

    Runs after answering, so it never delays a reply. Failure is silent — a
    missing summary costs a little context, not the conversation.
    """
    settings = get_settings()
    db = supabase.service()

    conversation = await db.select(
        "conversations",
        columns="id, message_count, summary",
        filters={"id": f"eq.{conversation_id}"},
        single=True,
    )
    if not conversation:
        return
    if (conversation.get("message_count") or 0) < settings.chat_summary_threshold:
        return

    rows = await db.select(
        "messages",
        columns="role, content, created_at",
        filters={"conversation_id": f"eq.{conversation_id}"},
        order="created_at.asc",
    )
    older = (rows or [])[: -settings.chat_history_window]
    if len(older) < 4:
        return

    transcript = "\n".join(
        f"{row['role']}: {row['content'][:500]}" for row in older if row.get("content")
    )

    try:
        completion = await get_provider().complete(
            [
                Message(
                    role="system",
                    content=(
                        "Summarise this conversation in under 150 words, for use as "
                        "context in the rest of it. Keep the lessons discussed, the "
                        "questions asked, and any thread still open. Plain prose."
                    ),
                ),
                Message(role="user", content=transcript),
            ],
            operation="utility",
            temperature=0.2,
            max_tokens=260,
        )
        await db.update(
            "conversations",
            {"id": f"eq.{conversation_id}"},
            {"summary": completion.text.strip()[:2000]},
            returning=False,
        )
        log.info("conversation_summarised", conversation_id=conversation_id)
    except (LLMError, BudgetExceeded, supabase.SupabaseError) as exc:
        log.warning("summarise_failed", conversation_id=conversation_id, error=str(exc))


async def suggest_title(question: str, answer_text: str) -> str:
    """Name a conversation from its first exchange."""
    fallback = question.strip()[:60] or "New conversation"
    try:
        completion = await get_provider().complete(
            [
                Message(role="system", content=TITLE_SYSTEM),
                Message(
                    role="user",
                    content=f"Question: {question}\n\nAnswer: {answer_text[:600]}",
                ),
            ],
            operation="utility",
            temperature=0.3,
            max_tokens=30,
        )
        title = completion.text.strip().strip('"').rstrip(".")
        return title[:80] or fallback
    except (LLMError, BudgetExceeded):
        return fallback
