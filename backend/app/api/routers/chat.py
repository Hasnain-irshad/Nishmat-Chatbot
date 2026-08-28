"""
The learner chatbot.

Any signed-in person may use this — it is the one AI surface learners touch.
Everything it can reach is already public to them: it answers only from
published lessons, enforced inside the SQL search function.

Conversations are strictly private. A learner sees only their own, and an admin
gets no special read on anyone else's — someone's questions about their own
struggles are not management information.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep
from app.db import supabase
from app.llm.types import BudgetExceeded, LLMError
from app.logging import get_logger
from app.services import chat_service

log = get_logger("api.chat")

router = APIRouter(prefix="/chat", tags=["chat"])


# ------------------------------------------------------------------ schemas


class ConversationSummary(BaseModel):
    id: str
    title: str
    lesson_id: str | None
    message_count: int
    last_message_at: str | None
    created_at: str
    updated_at: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list[dict] = Field(default_factory=list)
    created_at: str


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut] = Field(default_factory=list)


class NewConversation(BaseModel):
    lesson_id: str | None = None
    title: str | None = Field(default=None, max_length=200)


class NewMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AnswerOut(BaseModel):
    question: MessageOut
    answer: MessageOut
    grounded: bool
    conversation_title: str


class RenameConversation(BaseModel):
    title: str = Field(min_length=1, max_length=200)


# ------------------------------------------------------------ conversations


@router.post("/conversations", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    payload: NewConversation, user: CurrentUserDep
) -> ConversationSummary:
    if payload.lesson_id:
        lesson = await supabase.service().select(
            "lessons",
            columns="id",
            filters={
                "id": f"eq.{payload.lesson_id}",
                "status": "eq.published",
                "deleted_at": "is.null",
            },
            single=True,
        )
        if not lesson:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "That lesson isn't available."
            )

    rows = await user.db().insert(
        "conversations",
        {
            "user_id": user.id,
            "lesson_id": payload.lesson_id,
            "title": payload.title or "New conversation",
        },
    )
    return ConversationSummary(**_conversation_fields(_one(rows)))


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    user: CurrentUserDep,
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ConversationSummary]:
    filters = {"user_id": f"eq.{user.id}"}
    if not include_archived:
        filters["archived_at"] = "is.null"

    rows = await user.db().select(
        "conversations",
        columns=(
            "id, title, lesson_id, message_count, last_message_at, "
            "created_at, updated_at"
        ),
        filters=filters,
        order="last_message_at.desc.nullslast",
        limit=limit,
    )
    return [ConversationSummary(**_conversation_fields(row)) for row in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str, user: CurrentUserDep
) -> ConversationDetail:
    conversation = await _owned(user, conversation_id)

    rows = await user.db().select(
        "messages",
        columns="id, role, content, citations, created_at",
        filters={"conversation_id": f"eq.{conversation_id}"},
        order="created_at.asc",
    )
    return ConversationDetail(
        **_conversation_fields(conversation),
        messages=[MessageOut(**row) for row in rows if row["role"] != "system"],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str, payload: RenameConversation, user: CurrentUserDep
) -> ConversationSummary:
    await _owned(user, conversation_id)
    rows = await user.db().update(
        "conversations", {"id": f"eq.{conversation_id}"}, {"title": payload.title}
    )
    return ConversationSummary(**_conversation_fields(_one(rows)))


@router.delete("/conversations/{conversation_id}", status_code=204, response_model=None)
async def delete_conversation(conversation_id: str, user: CurrentUserDep) -> None:
    await _owned(user, conversation_id)
    await user.db().delete("conversations", {"id": f"eq.{conversation_id}"})


# --------------------------------------------------------------- messaging


@router.post("/conversations/{conversation_id}/messages", response_model=AnswerOut)
async def send_message(
    conversation_id: str, payload: NewMessage, user: CurrentUserDep
) -> AnswerOut:
    conversation = await _owned(user, conversation_id)
    db = user.db()
    service_db = supabase.service()

    question = payload.content.strip()
    history, summary = await chat_service.load_history(conversation_id)

    try:
        result = await chat_service.answer(
            question=question,
            history=history,
            summary=summary,
            lesson_id=conversation.get("lesson_id"),
            user_id=user.id,
            conversation_id=conversation_id,
        )
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    except LLMError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The assistant isn't responding right now. Please try again shortly.",
        ) from None

    stored_question = _one(
        await db.insert(
            "messages",
            {"conversation_id": conversation_id, "role": "user", "content": question},
        )
    )
    stored_answer = _one(
        await db.insert(
            "messages",
            {
                "conversation_id": conversation_id,
                "role": "assistant",
                "content": result.content,
                "citations": result.citations,
            },
        )
    )

    title = conversation.get("title") or "New conversation"
    if title == "New conversation" and not history:
        title = await chat_service.suggest_title(question, result.content)

    count = (conversation.get("message_count") or 0) + 2
    await db.update(
        "conversations",
        {"id": f"eq.{conversation_id}"},
        {
            "title": title,
            "message_count": count,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        },
        returning=False,
    )

    # Record spend against this conversation, and compact if it has grown long.
    if result.cost_usd:
        log.info(
            "chat_answered",
            conversation_id=conversation_id,
            grounded=result.grounded,
            passages=len(result.passages),
            cost=round(result.cost_usd, 5),
        )
    await chat_service.maybe_summarise(conversation_id)

    return AnswerOut(
        question=MessageOut(**_message_fields(stored_question)),
        answer=MessageOut(**_message_fields(stored_answer)),
        grounded=result.grounded,
        conversation_title=title,
    )


# ------------------------------------------------------------------ helpers


async def _owned(user, conversation_id: str) -> dict:
    """Fetch a conversation, or 404 — never confirm someone else's exists."""
    conversation = await user.db().select(
        "conversations",
        columns=(
            "id, user_id, title, lesson_id, summary, message_count, "
            "last_message_at, created_at, updated_at"
        ),
        filters={"id": f"eq.{conversation_id}"},
        single=True,
    )
    if not conversation or conversation.get("user_id") != user.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That conversation was not found."
        )
    return conversation


def _one(rows):
    return rows[0] if isinstance(rows, list) else rows


def _conversation_fields(row: dict) -> dict:
    return {
        "id": row["id"],
        "title": row.get("title") or "New conversation",
        "lesson_id": row.get("lesson_id"),
        "message_count": row.get("message_count") or 0,
        "last_message_at": row.get("last_message_at"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_fields(row: dict) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "citations": row.get("citations") or [],
        "created_at": row["created_at"],
    }
