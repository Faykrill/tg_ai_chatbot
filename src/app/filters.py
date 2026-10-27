"""Фильтры обновлений: привязка к темам и адресность сообщений."""

from __future__ import annotations

from typing import Any

from aiogram.filters.base import Filter
from aiogram.types import Message

from app.chat_rules import prompt_from_message
from app.services import Services

__all__ = ["AddressedToBot", "TopicAllowed"]


class TopicAllowed(Filter):
    """Пускает сообщение дальше, если группа не «заперта» в другой теме."""

    async def __call__(self, message: Message, services: Services) -> bool:
        return not services.topics.is_blocked(message.chat.id, message.message_thread_id)


class AddressedToBot(Filter):
    """Пропускает только те текстовые сообщения, которые адресованы боту.

    В личке это любое сообщение, в группе — зависит от режима ``/chatmode``:
    ``mention`` требует @упоминания или reply на сообщение бота, ``all`` — нет.
    Готовый текст запроса кладётся в kwargs хендлера как ``prompt``, чтобы не
    считать адресацию дважды.
    """

    async def __call__(self, message: Message, services: Services) -> dict[str, Any] | bool:
        prompt = prompt_from_message(
            message,
            services.identity,
            services.group_modes.get(message.chat.id),
        )
        if not prompt:
            return False
        return {"prompt": prompt}
