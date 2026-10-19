"""Chats: saved conversations, rename/delete, and follow-up-aware questions.

A chat belongs to one owner and every query filters on `owner_id`, so another user's chat is a 404.
Sending a message runs the same RAG pipeline as /v1/query, but first turns a follow-up question
("et le prix ?") into a standalone one using the recent messages, and stores both messages.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from documind.api.query_response import build_query_response
from documind.api.schemas import QueryResponse
from documind.chat.rewrite import QuestionRewriter
from documind.config import Settings
from documind.db.session import transaction
from documind.db.tables import Conversation, Message
from documind.domain.errors import NotFound
from documind.domain.models import SearchFilters
from documind.rag.query_pipeline import QueryPipeline

TITLE_CHARS = 60


def shorten_title(question: str) -> str:
    line = " ".join(question.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


class ChatService:
    def __init__(self, sf: sessionmaker[Session], pipeline: QueryPipeline, rewriter: QuestionRewriter,
                 settings: Settings) -> None:
        self.sf = sf
        self.pipeline = pipeline
        self.rewriter = rewriter
        self.settings = settings

    # ── conversations ────────────────────────────────────
    def list(self, owner_id: uuid.UUID) -> list[Conversation]:
        with self.sf() as s:
            return list(s.scalars(
                select(Conversation).where(Conversation.owner_id == owner_id)
                .order_by(Conversation.updated_at.desc(), Conversation.id)
            ))

    def create(self, owner_id: uuid.UUID, title: str | None, document_ids: list[uuid.UUID] | None) -> Conversation:
        now = datetime.now(UTC)
        conv = Conversation(
            id=uuid.uuid4(), owner_id=owner_id, title=(title or "").strip(),
            document_ids=[str(d) for d in document_ids] if document_ids else None, created_at=now, updated_at=now,
        )
        with transaction(self.sf) as s:
            s.add(conv)
        return conv

    def get(self, owner_id: uuid.UUID, conversation_id: uuid.UUID) -> tuple[Conversation, list[Message]]:
        with self.sf() as s:
            conv = self._owned(s, owner_id, conversation_id)
            messages = list(s.scalars(
                select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
            ))
        return conv, messages

    def update(self, owner_id: uuid.UUID, conversation_id: uuid.UUID, title: str | None,
               document_ids: list[uuid.UUID] | None, clear_scope: bool) -> Conversation:
        with transaction(self.sf) as s:
            conv = self._owned(s, owner_id, conversation_id)
            if title is not None:
                conv.title = title.strip()
            if clear_scope:
                conv.document_ids = None
            elif document_ids is not None:
                conv.document_ids = [str(d) for d in document_ids]
        return conv

    def delete(self, owner_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        with transaction(self.sf) as s:
            conv = self._owned(s, owner_id, conversation_id)
            s.execute(delete(Conversation).where(Conversation.id == conv.id))  # messages cascade

    # ── sending a message ────────────────────────────────
    def send(self, owner_id: uuid.UUID, conversation_id: uuid.UUID, question: str, top_k: int,
             debug: bool) -> tuple[Conversation, Message, Message]:
        conv, past = self.get(owner_id, conversation_id)
        history = self._history(past)

        asked_at = datetime.now(UTC)
        rewrite = self.rewriter.rewrite(history, question)
        scope = [uuid.UUID(d) for d in conv.document_ids] if conv.document_ids else None
        filters = SearchFilters(owner_id=owner_id, document_ids=scope)
        result = self.pipeline.run(rewrite.question, filters, top_k, history)
        response = build_query_response(result, debug, rewrite.question if rewrite.rewritten else None)
        if rewrite.rewritten:  # count the extra small-model call in the totals shown to the user
            response.usage.input_tokens += rewrite.input_tokens
            response.usage.output_tokens += rewrite.output_tokens
            response.latency_ms["rewrite"] = rewrite.latency_ms

        g = result.generated
        answered_at = datetime.now(UTC)
        user_msg = Message(id=uuid.uuid4(), conversation_id=conv.id, owner_id=owner_id, role="user",
                           content=question, payload={}, created_at=asked_at)
        assistant_msg = Message(
            id=uuid.uuid4(), conversation_id=conv.id, owner_id=owner_id, role="assistant",
            content=g.answer or g.abstention_message or "", payload=response.model_dump(mode="json"),
            created_at=answered_at,
        )
        with transaction(self.sf) as s:
            stored = self._owned(s, owner_id, conversation_id)
            s.add_all([user_msg, assistant_msg])
            if not stored.title:
                stored.title = shorten_title(question)
            stored.updated_at = answered_at
        return stored, user_msg, assistant_msg

    # ── helpers ──────────────────────────────────────────
    def _history(self, messages: list[Message]) -> list[dict[str, str]]:
        n = self.settings.chat_history_messages
        recent = messages[-n:] if n else []
        return [{"role": m.role, "content": m.content} for m in recent if m.content]

    @staticmethod
    def _owned(s: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
        conv = s.scalar(select(Conversation).where(Conversation.id == conversation_id,
                                                   Conversation.owner_id == owner_id))
        if conv is None:
            raise NotFound("Conversation not found.")
        return conv


def message_response(message: Message) -> QueryResponse | None:
    if message.role == "assistant" and message.payload:
        return QueryResponse.model_validate(message.payload)
    return None
