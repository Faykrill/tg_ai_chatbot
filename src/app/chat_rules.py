"""Правила общения бота: группы, упоминания, ответы боту, аргументы команд."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Final

from aiogram.types import Message

from app.stores import GroupMode

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from app.services import BotIdentity

__all__ = [
    "bot_is_mentioned",
    "get_command_args",
    "is_group_chat",
    "is_reply_to_bot",
    "prompt_from_message",
    "strip_mention",
]

#: Типы чатов, которые Telegram считает группами.
GROUP_CHAT_TYPES: Final[tuple[str, ...]] = ("group", "supergroup")


def is_group_chat(message: Message) -> bool:
    """True для обычных и супергрупп (не для лички и каналов)."""
    return message.chat.type in GROUP_CHAT_TYPES


def get_command_args(message: Message) -> str:
    """Возвращает текст команды после её названия (``/joke про котов`` → ``про котов``)."""
    if not message.text:
        return ""
    parts = message.text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


@lru_cache(maxsize=32)
def _mention_pattern(username: str) -> re.Pattern[str]:
    """Кеширует регулярку упоминания, чтобы не компилировать её на каждое сообщение."""
    return re.compile(re.escape(f"@{username}"), re.IGNORECASE)


def bot_is_mentioned(message: Message, identity: "BotIdentity") -> bool:
    """Проверяет, упомянут ли бот в тексте сообщения."""
    text = message.text or ""

    # 1. Самый надёжный способ: через сущности (entities) Telegram
    for entity in message.entities or ():
        if entity.type == "mention":
            # В aiogram 3 у MessageEntity нет .text, вырезаем срезом по offset и length
            mention = text[entity.offset : entity.offset + entity.length]
            if identity.username and mention.lower() == identity.mention.lower():
                return True
        elif entity.type == "text_mention":
            # Если упомянули по имени (без @, но со ссылкой на профиль бота)
            if entity.user is not None and entity.user.id == identity.user_id:
                return True

    # 2. Резервный способ: поиск по тексту (на случай, если entities не сработали)
    return bool(identity.username) and identity.mention.lower() in text.lower()


def is_reply_to_bot(message: Message, identity: "BotIdentity") -> bool:
    """True, если сообщение — ответ (reply) на сообщение бота."""
    reply = message.reply_to_message
    if reply is None or reply.from_user is None or not identity.user_id:
        return False
    return reply.from_user.id == identity.user_id


def strip_mention(text: str, identity: "BotIdentity") -> str:
    """Убирает @упоминание бота из текста, чтобы не мешало нейросети."""
    if not identity.username:
        return text.strip()
    return _mention_pattern(identity.username).sub("", text).strip()


def prompt_from_message(
    message: Message,
    identity: "BotIdentity",
    mode: GroupMode = GroupMode.MENTION,
) -> str | None:
    """Текст запроса к ИИ либо None, если сообщение боту не адресовано.

    * в личке относим на сообщение всё, что прислали текстом;
    * в группе в режиме ``all`` — любое текстовое сообщение;
    * в группе в режиме ``mention`` — только @упоминание или reply на бота.
    """
    text = message.text or ""
    if not is_group_chat(message):
        return text

    if mode is GroupMode.ALL:
        return text

    if bot_is_mentioned(message, identity) or is_reply_to_bot(message, identity):
        return strip_mention(text, identity) or text
    return None
