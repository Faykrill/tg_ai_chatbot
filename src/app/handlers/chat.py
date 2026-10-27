"""Обычные текстовые сообщения: чат с ИИ с памятью диалога."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app import texts
from app.ai import AIError
from app.chat_rules import is_group_chat
from app.filters import AddressedToBot, TopicAllowed
from app.messaging import (
    answer_text,
    finalize_placeholder,
    send_long_text,
    send_thinking,
    send_typing,
)
from app.memory import DialogueKey
from app.prompts import Mode
from app.services import Services

__all__ = ["router"]

router = Router(name="chat")


@router.message(F.text, TopicAllowed(), AddressedToBot())
async def handle_text(
    message: Message,
    services: Services,
    prompt: str,
) -> None:
    """Отвечает через нейросеть и помнит историю диалога."""
    key = DialogueKey.from_message(message)
    await send_typing(message)
    placeholder = await send_thinking(message)

    try:
        result = await services.ai.generate(
            prompt,
            mode=Mode.CHAT,
            history=services.memory.history(key),
        )
    except AIError as exc:
        # Ошибку в память не пишем, чтобы следующий ответ не строился на ней.
        await finalize_placeholder(placeholder, message, exc.message)
        return

    services.memory.record_turn(key, prompt, result.text)
    await send_long_text(message, result.text, placeholder=placeholder)


@router.message(TopicAllowed())
async def handle_unsupported(message: Message, services: Services) -> None:
    """Реагирует на нетекстовые сообщения (в группах — молчит)."""
    if not is_group_chat(message):
        await answer_text(message, texts.NOT_TEXT)
