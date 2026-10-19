"""Chats API: list, create, rename, delete conversations, and ask questions inside one."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from documind.api.deps import ContainerDep, UserDep
from documind.api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    Exchange,
    MessageCreate,
    MessageOut,
)
from documind.chat.service import message_response
from documind.db.tables import Conversation, Message
from documind.domain.errors import BadRequest

router = APIRouter(prefix="/v1/conversations", tags=["chats"])


def _conv_out(c: Conversation) -> ConversationOut:
    return ConversationOut(
        id=c.id, title=c.title, document_ids=[uuid.UUID(d) for d in c.document_ids] if c.document_ids else None,
        created_at=c.created_at, updated_at=c.updated_at,
    )


def _msg_out(m: Message) -> MessageOut:
    return MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at,
                      response=message_response(m))


@router.get("", response_model=list[ConversationOut])
def list_conversations(container: ContainerDep, user: UserDep) -> list[ConversationOut]:
    return [_conv_out(c) for c in container.chats.list(user.id)]


@router.post("", status_code=201, response_model=ConversationOut)
def create_conversation(body: ConversationCreate, container: ContainerDep, user: UserDep) -> ConversationOut:
    return _conv_out(container.chats.create(user.id, body.title, body.document_ids))


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, container: ContainerDep, user: UserDep) -> ConversationDetail:
    conv, messages = container.chats.get(user.id, conversation_id)
    return ConversationDetail(conversation=_conv_out(conv), messages=[_msg_out(m) for m in messages])


@router.patch("/{conversation_id}", response_model=ConversationOut)
def update_conversation(conversation_id: uuid.UUID, body: ConversationUpdate, container: ContainerDep,
                        user: UserDep) -> ConversationOut:
    return _conv_out(container.chats.update(
        user.id, conversation_id, body.title, body.document_ids, body.clear_scope))


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, container: ContainerDep, user: UserDep) -> Response:
    container.chats.delete(user.id, conversation_id)
    return Response(status_code=204)


@router.post("/{conversation_id}/messages", response_model=Exchange)
def send_message(conversation_id: uuid.UUID, body: MessageCreate, container: ContainerDep,
                 user: UserDep) -> Exchange:
    settings = container.settings
    question = body.question.strip()
    if not question:
        raise BadRequest("Question is empty.")
    if len(question) > settings.max_question_chars:
        raise BadRequest(f"Question is longer than {settings.max_question_chars} characters.")
    top_k = min(body.top_k or settings.context_max_chunks, settings.max_top_k)  # may narrow, never raise
    conv, user_msg, assistant_msg = container.chats.send(user.id, conversation_id, question, top_k, body.debug)
    return Exchange(conversation=_conv_out(conv), user_message=_msg_out(user_msg),
                    assistant_message=_msg_out(assistant_msg))
